"""Verified, authorized data ingestion; no synthetic sports observations."""
import hashlib,json
from datetime import datetime,timezone
from sqlalchemy import select
from app.db import models as m

def ingest_fixture(session, source_name, sport_name, competition_name, home, away, kickoff, source_url, evidence):
    if not isinstance(evidence,dict) or not evidence.get('source_reference'):
        raise ValueError('Source reference and provenance required')
    if kickoff.tzinfo is None or kickoff.utcoffset() is None:
        raise ValueError('Timezone-aware kickoff required')
    if not all([source_name,sport_name,competition_name,home,away,source_url]):
        raise ValueError('Missing mandatory fixture provenance')
    source=session.scalar(select(m.Source).where(m.Source.name==source_name))
    if not source or not source.enabled or source.permission!='AUTHORIZED':
        raise PermissionError('Source not explicitly authorized')
    sport=session.scalar(select(m.Sport).where(m.Sport.name==sport_name))
    if sport is None:
        sport=m.Sport(name=sport_name);session.add(sport);session.flush()
    comp=session.scalar(select(m.Competition).where(m.Competition.sport_id==sport.id,m.Competition.name==competition_name))
    if comp is None:
        comp=m.Competition(sport_id=sport.id,name=competition_name);session.add(comp);session.flush()
    fixture=session.scalar(select(m.Fixture).where(m.Fixture.competition_id==comp.id,m.Fixture.home_name==home,m.Fixture.away_name==away,m.Fixture.kickoff_at==kickoff))
    if fixture is None:
        fixture=m.Fixture(competition_id=comp.id,home_name=home,away_name=away,kickoff_at=kickoff);session.add(fixture);session.flush()
    payload={'source_reference':evidence['source_reference'],'fixture_id':fixture.id,'kickoff_at':kickoff.isoformat(),'home':home,'away':away,'source_data':evidence}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    observation=session.scalar(select(m.Observation).where(m.Observation.source_id==source.id,m.Observation.content_hash==digest))
    if observation is None:
        observation=m.Observation(source_id=source.id,fixture_id=fixture.id,source_url=source_url,content_hash=digest,payload=payload);session.add(observation)
    session.flush()
    return {'fixture_id':fixture.id,'observation_id':observation.id,'status':'EVIDENCE_CAPTURED','prediction_status':'NOT_ELIGIBLE'}
