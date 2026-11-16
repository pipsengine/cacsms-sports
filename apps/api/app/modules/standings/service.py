"""Football-Data CSV acquisition adapted to the canonical catalogue and worker.

Provider registrations use ProviderSyncState. Immutable captured CSV datasets use
Observation; neither computed scores nor tables become independently verified results.
"""
import csv,hashlib,io,json,re
from datetime import datetime,timedelta,timezone,date
from urllib.parse import urlparse
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc
from app.modules.autonomy.community_tables import build_tables

PREFIX='standings-csv:'
ADAPTER='football-data-csv'


def safe_source(url):
    p=urlparse(url)
    if (p.scheme!='https' or p.hostname not in {'www.football-data.co.uk','football-data.co.uk'}
        or p.port not in (None,443) or p.username or p.password or p.query or p.fragment
        or not re.fullmatch(r'/mmz4281/\d{4}/[A-Za-z0-9]+\.csv',p.path)):
        raise ValueError('Only canonical HTTPS football-data.co.uk season/division CSV URLs are supported')
    return url


def season_year(label):
    if not re.fullmatch(r'\d{4}/(?:\d{4}|\d{2})',label):
        raise ValueError('Season must use YYYY/YYYY or YYYY/YY')
    year=int(label[:4])
    if int(label.split('/')[1]) not in (year+1,(year+1)%100):
        raise ValueError('Season years must be consecutive')
    return year


def register(db,body):
    url=safe_source(body['source_url'])
    if body.get('sport','Football').casefold()!='football':raise ValueError('The CSV adapter supports football only')
    if urlparse(url).path.rsplit('/',1)[1][:-4]!=body['division_code']:raise ValueError('Division code does not match source URL')
    sport=db.scalar(select(m.Sport).where(func.lower(m.Sport.name)=='football'))
    if sport is None:sport=m.Sport(name='Football');db.add(sport);db.flush()
    comp=db.scalar(select(m.Competition).where(m.Competition.sport_id==sport.id,m.Competition.name==body['name'],m.Competition.country==body['country']))
    if comp is None:comp=m.Competition(sport_id=sport.id,name=body['name'],country=body['country']);db.add(comp);db.flush()
    key=PREFIX+body['id'];state=db.get(m.ProviderSyncState,key)
    if state and state.payload.get('competition_id')!=comp.id:raise ValueError('Registration ID already belongs to another competition')
    source_id=str(uuid5(NAMESPACE_URL,'football-data:'+body['id']))
    source=db.get(m.Source,source_id)
    if source is None:source=m.Source(id=source_id,name='Football-Data.co.uk: '+body['id']);db.add(source);db.flush()
    source.enabled=body['authorized'];source.permission='AUTHORIZED' if body['authorized'] else 'UNVERIFIED'
    if state is None:state=m.ProviderSyncState(id=key,source_id=source.id,payload={},failures=0);db.add(state)
    state.payload={**(state.payload or {}),'adapter':ADAPTER,'registration_id':body['id'],'competition_id':comp.id,
                   'source_url':url,'division_code':body['division_code'],'points_win':body.get('points_win',3)}
    state.next_check_at=datetime.now(timezone.utc)
    db.add(m.AuditEvent(actor='admin',action='standings.registered',correlation_id=comp.id,payload={'registration_id':body['id'],'authorized':body['authorized'],'source_url':url}))
    db.flush()
    return {'id':comp.id,'registration_id':body['id'],'authorized':source.enabled}


def download(url):
    import httpx
    safe_source(url)
    with httpx.Client(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':'CACSMSResearch/1.0 (authorized standings ingestion)'}) as client:
        with client.stream('GET',url) as r:
            r.raise_for_status()
            if 'text/html' in r.headers.get('content-type','').lower():raise ValueError('Expected CSV, received HTML')
            body=bytearray()
            for chunk in r.iter_bytes():
                body.extend(chunk)
                if len(body)>8_000_000:raise ValueError('CSV exceeds 8 MB limit')
    return bytes(body)


def parse_csv(content,season,at):
    if len(content)>8_000_000:raise ValueError('CSV exceeds 8 MB limit')
    year=season_year(season)
    try:text=content.decode('utf-8-sig')
    except UnicodeDecodeError:text=content.decode('cp1252')
    reader=csv.DictReader(io.StringIO(text))
    if not {'Date','HomeTeam','AwayTeam','FTHG','FTAG','FTR'}.issubset(reader.fieldnames or []):raise ValueError('CSV missing required match fields')
    matches=[];rejected=0;seen={}
    for row in reader:
        if not any(row.values()):continue
        try:
            home=(row['HomeTeam'] or '').strip();away=(row['AwayTeam'] or '').strip()
            if not home or not away or home.casefold()==away.casefold() or max(len(home),len(away))>200:raise ValueError('Invalid teams')
            stamp=None
            for fmt in ('%d/%m/%Y','%d/%m/%y','%Y-%m-%d'):
                try:stamp=datetime.strptime(row['Date'].strip(),fmt).replace(tzinfo=timezone.utc);break
                except ValueError:pass
            # Date-only data cannot establish that a result was known earlier that day.
            if stamp is None or stamp.year not in (year,year+1) or stamp+timedelta(days=1)>at:raise ValueError('Invalid result date')
            if not re.fullmatch(r'\d{1,2}',row['FTHG'] or '') or not re.fullmatch(r'\d{1,2}',row['FTAG'] or ''):raise ValueError('Invalid score')
            h,a=int(row['FTHG']),int(row['FTAG'])
            if row['FTR'].strip()!=('H' if h>a else 'A' if h<a else 'D'):raise ValueError('Inconsistent score/result')
            key=(stamp.isoformat(),home.casefold(),away.casefold())
            if key in seen:
                if seen[key]!=(h,a):raise ValueError('Conflicting duplicate fixture')
                continue
            seen[key]=(h,a)
            matches.append(dict(matchID=len(matches)+1,matchDateTimeUTC=stamp.isoformat(),team1={'teamName':home},team2={'teamName':away},
                matchIsFinished=True,matchResults=[dict(resultTypeKind='After90Minutes',pointsTeam1=h,pointsTeam2=a)]))
        except (ValueError,TypeError,KeyError,AttributeError):rejected+=1
    if not matches:raise ValueError('No valid completed matches')
    # Reject conflicts instead of silently accepting an arbitrary version of a score.
    if rejected:raise ValueError(f'CSV contains {rejected} invalid or conflicting rows; no partial import was committed')
    return matches,rejected


def resolve_state(db,ident):
    state=db.scalar(select(m.ProviderSyncState).where(m.ProviderSyncState.id==PREFIX+ident).with_for_update())
    if state is None:
        state=db.scalar(select(m.ProviderSyncState).where(m.ProviderSyncState.id.like(PREFIX+'%'),m.ProviderSyncState.payload['competition_id'].as_string()==ident).with_for_update())
    if state is None:raise LookupError('CSV competition not registered')
    return state


def sync(factory,ident,season=None,fetcher=download,at=None):
    at=at or datetime.now(timezone.utc)
    with factory.begin() as db:
        state=resolve_state(db,ident)
        source=db.get(m.Source,state.source_id)
        if not source.enabled or source.permission!='AUTHORIZED':raise PermissionError('Source not authorized')
        p=dict(state.payload);key=state.id;source_id=source.id
        if p.get('lease_until') and datetime.fromisoformat(p['lease_until'])>at:return {'status':'ALREADY_RUNNING'}
        code=urlparse(safe_source(p['source_url'])).path.split('/')[2]
        if season is None:
            start=2000+int(code[:2]);season=f'{start}/{start+1}'
        year=season_year(season)
        if code!=f'{year%100:02d}{(year+1)%100:02d}':raise ValueError('Season does not match registered source URL')
        state.payload={**p,'lease_until':(at+timedelta(minutes=5)).isoformat()}
        run=m.AuditEvent(actor='standings-worker',action='standings.sync',created_at=at,correlation_id=p['competition_id'],payload={'registration_id':p['registration_id'],'season':season,'status':'RUNNING','started_at':at.isoformat()})
        db.add(run);db.flush();run_id=run.id
    try:
        content=fetcher(p['source_url']);checksum=hashlib.sha256(content).hexdigest()
        matches,rejected=parse_csv(content,season,at)
        tables=build_tables(matches,at)
        points_win=p.get('points_win',3)
        for scope in ('overall','home','away'):
            rows=[r for r in tables[scope] if r['played']]
            for row in rows:row['points']=points_win*row['wins']+row['draws']
            rows.sort(key=lambda r:(-r['points'],-r['goal_difference'],-r['goals_for'],r['club']))
            for rank,row in enumerate(rows,1):row['rank']=rank
            tables[scope]=rows
        with factory.begin() as db:
            state=db.get(m.ProviderSyncState,key);source=db.get(m.Source,source_id)
            if not source.enabled or source.permission!='AUTHORIZED' or any(state.payload.get(k)!=p.get(k) for k in ('source_url','points_win','competition_id')):raise PermissionError('Source authorization or configuration changed during sync')
            comp=db.get(m.Competition,p['competition_id'])
            labels=(season,f'{year}/{str(year+1)[-2:]}')
            registered=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp.id,m.CompetitionSeason.label.in_(labels)))
            dates=[datetime.fromisoformat(r['matchDateTimeUTC']).date() for r in matches]
            if registered is None:
                registered=m.CompetitionSeason(competition_id=comp.id,label=season,start_date=min(dates),end_date=max(dates),is_current=year==(at.year if at.month>=7 else at.year-1));db.add(registered);db.flush()
            for match in matches:
                kickoff=datetime.fromisoformat(match['matchDateTimeUTC'])
                home,away=match['team1']['teamName'],match['team2']['teamName']
                fixture=db.scalar(select(m.Fixture).where(m.Fixture.competition_id==comp.id,m.Fixture.home_name==home,m.Fixture.away_name==away,m.Fixture.kickoff_at==kickoff))
                if fixture is None:
                    fixture=m.Fixture(competition_id=comp.id,season_id=registered.id,home_name=home,away_name=away,kickoff_at=kickoff,status='RESULT_REPORTED')
                    db.add(fixture)
                elif fixture.season_id is None:
                    fixture.season_id=registered.id
            digest=hashlib.sha256((key+':'+registered.id+':'+str(points_win)+':'+checksum).encode()).hexdigest()
            changed=state.last_change!=digest
            dataset={'section':'standings_dataset','adapter':ADAPTER,'competition_id':comp.id,'season_id':registered.id,'registration_id':p['registration_id'],
                     'tables':tables,'checksum':checksum,'points_win':points_win,'source_url':p['source_url'],'matches':len(matches)}
            if changed:
                capture_hash=hashlib.sha256((digest+run_id).encode()).hexdigest()
                db.add(m.Observation(source_id=source.id,content_hash=capture_hash,source_url=p['source_url'],observed_at=at,payload=dataset))
            state.last_change=digest;state.last_full_at=at;state.failures=0;state.next_check_at=at+timedelta(hours=6)
            state.payload={**state.payload,'season_id':registered.id,'lease_until':None,'last_status':'COMPLETED','checksum':checksum,'last_run_id':run_id}
            run=db.get(m.AuditEvent,run_id);run.payload={**run.payload,'status':'COMPLETED','finished_at':at.isoformat(),'valid_rows':len(matches),'rejected_rows':rejected,'checksum':checksum,'changed':changed}
            if changed:
                db.add(m.PipelineEvent(event_key='standings:'+run_id,content_hash=digest,kind='standings.updated',payload={'competition_id':comp.id,'season_id':registered.id,'invalidate_from':'research'},status='PENDING',available_at=at))
            return {'run_id':run_id,'status':'COMPLETED','valid_rows':len(matches),'rejected_rows':rejected,'checksum':checksum,'changed':changed}
    except Exception as exc:
        with factory.begin() as db:
            state=db.get(m.ProviderSyncState,key);state.failures+=1;state.next_check_at=at+timedelta(seconds=min(21600,300*2**min(state.failures,6)))
            state.payload={**state.payload,'lease_until':None,'last_status':'FAILED'}
            run=db.get(m.AuditEvent,run_id);run.payload={**run.payload,'status':'FAILED','finished_at':at.isoformat(),'error_code':type(exc).__name__}
        raise


def collect(factory,fetcher=download,at=None):
    at=at or datetime.now(timezone.utc)
    with factory() as db:
        keys=list(db.scalars(select(m.ProviderSyncState.id).join(m.Source,m.Source.id==m.ProviderSyncState.source_id).where(
            m.ProviderSyncState.id.like(PREFIX+'%'),m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')))
    results=[];errors=[]
    for key in keys:
        with factory() as db:
            state=db.get(m.ProviderSyncState,key)
            if state.next_check_at and utc(state.next_check_at)>at:continue
        try:results.append(sync(factory,key[len(PREFIX):],fetcher=fetcher,at=at))
        except Exception as exc:errors.append({'registration_id':key[len(PREFIX):],'code':type(exc).__name__})
    return {'configured_sources':len(keys),'processed':len(results),'errors':errors}


def report(db,competition_id,season_id,cutoff,scope):
    if not season_id:return None
    obs=db.scalar(select(m.Observation).join(m.Source,m.Source.id==m.Observation.source_id).where(
        m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED',m.Observation.observed_at<=cutoff,
        m.Observation.payload['adapter'].as_string()==ADAPTER,m.Observation.payload['competition_id'].as_string()==competition_id,
        m.Observation.payload['season_id'].as_string()==season_id).order_by(m.Observation.observed_at.desc(),m.Observation.id).limit(1))
    if obs is None:return None
    p=obs.payload;source=db.get(m.Source,obs.source_id);state=db.get(m.ProviderSyncState,PREFIX+p['registration_id'])
    return dict(mode='csv_computed',scope=scope,season_id=season_id,as_of=cutoff,rows=p['tables'][scope],
        warning=f"Computed/unofficial CSV table ({p['points_win']}/1/0). Deductions and competition-specific tie-breakers are excluded. Captured datasets, including corrections, are restricted to what was known by the selected cutoff.",
        source=dict(id=source.id,name=source.name,official=False,captured_at=obs.observed_at,verified_at=None,source_url=obs.source_url,source_reference=obs.id),
        community_statistics=p['tables']['_statistics'],next_check_at=state.next_check_at if state else None)
