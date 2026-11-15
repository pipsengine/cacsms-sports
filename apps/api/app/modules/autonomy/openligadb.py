"""Opt-in, cached OpenLigaDB fixture discovery under its published ODbL data licence.

Community data is never labelled independently verified research or an official result.
No images, logos, betting odds or personal information are fetched or embedded.
"""
import os,random,hashlib,json
from datetime import datetime,timedelta,timezone
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from app.db import models as m
from app.modules.ingestion.service import ingest_fixture
from app.modules.acquisition.jobs import validate_feed_url
from app.modules.research.league import utc

BASE='https://api.openligadb.de'
SOURCE='OpenLigaDB (ODbL 1.0)'
SOURCE_ID=str(uuid5(NAMESPACE_URL,'https://www.openligadb.de/'))
LICENCE='https://www.openligadb.de/en/license'
ATTRIBUTION='Data from OpenLigaDB (www.openligadb.de), licensed under ODbL 1.0'


def enabled():return os.getenv('SPORTS_OPENLIGADB_ENABLED','0').lower() in ('1','true','yes')


def fetch(url):
 import httpx
 validate_feed_url(url)
 with httpx.Client(timeout=15,follow_redirects=False,trust_env=False,headers={'Accept':'application/json','User-Agent':os.getenv('SPORTS_OPENLIGADB_USER_AGENT','CACSMS-Sports/1.0 (local autonomous research dashboard)')}) as client:
  with client.stream('GET',url) as response:
   response.raise_for_status();body=bytearray()
   for chunk in response.iter_bytes():
    body.extend(chunk)
    if len(body)>2_000_000:raise ValueError('Provider response too large')
 return json.loads(body)


def normalize(matches,at):
 if not isinstance(matches,list) or len(matches)>500:raise ValueError('Unexpected provider fixture envelope')
 rows=[];timings=[]
 for match in matches:
  stamp=datetime.fromisoformat(match['matchDateTimeUTC'].replace('Z','+00:00'))
  if stamp.tzinfo is None:raise ValueError('Provider UTC kickoff missing timezone')
  home=match['team1']['teamName'];away=match['team2']['teamName']
  if not isinstance(home,str) or not isinstance(away,str) or not home.strip() or not away.strip() or home.casefold()==away.casefold():raise ValueError('Invalid provider team identity')
  ident=match['matchID']
  if type(ident) is not int or ident<=0:raise ValueError('Invalid provider match ID')
  # A stable league label avoids embedding changing season strings in competition identity.
  rows.append(dict(home=home,away=away,kickoff=stamp.isoformat(),source_reference='OpenLigaDB:match:'+str(ident),url=BASE+'/getmatchdata/'+str(ident)))
  group=match.get('group',{}).get('groupOrderID')
  if type(group) is int:timings.append((stamp,group,match.get('matchIsFinished') is True))
 nearest=min(timings,key=lambda item:abs((item[0]-at).total_seconds())) if timings else None
 live=any(stamp-timedelta(minutes=15)<=at<=stamp+timedelta(hours=3) and not finished for stamp,_,finished in timings)
 return rows,nearest[1] if nearest else None,live


def collect(factory,fetcher=fetch,at=None):
 at=at or datetime.now(timezone.utc)
 if not enabled():return {'enabled':False,'status':'DISABLED','errors':[]}
 # Bootstrap is opt-in through the local environment. Never re-enable a source revoked by an operator.
 with factory.begin() as db:
  source=db.get(m.Source,SOURCE_ID)
  if source is None:
   source=m.Source(id=SOURCE_ID,name=SOURCE,permission='AUTHORIZED',enabled=True);db.add(source);db.flush()
   db.add(m.AuditEvent(actor='autonomous-source-setup',action='source.open_data_enabled',correlation_id=source.id,
      payload={'provider':'OpenLigaDB','licence_url':LICENCE,'terms_url':'https://www.openligadb.de/en/terms-of-use','permission_basis':'ODbL 1.0 public licence','attribution':ATTRIBUTION}))
  if not source.enabled or source.permission!='AUTHORIZED':return {'enabled':True,'status':'SOURCE_DISABLED','errors':[]}
  season=at.year if at.month>=7 else at.year-1
  key='openligadb:bl1:'+str(season)
  cache=db.get(m.ProviderSyncState,key)
  if cache is None:
   cache=m.ProviderSyncState(id=key,source_id=source.id,payload={},failures=0);db.add(cache);db.flush()
  if cache.next_check_at and utc(cache.next_check_at)>at:
   return {'enabled':True,'status':'CACHED','fixtures':cache.payload.get('fixtures',0),'next_check_at':cache.next_check_at.isoformat(),'errors':[]}
  group=cache.payload.get('group');last_change=cache.last_change;last_full=cache.last_full_at
 try:
  marker=fetcher(BASE+'/getlastchangedate/bl1/'+str(season)+'/'+str(group)) if group else None
  if marker is not None and not isinstance(marker,str):raise ValueError('Invalid change timestamp')
  changed=marker is None or marker!=last_change or not last_full or at-utc(last_full)>=timedelta(days=1)
  if changed:
   matches=fetcher(BASE+'/getmatchdata/bl1/'+str(season))
   rows,group,live=normalize(matches,at)
   if not rows:raise ValueError('Provider returned no fixtures for the current season')
   dates=[datetime.fromisoformat(row['kickoff']).date() for row in rows]
   coverage_start,coverage_end=min(dates),max(dates)
   season_label=str(season)+'/'+str(season+1)[-2:]
   for item in rows:
    with factory.begin() as db:
     source=db.get(m.Source,SOURCE_ID)
     if not source or not source.enabled or source.permission!='AUTHORIZED':raise PermissionError('Source permission revoked')
     prior=db.scalar(select(m.Observation).where(m.Observation.source_id==source.id,m.Observation.payload['source_reference'].as_string()==item['source_reference']).order_by(m.Observation.observed_at.desc()).limit(1))
     if prior:
      fixture=db.get(m.Fixture,prior.fixture_id)
      if fixture and fixture.home_name==item['home'] and fixture.away_name==item['away']:
       fixture.kickoff_at=datetime.fromisoformat(item['kickoff'])
     result=ingest_fixture(db,source.name,'Football','Bundesliga',item['home'],item['away'],datetime.fromisoformat(item['kickoff']),item['url'],
       {'source_reference':item['source_reference'],'licence':'ODbL 1.0','licence_url':LICENCE,'attribution':ATTRIBUTION,'verification':'COMMUNITY_SOURCE_NOT_INDEPENDENTLY_VERIFIED'})
     fixture=db.get(m.Fixture,result['fixture_id']);competition=db.get(m.Competition,fixture.competition_id);competition.country='Germany'
     registered=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==competition.id,m.CompetitionSeason.label==season_label))
     if registered is None:
      registered=m.CompetitionSeason(competition_id=competition.id,label=season_label,start_date=coverage_start,end_date=coverage_end,is_current=True);db.add(registered);db.flush()
     if registered.start_date<=datetime.fromisoformat(item['kickoff']).date()<=registered.end_date:
      fixture.season_id=registered.id
   if group:marker=fetcher(BASE+'/getlastchangedate/bl1/'+str(season)+'/'+str(group))
  else:
   rows=None;live=False
  with factory.begin() as db:
   cache=db.get(m.ProviderSyncState,key)
   cache.last_change=marker;cache.failures=0
   # Outside live windows, a few centralized checks per day; full data only on change or daily refresh.
   seconds=75 if live else 6*60*60
   cache.next_check_at=at+timedelta(seconds=seconds+random.randint(5,45))
   if changed:cache.last_full_at=at;cache.payload={'group':group,'fixtures':len(rows),'attribution':ATTRIBUTION,'licence_url':LICENCE}
   return {'enabled':True,'status':'SYNCED' if changed else 'UNCHANGED','fixtures':cache.payload.get('fixtures',0),'next_check_at':cache.next_check_at.isoformat(),'errors':[]}
 except Exception as exc:
  with factory.begin() as db:
   cache=db.get(m.ProviderSyncState,key);cache.failures+=1
   cache.next_check_at=at+timedelta(seconds=min(21600,300*2**min(cache.failures,6))+random.randint(5,45))
  return {'enabled':True,'status':'RETRY_SCHEDULED','errors':[{'provider':'OpenLigaDB','code':type(exc).__name__}]}
