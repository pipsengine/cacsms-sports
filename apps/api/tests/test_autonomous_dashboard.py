import json
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.autonomy import service,discovery
from app.modules.autonomy.overview import snapshot

@pytest.fixture
def factory():
 engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
 Base.metadata.create_all(engine)
 factory=sessionmaker(bind=engine)
 yield factory
 engine.dispose()


def seed(factory,at):
 with factory.begin() as db:
  db.add(m.Sport(id='sport',name='Football'));db.flush()
  db.add(m.Competition(id='league',sport_id='sport',name='League',country='England'));db.flush()
  db.add(m.Source(id='source',name='Licensed source',enabled=True,permission='AUTHORIZED'))
  db.add(m.Fixture(id='fixture',competition_id='league',home_name='Home',away_name='Away',kickoff_at=at+timedelta(hours=2)));db.flush()
  db.add(m.Observation(source_id='source',fixture_id='fixture',source_url='https://licensed.example/fixture',content_hash='s'*64,observed_at=at-timedelta(seconds=1),payload={'source_reference':'seed-fixture'}))


def test_runtime_lease_recovery_and_stale_heartbeat(factory):
 at=datetime.now(timezone.utc)
 first=service.claim(factory,at)
 assert first and service.claim(factory,at+timedelta(seconds=31)) is None
 second=service.claim(factory,at+timedelta(seconds=301))
 assert second and second!=first
 assert not service.finish(factory,first,{},at=at+timedelta(seconds=302))
 assert service.finish(factory,second,{'blockers':[],'errors':[]},at=at+timedelta(seconds=302))
 with factory() as db:
  assert service.runtime_status(db,at+timedelta(seconds=303))['worker_online']
  assert service.runtime_status(db,at+timedelta(seconds=600))['status']=='OFFLINE'


def test_empty_cycle_is_automatic_and_truthful(factory,monkeypatch):
 monkeypatch.delenv('SPORTS_DISCOVERY_FEEDS_JSON',raising=False)
 report=service.cycle(factory)
 assert report['created_runs']==0 and len(report['blockers'])==3
 assert service.cycle(factory)['status']=='NOT_DUE_OR_ALREADY_RUNNING'
 with factory() as db:
  state=service.runtime_status(db)
  assert state['status']=='WAITING_FOR_DATA' and state['worker_online'] and state['cycles']==1
  view=snapshot(db)
  assert view['latest_run'] is None
  assert view['summary']['fixtures']==0
  assert view['registered_models']==0


def test_runs_are_created_once_and_advance_without_browser(factory,monkeypatch):
 at=datetime.now(timezone.utc);seed(factory,at)
 monkeypatch.setattr(service,'now',lambda:at)
 monkeypatch.delenv('SPORTS_DISCOVERY_FEEDS_JSON',raising=False)
 report=service.cycle(factory)
 assert report['created_runs']==1 and report['processed_runs']==1,report
 assert not report['errors']
 with factory() as db:
  run=db.scalar(select(m.PipelineRun))
  stages=db.scalars(select(m.PipelineStage).order_by(m.PipelineStage.position)).all()
  assert len(stages)==12 and stages[0].status=='VERIFIED' and stages[1].status=='VERIFIED' and stages[2].status=='WAITING_FOR_DATA'
  assert run.mode=='PAPER' and run.status=='WAITING_FOR_DATA'
  assert db.get(m.Fixture,'fixture').sport_id=='sport'
 monkeypatch.setattr(service,'now',lambda:at+timedelta(seconds=31))
 second=service.cycle(factory)
 assert second['created_runs']==0 and second['processed_runs']==1
 with factory() as db:assert db.scalar(select(func.count()).select_from(m.PipelineRun))==1


def test_discovery_authorization_validation_and_idempotency(factory,monkeypatch):
 at=datetime.now(timezone.utc);seed(factory,at)
 monkeypatch.setenv('SPORTS_DISCOVERY_FEEDS_JSON',json.dumps({'source':'https://licensed.example/fixtures'}))
 payload={'fixtures':[dict(sport_name='Football',competition_name='League',home='New home',away='New away',kickoff_at=(at+timedelta(days=1)).isoformat(),source_url='https://licensed.example/evidence',source_reference='fixture-123')]}
 assert discovery.collect(factory,lambda url:payload)['fixtures']==1
 assert discovery.collect(factory,lambda url:payload)['fixtures']==1
 with factory() as db:
  assert db.scalar(select(func.count()).select_from(m.Fixture))==2
  assert db.scalar(select(func.count()).select_from(m.Observation))==2
 with factory.begin() as db:db.get(m.Source,'source').enabled=False
 def forbidden(url):raise AssertionError('Unauthorized source must not be fetched')
 result=discovery.collect(factory,forbidden)
 assert result['errors'][0]['code']=='SOURCE_NOT_AUTHORIZED'


def test_period_filters_and_canonical_dashboard_fields(factory):
 at=datetime.now(timezone.utc);seed(factory,at)
 with factory.begin() as db:
  db.add(m.Fixture(id='later',competition_id='league',home_name='Later home',away_name='Later away',kickoff_at=at+timedelta(hours=40)))
  db.add(m.Research(fixture_id='fixture',version=1,status='PARTIAL',sections={},evidence_ids=[],created_at=at-timedelta(hours=40)))
 with factory() as db:
  narrow=snapshot(db,24,at);wide=snapshot(db,72,at)
  assert narrow['summary']['fixtures']==1 and wide['summary']['fixtures']==2
  assert narrow['summary']['research_dossiers']==0 and wide['summary']['research_dossiers']==1
  assert narrow['fixtures'][0]['name']=='Home vs Away'
  assert narrow['fixtures'][0]['sport']=='Football'
  assert next(p for p in narrow['programmes'] if p['key']=='rollover')['daily_limit']==1


def test_open_data_cache_permission_and_no_verification(factory,monkeypatch):
 from app.modules.autonomy import openligadb
 at=datetime.now(timezone.utc)
 monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
 calls=[]
 def fetch(url):
  calls.append(url)
  if 'getlastchangedate' in url:return '2026-11-15T12:00:00Z'
  return [dict(matchID=123,matchDateTimeUTC=(at+timedelta(days=2)).isoformat(),team1={'teamName':'Home'},team2={'teamName':'Away'},group={'groupOrderID':1},matchIsFinished=False)]
 report=openligadb.collect(factory,fetch,at)
 assert report['status']=='SYNCED' and report['fixtures']==1
 assert len(calls)==2
 assert openligadb.collect(factory,fetch,at+timedelta(seconds=30))['status']=='CACHED'
 assert len(calls)==2
 with factory() as db:
  fixture=db.scalar(select(m.Fixture))
  assert fixture.season_id is not None
  assert db.scalar(select(func.count()).select_from(m.Result))==0
  assert db.scalar(select(func.count()).select_from(m.Prediction))==0
  assert db.scalar(select(func.count()).select_from(m.Research))==0
 with factory.begin() as db:db.get(m.Source,openligadb.SOURCE_ID).enabled=False
 assert openligadb.collect(factory,fetch,at+timedelta(days=1))['status']=='SOURCE_DISABLED'
 assert len(calls)==2


def test_open_data_failure_backoff_preserves_controller(factory,monkeypatch):
 from app.modules.autonomy import openligadb
 monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
 def broken(url):raise TimeoutError('secret provider body must not be copied')
 report=openligadb.collect(factory,broken)
 assert report['status']=='RETRY_SCHEDULED'
 assert 'secret' not in json.dumps(report)
 with factory() as db:
  cached=db.scalar(select(m.ProviderSyncState))
  assert cached.failures==1 and cached.next_check_at is not None


def test_event_fanout_exceeds_one_batch_without_losing_work(factory,monkeypatch):
 at=datetime.now(timezone.utc);seed(factory,at)
 monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
 monkeypatch.setenv('SPORTS_DISCOVERY_FEEDS_JSON','{}')
 with factory.begin() as db:
  for i in range(39):db.add(m.Fixture(id='batch-'+str(i),competition_id='league',home_name='Batch home '+str(i),away_name='Batch away '+str(i),kickoff_at=at+timedelta(hours=1)))
 first=service.cycle(factory)
 monkeypatch.setattr(service,'now',lambda:at+timedelta(seconds=10))
 second=service.cycle(factory)
 assert first['processed_runs']==25
 assert second['processed_runs']==25
 with factory() as db:
  assert db.scalar(select(func.count()).select_from(m.PipelineRun))==40
  assert db.scalar(select(func.count()).select_from(m.PipelineEvent).where(m.PipelineEvent.status=='PENDING'))==0


def test_revoked_acquisition_source_is_not_fetched(factory,monkeypatch):
 from app.modules.acquisition import jobs
 at=datetime.now(timezone.utc);seed(factory,at)
 with factory.begin() as db:
  db.get(m.Source,'source').enabled=False
  db.add(m.AcquisitionJob(id='revoked-job',source_id='source',fixture_id='fixture',section='recent_form',idempotency_key='revoked-key',status='PENDING',next_run_at=at-timedelta(seconds=1)))
 monkeypatch.setattr(jobs,'SessionLocal',factory)
 def forbidden(url):raise AssertionError('Revoked source must not receive a request')
 result=jobs.run_job('revoked-job',fetcher=forbidden)
 assert result['status']=='REJECTED' and result['error_code']=='SOURCE_REVOKED'


def test_autonomous_community_tables_scopes_and_revocation(factory,monkeypatch):
 from app.modules.autonomy import openligadb
 from app.modules.research import catalog
 at=datetime.now(timezone.utc)-timedelta(seconds=10)
 monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
 def fetch(url):
  if 'getlastchangedate' in url:return 'changed'
  return [dict(matchID=401,matchDateTimeUTC=(at-timedelta(days=1)).isoformat(),team1={'teamName':'Home'},team2={'teamName':'Away'},
               group={'groupOrderID':1},matchIsFinished=True,matchResults=[
                {'resultTypeKind':'HalfTime','pointsTeam1':9,'pointsTeam2':0},
                {'resultTypeKind':'After90Minutes','pointsTeam1':2,'pointsTeam2':1}])]
 report=openligadb.collect(factory,fetch,at)
 assert report['status']=='SYNCED',report
 with factory() as db:
  fixture=db.scalar(select(m.Fixture))
  overall=catalog.standings(db,fixture.competition_id,fixture.season_id,at+timedelta(seconds=1))
  assert overall['mode']=='community_computed'
  assert overall['source']['verified_at'] is None and overall['source']['official'] is False
  assert overall['rows'][0]['club']=='Home' and overall['rows'][0]['goals_for']==2
  assert overall['community_statistics']['matches']==1 and overall['community_statistics']['home_wins']==1
  assert overall['community_statistics']['goals_trend'][0]['value']==3
  home=catalog.standings(db,fixture.competition_id,fixture.season_id,at+timedelta(seconds=1),'home')
  away=catalog.standings(db,fixture.competition_id,fixture.season_id,at+timedelta(seconds=1),'away')
  assert next(r for r in home['rows'] if r['club']=='Away')['played']==0
  assert next(r for r in away['rows'] if r['club']=='Away')['played']==1
  assert next(r for r in overall['rows'] if r['club']=='Home')['form']==['W']
  assert catalog.standings(db,fixture.competition_id,fixture.season_id,at-timedelta(hours=1))['rows']==[]
  for model in (m.Result,m.StandingsSnapshot,m.Prediction,m.Research):
   assert db.scalar(select(func.count()).select_from(model))==0
  league_id,season_id=fixture.competition_id,fixture.season_id
 with factory.begin() as db:db.get(m.Source,openligadb.SOURCE_ID).enabled=False
 with factory() as db:assert catalog.standings(db,league_id,season_id,at+timedelta(seconds=2))['rows']==[]


def test_community_scores_never_guess_final_or_accept_future():
 from app.modules.autonomy.community_tables import build_tables
 at=datetime.now(timezone.utc)
 match=dict(matchID=1,matchDateTimeUTC=(at-timedelta(days=1)).isoformat(),team1={'teamName':'Home'},team2={'teamName':'Away'},matchIsFinished=True,
            matchResults=[dict(resultTypeKind='HalfTime',pointsTeam1=3,pointsTeam2=0)])
 for values in [match,{**match,'matchIsFinished':False},
                {**match,'matchDateTimeUTC':(at+timedelta(days=1)).isoformat(),'matchResults':[dict(resultTypeKind='After90Minutes',pointsTeam1=3,pointsTeam2=0)]},
                {**match,'matchResults':[dict(resultTypeKind='After90Minutes',pointsTeam1=True,pointsTeam2=0)]}]:
  assert all(row['played']==0 for row in build_tables([values],at)['overall'])
