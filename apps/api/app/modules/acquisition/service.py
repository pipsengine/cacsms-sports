"""Authorized observation ingestion, provenance checks, and temporal-safe feature materialization."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from sqlalchemy import select
from app.db import models as m

ALLOWED_SECTIONS=frozenset(('standings','recent_form','head_to_head','team_news','lineups','injuries','match_statistics','official_result'))

def utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return value.astimezone(timezone.utc)

def validate_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('A public HTTPS evidence URL is required')
    host=parsed.hostname.lower()
    if host in ('localhost','localhost.localdomain') or host.endswith(('.local','.internal')) or host.startswith(('127.','10.','192.168.','169.254.')):
        raise ValueError('Private/internal evidence URLs are not accepted')
    return url

def fingerprint(source_id, fixture_id, section, url, observed_at, payload):
    canonical=json.dumps({'source_id':source_id,'fixture_id':fixture_id,'section':section,'url':url,'observed_at':utc(observed_at).isoformat(),'payload':payload},sort_keys=True,separators=(',',':'),default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()

def ingest_observation(session, *, source_id, fixture_id, section, source_url, observed_at, payload):
    source=session.get(m.Source,source_id)
    if source is None or source.permission!='AUTHORIZED' or not source.enabled:
        raise PermissionError('Source is not enabled and authorized')
    fixture=session.get(m.Fixture,fixture_id)
    if fixture is None:raise ValueError('Unknown fixture')
    if section not in ALLOWED_SECTIONS:raise ValueError('Unsupported research section')
    validate_url(source_url)
    observed=utc(observed_at)
    if observed>datetime.now(timezone.utc):raise ValueError('Future-dated observation')
    if not isinstance(payload,dict) or not payload:raise ValueError('Nonempty structured evidence required')
    if section=='official_result':
        from app.modules.results.service import validate_result_payload
        if observed<utc(fixture.kickoff_at):raise ValueError('Final result precedes kickoff')
        payload=validate_result_payload(payload)
    if payload.get('fixture_id') not in (None,fixture_id):raise ValueError('Evidence fixture identity mismatch')
    content={'section':section,'data':payload}
    digest=fingerprint(source_id,fixture_id,section,source_url,observed,content)
    existing=session.scalar(select(m.Observation).where(m.Observation.source_id==source_id,m.Observation.content_hash==digest))
    if existing:return {'id':existing.id,'duplicate':True,'content_hash':digest}
    record=m.Observation(source_id=source_id,fixture_id=fixture_id,source_url=source_url,content_hash=digest,observed_at=observed,payload=content)
    session.add(record);session.flush()
    return {'id':record.id,'duplicate':False,'content_hash':digest}

def build_feature_snapshot(session, *, research_id, cutoff_at, required_sections):
    dossier=session.get(m.Research,research_id)
    if dossier is None:raise ValueError('Unknown research dossier')
    fixture=session.get(m.Fixture,dossier.fixture_id)
    cutoff=utc(cutoff_at)
    if cutoff>=utc(fixture.kickoff_at):raise ValueError('Feature cutoff must precede fixture kickoff')
    if not required_sections or len(set(required_sections))!=len(required_sections) or set(required_sections)-ALLOWED_SECTIONS:
        raise ValueError('Provide distinct supported required sections')
    output={}; used=[]
    for section in required_sections:
        entry=dossier.sections.get(section,{})
        if entry.get('status')!='VERIFIED':raise ValueError('Required research section is not verified: '+section)
        refs=entry.get('evidence_ids',[])
        if not refs:raise ValueError('Verified section lacks evidence: '+section)
        values=[]
        for evidence_id in refs:
            obs=session.get(m.Observation,evidence_id)
            if obs is None or obs.fixture_id!=dossier.fixture_id:raise ValueError('Evidence fixture mismatch')
            source=session.get(m.Source,obs.source_id)
            if source is None or source.permission!='AUTHORIZED' or not source.enabled:raise ValueError('Evidence source no longer authorized')
            if utc(obs.observed_at)>cutoff:raise ValueError('Evidence was observed after the feature cutoff')
            if obs.payload.get('section')!=section:raise ValueError('Evidence section mismatch')
            values.append(obs.payload['data']);used.append(obs.id)
        output[section]=values
    snapshot=m.Feature(research_id=research_id,cutoff_at=cutoff,features={'sections':output,'evidence_ids':sorted(set(used)),'schema_version':'1.0'})
    session.add(snapshot);session.flush()
    return {'id':snapshot.id,'research_id':research_id,'cutoff_at':cutoff.isoformat(),'sections':list(output),'evidence_ids':sorted(set(used)),'status':'MATERIALIZED_NOT_MODEL_APPROVED'}
