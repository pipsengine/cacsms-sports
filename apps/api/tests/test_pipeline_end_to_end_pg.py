"""Full backend acceptance tests on disposable PostgreSQL. No operations are mocked.

Test-only inputs and approved artifacts are deliberately controlled fixtures, never production records.
Set SPORTS_TEST_DATABASE_URL to a PostgreSQL connection whose user may create a disposable database.
"""
import json,math,os,subprocess,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest
import psycopg
from psycopg import sql
from sqlalchemy import create_engine,select,func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.db import models as m
from app.modules.pipeline.logic import STAGES
from app.modules.pipeline.runner import drive_run,PAGES
from app.modules.pipeline.context import workflow_context
from app.modules.acquisition.service import ingest_observation

@pytest.fixture(scope='module')
def database():
 configured=os.getenv('SPORTS_TEST_DATABASE_URL')
 if not configured:pytest.skip('Set SPORTS_TEST_DATABASE_URL for full PostgreSQL integration tests')
 url=make_url(configured);name='cacsms_pipeline_test_'+uuid.uuid4().hex[:10]
 args=dict(host=url.host,port=url.port or 5432,user=url.username,password=url.password)
 root=Path(__file__).resolve().parents[3]
 with psycopg.connect(dbname='postgres',autocommit=True,**args) as admin:
  admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
  try:
   target=url.set(database=name).render_as_string(hide_password=False)
   env=dict(os.environ,DATABASE_URL=target,PYTHONPATH=str(root))
   result=subprocess.run([os.sys.executable,'-m','alembic','upgrade','head'],cwd=root/'apps/api',env=env,capture_output=True,text=True)
   assert result.returncode==0,result.stderr
   for operation,revision in [('downgrade','0010'),('upgrade','head')]:
    result=subprocess.run([os.sys.executable,'-m','alembic',operation,revision],cwd=root/'apps/api',env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
   engine=create_engine(target)
   yield engine
   engine.dispose()
  finally:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

@pytest.fixture
def factory(database,monkeypatch):
 monkeypatch.setenv('SPORTS_SOURCE_FEEDS_JSON','{}');monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
 monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON',json.dumps({'source-a':{'reviewed':True,'independence_group':'licensed-a'},'source-b':{'reviewed':True,'independence_group':'licensed-b'}}))
 connection=database.connect();transaction=connection.begin()
 factory=sessionmaker(bind=connection,join_transaction_mode='create_savepoint')
 yield factory
 transaction.rollback();connection.close()


def seed(factory,disagree=False,calibrated=True,at=None):
 at=at or datetime.now(timezone.utc)-timedelta(hours=4)
 with factory.begin() as db:
  db.add(m.Sport(id='sport-integration',name='Integration Football'));db.flush()
  db.add(m.Competition(id='competition-integration',sport_id='sport-integration',name='Integration Test Competition'));db.flush()
  db.add_all([m.Source(id='source-a',name='Integration Source A',permission='AUTHORIZED',enabled=True),m.Source(id='source-b',name='Integration Source B',permission='AUTHORIZED',enabled=True)])
  db.add(m.Fixture(id='fixture-integration',competition_id='competition-integration',home_name='Integration Home',away_name='Integration Away',kickoff_at=at+timedelta(hours=1)));db.flush()
  contents={'standings':{'home_rank':1,'away_rank':2},'recent_form':{'home_form':2.,'away_form':1.},'head_to_head':{'matches':3},'team_news':{'checked':True},'lineups':{'confirmed':True},'injuries':{'checked':True},'match_statistics':{'home_scoring_rate':2.,'away_scoring_rate':1.,'home_conceding_rate':1.,'away_conceding_rate':2.}}
  for source in ('source-a','source-b'):
   for section,content in contents.items():
    if disagree and source=='source-b' and section=='recent_form':content={**content,'home_form':0.}
    ingest_observation(db,source_id=source,fixture_id='fixture-integration',section=section,source_url='https://'+source+'.example/research',observed_at=at-timedelta(minutes=1),payload=content)
  prices=[dict(bookmaker='Integration Book',market_key='1X2',outcome_key=outcome,decimal_odds=price,observed_at=(at-timedelta(minutes=1)).isoformat()) for outcome,price in [('HOME',2.5),('DRAW',3.5),('AWAY',2.9)]]
  ingest_observation(db,source_id='source-a',fixture_id='fixture-integration',section='market_odds',source_url='https://source-a.example/prices',observed_at=at-timedelta(seconds=20),payload={'prices':prices})
  artifact=dict(approved=True,out_of_sample=True,calibrated=True,calibration_verified=calibrated,means=[0.]*6,scales=[1.]*6,coefficients=[0.]*6,intercept=math.log(3))
  db.add(m.ModelVersion(id='model-integration',sport_id='sport-integration',name='Controlled integration artifact',version='1',status='ACTIVE',validation=artifact))
  run=m.PipelineRun(id='run-integration',idempotency_key='integration:canonical-run',fixture_id='fixture-integration',status='PENDING',mode='PAPER',context={});db.add(run);db.flush()
  for index,(key,_,_) in enumerate(STAGES,1):db.add(m.PipelineStage(run_id=run.id,position=index,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=[]))
 return at


def test_all_twelve_actual_operations_and_final_result(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');report=drive_run(db,run,at=at)
  stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id).order_by(m.PipelineStage.position)).all()
  assert [s.status for s in stages[:11]]==['VERIFIED']*11,[(s.stage_key,s.status,s.error) for s in stages]
  assert stages[11].status=='WAITING_FOR_DATA' and run.status=='MONITORING'
  assert db.scalar(select(func.count()).select_from(m.Feature))==1
  assert db.scalar(select(func.count()).select_from(m.Prediction))==1
  assert db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED'))==1
  assert db.scalar(select(func.count()).select_from(m.Ticket))==1
  assert db.scalar(select(func.count()).select_from(m.Betslip).where(m.Betslip.status=='PAPER_VERIFIED'))==1
  assert db.scalar(select(func.count()).select_from(m.BookingCode))==0
  context=workflow_context(db,run.id,run.fixture_id)
  assert context['run']['verified_stages']==11
  for stage in context['run']['stages']:
   assert stage['href'].startswith('/sports/'+PAGES[stage['stage_key']]+'?')
   assert 'fixture_id=fixture-integration' in stage['href'] and 'run_id=run-integration' in stage['href']
  assert context['datasets']['verify'] and context['datasets']['monitor']
  # Source data commits publish actual outbox records, not direct client completion claims.
  assert db.scalar(select(func.count()).select_from(m.PipelineEvent))>0
 final_at=at+timedelta(hours=2)
 with factory.begin() as db:
  ingest_observation(db,source_id='source-a',fixture_id='fixture-integration',section='official_result',source_url='https://source-a.example/final',observed_at=final_at-timedelta(seconds=10),payload={'status':'FINAL','outcomes':{'1X2':{'HOME':'WON','DRAW':'LOST','AWAY':'LOST'}},'score':{'home':2,'away':0}})
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=final_at)
  stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id)).all()
  assert run.status=='COMPLETED' and all(s.status=='VERIFIED' for s in stages),[(s.stage_key,s.status,s.error) for s in stages]
  assert db.scalar(select(m.Settlement.outcome))=='WON'
  assert len(workflow_context(db,run.id)['datasets']['reconcile'])==2
  receipts=db.scalar(select(func.count()).select_from(m.StageRecord))
  drive_run(db,run,at=final_at)
  assert db.scalar(select(func.count()).select_from(m.Ticket))==1
  assert db.scalar(select(func.count()).select_from(m.Settlement))==1
  assert db.scalar(select(func.count()).select_from(m.StageRecord))==receipts
  assert db.scalar(select(func.count()).select_from(m.AuditEvent).where(m.AuditEvent.action=='pipeline.stage_executed'))>=12


def test_conflicting_research_cannot_advance(factory):
 at=seed(factory,disagree=True)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='research'))
  assert stage.status=='WAITING_FOR_DATA' and 'recent_form' in stage.error
  assert db.scalar(select(func.count()).select_from(m.Prediction))==0
  assert db.scalar(select(func.count()).select_from(m.Ticket))==0


def test_calibration_gate_stops_real_inference(factory):
 at=seed(factory,calibrated=False)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='predict'))
  assert stage.status=='WAITING_FOR_DATA'
  assert db.scalar(select(func.count()).select_from(m.Prediction))==0


def test_transactional_outbox_rollback_and_retry_recovery(factory,monkeypatch):
 at=seed(factory)
 with factory() as db:
  before=db.scalar(select(func.count()).select_from(m.PipelineEvent))
  obj=m.Odds(fixture_id='fixture-integration',bookmaker='Rollback Only',market_key='1X2',outcome_key='HOME',decimal_odds=2,observed_at=at)
  db.add(obj);db.flush()
  assert db.scalar(select(func.count()).select_from(m.PipelineEvent))==before+1
  db.rollback()
 with factory.begin() as db:
  assert db.scalar(select(func.count()).select_from(m.PipelineEvent))==before
  monkeypatch.setenv('SPORTS_SOURCE_FEEDS_JSON','invalid-json')
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='acquire'))
  assert stage.status=='RETRY_SCHEDULED' and stage.retry_count==1 and stage.next_retry_at is not None
  monkeypatch.setenv('SPORTS_SOURCE_FEEDS_JSON','{}')
  drive_run(db,run,at=at+timedelta(seconds=31))
  assert stage.status=='VERIFIED'


def test_betslip_tampering_and_continuous_monitor(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  slip=db.scalar(select(m.Betslip));slip.combined_odds=99
  drive_run(db,run,at=at+timedelta(seconds=10),recovery=True)
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='verify'))
  assert stage.status=='BLOCKED' and 'odds' in stage.error
  assert run.status!='COMPLETED'


def test_committed_model_change_wakes_autonomous_controller(factory):
 from app.modules.autonomy.service import cycle
 at=seed(factory,calibrated=False,at=datetime.now(timezone.utc))
 first=cycle(factory)
 assert first['created_runs']==0 and first['processed_runs']==1
 with factory.begin() as db:
  assert db.scalar(select(func.count()).select_from(m.Prediction))==0
  model=db.get(m.ModelVersion,'model-integration');model.validation={**model.validation,'calibration_verified':True}
 second=cycle(factory)
 assert second['status']!='NOT_DUE_OR_ALREADY_RUNNING' if 'status' in second else True
 with factory() as db:
  assert db.scalar(select(func.count()).select_from(m.Prediction))==1
  assert db.scalar(select(func.count()).select_from(m.PipelineRun))==1
  assert db.get(m.PipelineRun,'run-integration').status=='MONITORING'


def test_monitor_suspends_paper_ticket_when_source_is_revoked(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  db.get(m.Source,'source-a').enabled=False
  drive_run(db,run,at=at+timedelta(seconds=10),recovery=True)
  assert db.scalar(select(m.Betslip.status))=='PAPER_SUSPENDED'
  monitor=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='monitor'))
  assert monitor.status=='BLOCKED'
  assert db.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status=='OPEN'))==1


def test_stale_market_quotes_cannot_create_qualified_tickets(factory):
 at=seed(factory)
 with factory.begin() as db:
  observation=db.scalar(select(m.Observation).where(m.Observation.payload['section'].as_string()=='market_odds'))
  content=dict(observation.payload);content['data']={'prices':[dict(row,observed_at=(at-timedelta(hours=1)).isoformat()) for row in content['data']['prices']]};observation.payload=content
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='evaluate'))
  assert stage.status=='WAITING_FOR_DATA'
  assert db.scalar(select(func.count()).select_from(m.Ticket))==0


def test_monitor_continues_and_suspends_expired_paper_quotes(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  before=db.scalar(select(func.count()).select_from(m.StageRecord).where(m.StageRecord.stage_key=='monitor'))
  drive_run(db,run,at=at+timedelta(minutes=20))
  assert db.scalar(select(func.count()).select_from(m.StageRecord).where(m.StageRecord.stage_key=='monitor'))>before
  assert db.scalar(select(m.Betslip.status))=='PAPER_SUSPENDED'
  assert run.status=='BLOCKED'


def test_verified_result_correction_keeps_settlement_history(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
 for index,outcome in enumerate(('WON','LOST'),1):
  final_at=at+timedelta(hours=2,seconds=index*30)
  with factory.begin() as db:
   ingest_observation(db,source_id='source-a',fixture_id='fixture-integration',section='official_result',source_url='https://source-a.example/final',observed_at=final_at-timedelta(seconds=1),payload={'status':'FINAL','outcomes':{'1X2':{'HOME':outcome}}})
   run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=final_at,recovery=True)
   assert run.status=='COMPLETED'
 with factory() as db:
  assert db.scalar(select(func.count()).select_from(m.Result))==2
  assert db.scalar(select(func.count()).select_from(m.Settlement))==2
  assert db.scalar(select(m.Settlement.outcome).join(m.Result,m.Result.id==m.Settlement.result_id).order_by(m.Result.version.desc()).limit(1))=='LOST'


def test_shared_programme_pool_builds_real_risk_bounded_accumulator(factory):
 at=seed(factory)
 with factory.begin() as db:
  run=db.get(m.PipelineRun,'run-integration');drive_run(db,run,at=at)
  original=db.get(m.Fixture,'fixture-integration')
  db.add(m.Fixture(id='fixture-second',competition_id=original.competition_id,home_name='Second Home',away_name='Second Away',kickoff_at=original.kickoff_at));db.flush()
  originals=db.scalars(select(m.Observation).where(m.Observation.fixture_id==original.id)).all()
  for obs in originals:
   ingest_observation(db,source_id=obs.source_id,fixture_id='fixture-second',section=obs.payload['section'],source_url=obs.source_url,observed_at=obs.observed_at,payload=obs.payload['data'])
  second=m.PipelineRun(id='run-second',idempotency_key='integration:second',fixture_id='fixture-second',mode='PAPER',status='PENDING',context={});db.add(second);db.flush()
  for index,(key,_,_) in enumerate(STAGES,1):db.add(m.PipelineStage(run_id=second.id,position=index,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=[]))
  drive_run(db,second,at=at)
  assert second.status=='MONITORING'
  programme=db.scalar(select(m.Programme).where(m.Programme.key=='accumulator'))
  ticket=db.scalar(select(m.Ticket).where(m.Ticket.programme_id==programme.id))
  assert ticket is not None
  assert db.scalar(select(func.count()).select_from(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket.id))==2
  allocated=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==second.id,m.StageRecord.kind=='PROGRAMMES_ALLOCATED'))
  assert any(p['correlation_status']=='BOUNDED_WITHOUT_INDEPENDENCE' for p in allocated.details['proposals'])
  count=db.scalar(select(func.count()).select_from(m.Ticket))
  drive_run(db,second,at=at,recovery=True)
  assert db.scalar(select(func.count()).select_from(m.Ticket))==count
