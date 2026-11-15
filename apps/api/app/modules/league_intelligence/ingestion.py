"""Validate authorized standings documents and import into the shared research schema.

The caller owns the transaction. Dry-run validation does not connect to a database.
Re-importing pending evidence never promotes it to verified.
"""
from __future__ import annotations
import hashlib
import ipaddress
import json
from datetime import date, datetime, timezone
from urllib.parse import urlparse
from typing import Any

REQUIRED = ('club','position','played','won','drawn','lost','goals_for','goals_against','points')
VIEWS = {'overall','home','away'}

class ImportValidationError(ValueError):
    pass


def timestamp(value, name='as_of'):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('Timezone required')
    except (AttributeError,TypeError,ValueError) as exc:
        raise ImportValidationError(f'{name} must be a timezone-aware ISO timestamp') from exc
    if stamp > datetime.now(timezone.utc):
        raise ImportValidationError(f'Future {name} is invalid')
    return stamp.astimezone(timezone.utc)


def validate_source_url(value):
    if not isinstance(value,str):
        raise ImportValidationError('source_url must be a public HTTPS URL')
    parsed=urlparse(value)
    host=(parsed.hostname or '').lower()
    if parsed.scheme!='https' or not host or parsed.username or parsed.password or host=='localhost' or host.endswith(('.local','.internal')):
        raise ImportValidationError('source_url must be a public HTTPS URL')
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        address=None
    if address is not None and not address.is_global:
        raise ImportValidationError('Private/internal source URLs are not accepted')


def validate_document(doc: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(doc,dict):
        raise ImportValidationError('Expected JSON object')
    clean=dict(doc)
    for key,maximum in [('sport',100),('country',100),('competition',200),('season',100),('source',120)]:
        value=doc.get(key)
        if not isinstance(value,str) or not value.strip() or len(value.strip())>maximum:
            raise ImportValidationError(f'Missing or invalid {key}')
        clean[key]=value.strip()
    if doc.get('view') not in VIEWS:
        raise ImportValidationError('Invalid standings view')
    if 'source_reference' in doc and (not isinstance(doc['source_reference'],str) or not doc['source_reference'].strip() or len(doc['source_reference'])>1000):
        raise ImportValidationError('Invalid source_reference')
    stamp=timestamp(doc.get('as_of'))
    clean['as_of']=stamp.isoformat()
    validate_source_url(doc.get('source_url'))
    rows=doc.get('entries')
    if not isinstance(rows,list) or not 2<=len(rows)<=100:
        raise ImportValidationError('Standings must contain 2-100 entries')
    names=set();positions=set();normalized=[]
    for index,row in enumerate(rows):
        if not isinstance(row,dict) or any(k not in row for k in REQUIRED):
            raise ImportValidationError(f'Incomplete entry {index}')
        name=row['club']
        if not isinstance(name,str) or not name.strip() or len(name.strip())>200:
            raise ImportValidationError(f'Invalid club in entry {index}')
        name=name.strip()
        if name.casefold() in names:
            raise ImportValidationError('Duplicate club')
        names.add(name.casefold())
        for key in REQUIRED[1:]:
            if type(row[key]) is not int or (key!='points' and row[key]<0):
                raise ImportValidationError(f'Invalid {key} in entry {index}')
        if row['position'] in positions:
            raise ImportValidationError('Duplicate rank')
        positions.add(row['position'])
        if row['played']!=row['won']+row['drawn']+row['lost']:
            raise ImportValidationError('Played does not equal W+D+L')
        form=row.get('form')
        if form is not None and (not isinstance(form,str) or len(form)>30 or set(form)-set('WDL')):
            raise ImportValidationError('Invalid form')
        normalized.append(dict({key:row[key] for key in REQUIRED},club=name,form=form))
    if positions!=set(range(1,len(rows)+1)):
        raise ImportValidationError('Ranks must be contiguous')
    clean['entries']=sorted(normalized,key=lambda r:r['position'])
    if 'official' in clean and type(clean['official']) is not bool:
        raise ImportValidationError('official must be a boolean')
    if not isinstance(clean.get('provenance',{}),dict):
        raise ImportValidationError('provenance must be an object')
    start,end=clean.get('season_start'),clean.get('season_end')
    if start is not None or end is not None:
        try:
            start,end=date.fromisoformat(start),date.fromisoformat(end)
            if end<start:raise ValueError('date order')
        except (TypeError,ValueError) as exc:
            raise ImportValidationError('season_start and season_end must be ordered ISO dates') from exc
    # Review metadata cannot change document identity to promote an existing pending import.
    identity={k:v for k,v in clean.items() if k not in ('reviewed_by','reviewed_at','verified_at')}
    try:
        canonical=json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError) as exc:
        raise ImportValidationError('Document must contain finite JSON values') from exc
    return dict(hash=hashlib.sha256(canonical.encode()).hexdigest(),as_of=stamp,entries=clean['entries'],
                document=clean,season_start=start,season_end=end)


def import_document(db,doc:dict[str,Any],*,approve:bool=False,dry_run:bool=False):
    parsed=validate_document(doc)
    clean=parsed['document']
    reviewer=clean.get('reviewed_by')
    if approve and (not isinstance(reviewer,str) or not reviewer.strip() or len(reviewer.strip())>200):
        raise ImportValidationError('Approval requires reviewed_by attribution')
    if dry_run:
        return dict(status='VALID',sha256=parsed['hash'],rows=len(parsed['entries']),approved=approve,
                    note='Structural validation only; source authorization and season identity are checked on import')
    from sqlalchemy import select,func,or_
    from app.db import models as m
    source=db.scalar(select(m.Source).where(m.Source.name==clean['source']))
    if not source or not source.enabled or source.permission!='AUTHORIZED':
        raise ImportValidationError('Source must be registered, enabled and AUTHORIZED')
    existing=db.scalar(select(m.StandingsSnapshot).where(m.StandingsSnapshot.source_id==source.id,
                                                       m.StandingsSnapshot.content_hash==parsed['hash']))
    if existing:
        return dict(status='EXISTS',snapshot_id=existing.id,approved=existing.review_status=='VERIFIED',
                    note='Existing evidence is immutable; re-import does not promote pending snapshots')
    sport=db.scalar(select(m.Sport).where(func.lower(m.Sport.name)==clean['sport'].lower()))
    if sport is None:
        sport=m.Sport(name=clean['sport']);db.add(sport);db.flush()
    candidates=db.scalars(select(m.Competition).where(m.Competition.sport_id==sport.id,
        m.Competition.name==clean['competition'],or_(m.Competition.country==clean['country'],m.Competition.country.is_(None)))).all()
    if len(candidates)>1:
        raise ImportValidationError('Ambiguous competition identity; resolve the catalogue before import')
    comp=candidates[0] if candidates else None
    if comp is None:
        comp=m.Competition(sport_id=sport.id,name=clean['competition'],country=clean['country']);db.add(comp);db.flush()
    elif comp.country is None:
        comp.country=clean['country']
    season=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp.id,
                                                     m.CompetitionSeason.label==clean['season']))
    if season is None:
        if parsed['season_start'] is None:
            raise ImportValidationError('Register the competition season first, or supply season_start and season_end; dates are never guessed')
        season=m.CompetitionSeason(competition_id=comp.id,label=clean['season'],start_date=parsed['season_start'],end_date=parsed['season_end'])
        db.add(season);db.flush()
    elif parsed['season_start'] is not None and (season.start_date!=parsed['season_start'] or season.end_date!=parsed['season_end']):
        raise ImportValidationError('Supplied dates conflict with the registered season')
    provenance=dict(clean.get('provenance',{}))
    for key in ('first_match_date','last_match_date'):
        if key in provenance:
            try:match_date=date.fromisoformat(provenance[key])
            except (TypeError,ValueError) as exc:raise ImportValidationError('Invalid CSV provenance date') from exc
            if not season.start_date<=match_date<=season.end_date:
                raise ImportValidationError('CSV results fall outside registered season dates')
    # CSV arithmetic remains provisional even after review; never label it official.
    computed=provenance.get('status')=='UNVERIFIED_COMPUTED'
    imported=datetime.now(timezone.utc)
    entries=[dict(club=r['club'],rank=r['position'],played=r['played'],wins=r['won'],draws=r['drawn'],losses=r['lost'],
                  goals_for=r['goals_for'],goals_against=r['goals_against'],goal_difference=r['goals_for']-r['goals_against'],
                  points=r['points'],form=r.get('form')) for r in parsed['entries']]
    snap=m.StandingsSnapshot(competition_id=comp.id,season_id=season.id,source_id=source.id,
        source_url=clean['source_url'],source_reference=clean.get('source_reference') or parsed['hash'],content_hash=parsed['hash'],
        captured_at=parsed['as_of'],verified_at=imported if approve else None,review_status='VERIFIED' if approve else 'PENDING_REVIEW',
        reviewed_by=reviewer.strip() if approve else None,imported_at=imported,official=False if computed else clean.get('official',False),
        scope=clean['view'],entries=entries,provenance=provenance)
    db.add(snap);db.flush()
    db.add(m.AuditEvent(actor=reviewer.strip() if approve else 'operator:standings-import',action='research.standings_imported',
        correlation_id=snap.id,payload={'sha256':parsed['hash'],'review_status':snap.review_status,'source_id':source.id,'provenance':provenance}))
    return dict(status='IMPORTED',snapshot_id=snap.id,competition_id=comp.id,season_id=season.id,rows=len(entries),
                approved=approve,sha256=parsed['hash'])
