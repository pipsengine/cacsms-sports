from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select,func,text
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import EXECUTION_MODE
from app.db.base import SessionLocal
from app.db import models as m
app=FastAPI(title='CACSMS Sport AI 2.0',version='2.0.0',description='PAPER-only evidence-first sports intelligence API')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_credentials=False,allow_methods=['GET'],allow_headers=['*'])
PREFIX='/api/v1/sports'
TABLES={'fixtures':m.Fixture,'features':m.Feature,'research':m.Research,'predictions':m.Prediction,'markets/odds':m.Odds,'qualification/decisions':m.Qualification,'opportunities':m.Qualification,'tickets':m.Ticket,'betslips':m.Betslip,'booking-codes':m.BookingCode,'results':m.Result,'settlements':m.Settlement,'models':m.ModelVersion,'sources':m.Source,'browser/sessions':None,'missions':m.Mission,'incidents':m.Incident,'audit/events':m.AuditEvent,'statistics':None,'operations/live':m.StageRecord}
def rows_for(key):
 model=TABLES[key]
 if model is None:return []
 with SessionLocal() as s:
  q=select(model)
  if key=='opportunities':q=q.where(m.Qualification.decision=='QUALIFIED')
  if key=='operations/live':q=q.where(m.StageRecord.kind=='CONTINUOUS_PAPER_MONITOR').order_by(m.StageRecord.created_at.desc())
  if key=='incidents':q=q.where(m.Incident.status=='OPEN')
  return [{c.name:getattr(obj,c.name) for c in obj.__table__.columns} for obj in s.scalars(q.limit(100)).all()]
@app.get('/health')
def health():
 try:
  with SessionLocal() as s:s.execute(text('SELECT 1'))
  return {'api':'CONNECTED','database':'CONNECTED','mode':EXECUTION_MODE}
 except SQLAlchemyError:return {'api':'CONNECTED','database':'UNAVAILABLE','mode':EXECUTION_MODE}
@app.get(PREFIX+'/dashboard/summary')
def summary():
 with SessionLocal() as s:
  try:
   def count(model,where=None):
    q=select(func.count()).select_from(model)
    if where is not None:q=q.where(where)
    return s.scalar(q) or 0
   return {'api':'CONNECTED','database':'CONNECTED','mode':EXECUTION_MODE,'fixtures':count(m.Fixture),'research_dossiers':count(m.Research),'predictions':count(m.Prediction),'qualified':count(m.Qualification,m.Qualification.decision=='QUALIFIED'),'booking_codes':count(m.BookingCode),'incidents':count(m.Incident,m.Incident.status=='OPEN'),'updated_at':datetime.now(timezone.utc).isoformat()}
  except SQLAlchemyError as exc:raise HTTPException(status_code=503,detail='PostgreSQL unavailable or migrations not applied') from exc
@app.get(PREFIX+'/programmes')
def programmes():
 from app.modules.strategies.optimizer import PROGRAMMES
 return [{'key':key,'mode':'PAPER','status':'READY_FOR_QUALIFIED_DATA','configuration':{k:str(v) for k,v in config.items()}} for key,config in PROGRAMMES.items()]
@app.get(PREFIX+'/programmes/{key}/runs')
def programme_runs(key:str):
 if key not in ('accumulator','singles','jackpot','draws','rollover'):raise HTTPException(404,'Unknown programme')
 with SessionLocal() as db:
  return [{'id':r.id,'programme_key':r.programme_key,'status':r.status,'created_at':r.created_at,'result':r.result} for r in db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key).order_by(m.StrategyRun.created_at.desc()).limit(100)).all()]
@app.get(PREFIX+'/fixtures/{id}')
def fixture_detail(id:str):
 with SessionLocal() as s:
  obj=s.get(m.Fixture,id)
  if obj is None:raise HTTPException(404,'Fixture not found')
  return {c.name:getattr(obj,c.name) for c in obj.__table__.columns}
@app.get(PREFIX+'/fixtures/{id}/research')
def fixture_research(id:str):
 with SessionLocal() as s:
  return [{c.name:getattr(o,c.name) for c in o.__table__.columns} for o in s.scalars(select(m.Research).where(m.Research.fixture_id==id)).all()]
@app.get(PREFIX+'/fixtures/{id}/predictions')
def fixture_predictions(id:str):
 with SessionLocal() as s:
  return [{c.name:getattr(o,c.name) for c in o.__table__.columns} for o in s.scalars(select(m.Prediction).where(m.Prediction.fixture_id==id)).all()]
@app.get(PREFIX+'/fixtures/{id}/markets')
def fixture_markets(id:str):
 with SessionLocal() as s:
  return [{c.name:getattr(o,c.name) for c in o.__table__.columns} for o in s.scalars(select(m.Odds).where(m.Odds.fixture_id==id)).all()]
@app.get(PREFIX+'/fixtures/{id}/statistics')
def fixture_statistics(id:str):return []
@app.get(PREFIX+'/predictions/{id}')
def prediction_detail(id:str):
 with SessionLocal() as s:
  o=s.get(m.Prediction,id)
  if o is None:raise HTTPException(404,'Prediction not found')
  return {c.name:getattr(o,c.name) for c in o.__table__.columns}
@app.get(PREFIX+'/research/evidence/{id}')
def research_evidence(id:str):
 with SessionLocal() as s:
  o=s.get(m.Observation,id)
  if o is None:raise HTTPException(404,'Evidence not found')
  return {c.name:getattr(o,c.name) for c in o.__table__.columns}
@app.get(PREFIX+'/tickets/{id}')
def ticket_detail(id:str):
 with SessionLocal() as s:
  o=s.get(m.Ticket,id)
  if o is None:raise HTTPException(404,'Ticket not found')
  return {c.name:getattr(o,c.name) for c in o.__table__.columns}
@app.get(PREFIX+'/booking-codes/{id}')
def code_detail(id:str):
 with SessionLocal() as s:
  o=s.get(m.BookingCode,id)
  if o is None:raise HTTPException(404,'Code not found')
  return {c.name:getattr(o,c.name) for c in o.__table__.columns}
@app.get(PREFIX+'/models/{id}/evaluations')
def model_evaluations(id:str):return []
@app.get(PREFIX+'/sources/overview')
def source_overview():
 from app.modules.acquisition import source_intelligence as si
 with SessionLocal() as s:return si.overview(s)
@app.get(PREFIX+'/sources/analytics')
def source_analytics():
 from app.modules.acquisition import source_intelligence as si
 with SessionLocal() as s:return si.analytics(s)
@app.get(PREFIX+'/sources/health')
def source_health():
 from app.modules.acquisition import source_intelligence as si
 with SessionLocal() as s:return si.health(s)
@app.get(PREFIX+'/sources/registry')
def source_registry():
 from app.modules.acquisition.source_policy import registry
 with SessionLocal() as s:return registry(s)
@app.get(PREFIX+'/missions/{id}')
def mission_detail(id:str):
 with SessionLocal() as s:
  o=s.get(m.Mission,id)
  if o is None:raise HTTPException(404,'Mission not found')
  return {c.name:getattr(o,c.name) for c in o.__table__.columns}
@app.get(PREFIX+'/operations/events')
def operation_events():return rows_for('audit/events')
@app.get(PREFIX+'/diagnostics')
def diagnostics():return {'mode':EXECUTION_MODE,'incidents':rows_for('incidents'),'source_health':rows_for('sources')}


# Restricted source onboarding and provenance-based fixture ingestion.
# These endpoints are disabled unless a deployment administrator configures a secret.
import os,secrets
from fastapi import Header
from pydantic import BaseModel,Field
from app.modules.ingestion.service import ingest_fixture
from app.modules.qualification.service import evaluate
class SourceOnboard(BaseModel):
 name:str=Field(min_length=2,max_length=120)
 permission:str
 enabled:bool=False
class FixtureIntake(BaseModel):
 source_name:str
 sport_name:str
 competition_name:str
 home:str
 away:str
 kickoff_at:datetime
 source_url:str
 evidence:dict

def admin_guard(x_admin_token:str|None):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not x_admin_token or not secrets.compare_digest(expected,x_admin_token):
  raise HTTPException(403,'Administrative access disabled or invalid')

@app.post(PREFIX+'/admin/sources',status_code=201)
def onboard_source(item:SourceOnboard,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 if item.permission not in ('AUTHORIZED','UNVERIFIED','RESTRICTED'):
  raise HTTPException(422,'Invalid permission')
 if item.enabled and item.permission!='AUTHORIZED':raise HTTPException(422,'Only authorized sources may be enabled')
 with SessionLocal.begin() as s:
  source=s.scalar(select(m.Source).where(m.Source.name==item.name))
  if source is None:source=m.Source(name=item.name);s.add(source)
  source.permission=item.permission;source.enabled=item.enabled
  s.flush();return {'id':source.id,'name':source.name,'permission':source.permission,'enabled':source.enabled}

@app.post(PREFIX+'/admin/fixtures/ingest',status_code=201)
def fixture_ingest(item:FixtureIntake,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 try:
  with SessionLocal.begin() as s:
   return ingest_fixture(s,item.source_name,item.sport_name,item.competition_name,item.home,item.away,item.kickoff_at,item.source_url,item.evidence)
 except (ValueError,PermissionError) as e:raise HTTPException(422,str(e)) from e

@app.get(PREFIX+'/workflow/stages')
def workflow_stages():
 names=['Mission Planning','Fixture Discovery','Source Acquisition','Deep Match Research','Data Validation','Statistical Analysis','AI Prediction','Probability Validation','Market Intelligence','Opportunity Qualification','Strategy Allocation','Ticket Optimization','Betslip Preparation','Booking-Code Verification','Continuous Monitoring','Result Reconciliation','Model Evaluation & Learning']
 return [{'stage':i+1,'name':name,'state':'NOT_VERIFIED','mode':'PAPER'} for i,name in enumerate(names)]

@app.post(PREFIX+'/qualification/evaluate')
def qualification_preview(gates:dict):
 # Stateless preview; does not create a qualified opportunity or ticket.
 return evaluate(gates)


# Restricted source onboarding and provenance-based fixture ingestion.
# These endpoints are disabled unless a deployment administrator configures a secret.
import os,secrets
from fastapi import Header
from pydantic import BaseModel,Field
from app.modules.ingestion.service import ingest_fixture
from app.modules.qualification.service import evaluate
class SourceOnboard(BaseModel):
 name:str=Field(min_length=2,max_length=120)
 permission:str
 enabled:bool=False
class FixtureIntake(BaseModel):
 source_name:str
 sport_name:str
 competition_name:str
 home:str
 away:str
 kickoff_at:datetime
 source_url:str
 evidence:dict

def admin_guard(x_admin_token:str|None):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not x_admin_token or not secrets.compare_digest(expected,x_admin_token):
  raise HTTPException(403,'Administrative access disabled or invalid')

@app.post(PREFIX+'/admin/sources',status_code=201)
def onboard_source(item:SourceOnboard,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 if item.permission not in ('AUTHORIZED','UNVERIFIED','RESTRICTED'):
  raise HTTPException(422,'Invalid permission')
 if item.enabled and item.permission!='AUTHORIZED':raise HTTPException(422,'Only authorized sources may be enabled')
 with SessionLocal.begin() as s:
  source=s.scalar(select(m.Source).where(m.Source.name==item.name))
  if source is None:source=m.Source(name=item.name);s.add(source)
  source.permission=item.permission;source.enabled=item.enabled
  s.flush();return {'id':source.id,'name':source.name,'permission':source.permission,'enabled':source.enabled}

@app.post(PREFIX+'/admin/fixtures/ingest',status_code=201)
def fixture_ingest(item:FixtureIntake,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 try:
  with SessionLocal.begin() as s:
   return ingest_fixture(s,item.source_name,item.sport_name,item.competition_name,item.home,item.away,item.kickoff_at,item.source_url,item.evidence)
 except (ValueError,PermissionError) as e:raise HTTPException(422,str(e)) from e

@app.get(PREFIX+'/workflow/stages')
def workflow_stages():
 names=['Mission Planning','Fixture Discovery','Source Acquisition','Deep Match Research','Data Validation','Statistical Analysis','AI Prediction','Probability Validation','Market Intelligence','Opportunity Qualification','Strategy Allocation','Ticket Optimization','Betslip Preparation','Booking-Code Verification','Continuous Monitoring','Result Reconciliation','Model Evaluation & Learning']
 return [{'stage':i+1,'name':name,'state':'NOT_VERIFIED','mode':'PAPER'} for i,name in enumerate(names)]

@app.post(PREFIX+'/qualification/evaluate')
def qualification_preview(gates:dict):
 # Stateless preview; does not create a qualified opportunity or ticket.
 return evaluate(gates)


# V2.1: Evidence-bound research and audited PAPER mission lifecycle.
from app.modules.research.service import build_dossier
from app.modules.operations.service import create_mission,transition

class ResearchIntake(BaseModel):
    fixture_id:str
    sections:dict
    evidence_ids:list[str]

class MissionCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120)

class MissionTransition(BaseModel):
    status:str

@app.post(PREFIX+'/admin/research/dossiers',status_code=201)
def research_dossier_ingest(item:ResearchIntake,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:
            return build_dossier(session,item.fixture_id,item.sections,item.evidence_ids)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.post(PREFIX+'/admin/missions',status_code=201)
def mission_create(item:MissionCreate,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:return create_mission(session,item.name)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.post(PREFIX+'/admin/missions/{mission_id}/transition')
def mission_transition(mission_id:str,item:MissionTransition,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:return transition(session,mission_id,item.status)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get(PREFIX+'/research/readiness')
def research_readiness():
    with SessionLocal() as session:
        dossiers=session.scalars(select(m.Research).order_by(m.Research.created_at.desc()).limit(100)).all()
        return [{'fixture_id':d.fixture_id,'dossier_id':d.id,'version':d.version,'status':d.status,'verified_sections':sum(x.get('status')=='VERIFIED' for x in d.sections.values()),'total_sections':len(d.sections),'created_at':d.created_at} for d in dossiers]





# V2.2: Authorized source observations and temporal-safe feature snapshots.
from app.modules.acquisition.service import ingest_observation,build_feature_snapshot,ALLOWED_SECTIONS

class ObservationIntake(BaseModel):
    source_id:str
    fixture_id:str
    section:str
    source_url:str
    observed_at:datetime
    payload:dict

class FeatureIntake(BaseModel):
    research_id:str
    cutoff_at:datetime
    required_sections:list[str]

@app.post(PREFIX+'/admin/research/observations',status_code=201)
def observation_intake(item:ObservationIntake,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:return ingest_observation(session,**item.model_dump())
    except (ValueError,PermissionError) as exc:raise HTTPException(422,str(exc)) from exc

@app.post(PREFIX+'/admin/features/materialize',status_code=201)
def feature_materialize(item:FeatureIntake,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:return build_feature_snapshot(session,**item.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get(PREFIX+'/fixtures/{id}/observations')
def fixture_observations(id:str):
    with SessionLocal() as session:
        observations=session.scalars(select(m.Observation).where(m.Observation.fixture_id==id).order_by(m.Observation.observed_at.desc()).limit(100)).all()
        return [{'id':o.id,'source_id':o.source_id,'section':o.payload.get('section'),'source_url':o.source_url,'observed_at':o.observed_at,'content_hash':o.content_hash} for o in observations]

@app.get(PREFIX+'/research/{id}/features')
def research_features(id:str):
    with SessionLocal() as session:
        features=session.scalars(select(m.Feature).where(m.Feature.research_id==id).order_by(m.Feature.cutoff_at.desc()).limit(100)).all()
        return [{'id':f.id,'research_id':f.research_id,'cutoff_at':f.cutoff_at,'sections':list(f.features.get('sections',{})),'evidence_ids':f.features.get('evidence_ids',[])} for f in features]

@app.get(PREFIX+'/research/evidence-coverage')
def evidence_coverage():
    with SessionLocal() as session:
        observations=session.scalars(select(m.Observation).limit(5000)).all()
        counts={section:0 for section in sorted(ALLOWED_SECTIONS)}
        for observation in observations:
            section=observation.payload.get('section')
            if section in counts:counts[section]+=1
        return {'sections':counts,'sample_limit':5000,'sampled_observations':len(observations),'mode':'PAPER','note':'Counts are recorded observations, not verified research completeness'}



# V2.3: Durable acquisition queue; configured, authorized JSON feeds only.
from app.modules.acquisition.jobs import enqueue,feed_config
class AcquisitionRequest(BaseModel):
    source_id:str
    fixture_id:str
    section:str
    period_key:str=Field(min_length=1,max_length=100)
@app.post(PREFIX+'/admin/acquisition/jobs',status_code=202)
def create_acquisition_job(item:AcquisitionRequest,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:result=enqueue(session,**item.model_dump())
        # Beat recovers PENDING jobs even if broker delivery fails.
        return result
    except (ValueError,PermissionError) as exc:raise HTTPException(422,str(exc)) from exc
@app.get(PREFIX+'/acquisition/jobs')
def acquisition_jobs():
    from app.modules.acquisition import source_intelligence as si
    with SessionLocal() as session:return si.acquisition_jobs(session)
@app.get(PREFIX+'/acquisition/jobs/{job_id}')
def acquisition_job_detail(job_id:str):
    with SessionLocal() as session:
        j=session.get(m.AcquisitionJob,job_id)
        if j is None:raise HTTPException(404,'Acquisition job not found')
        return {'id':j.id,'status':j.status,'attempts':j.attempts,'error_code':j.error_code,'observation_id':j.observation_id}



# V2.4: leakage-aware challenger training and governed prediction previews.
from app.modules.prediction.service import create_challenger,preview_model,FEATURE_NAMES
class ModelTrainingRequest(BaseModel):
    sport_id:str
    name:str=Field(min_length=2,max_length=120)
    version:str=Field(min_length=1,max_length=40)
    examples:list[dict]

@app.post(PREFIX+'/admin/models/challengers',status_code=201)
def train_challenger(item:ModelTrainingRequest,x_admin_token:str|None=Header(default=None)):
    admin_guard(x_admin_token)
    try:
        with SessionLocal.begin() as session:
            return create_challenger(session,item.sport_id,item.name,item.version,item.examples)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get(PREFIX+'/models/{id}/validation')
def model_validation(id:str):
    with SessionLocal() as session:
        obj=session.get(m.ModelVersion,id)
        if obj is None:raise HTTPException(404,'Unknown model')
        return {'id':obj.id,'name':obj.name,'version':obj.version,'status':obj.status,'validation':obj.validation}

@app.get(PREFIX+'/models/feature-contract')
def model_feature_contract():
    return {'features':FEATURE_NAMES,'market':'BINARY_RESEARCH_PROTOTYPE','status':'CHALLENGER_ONLY'}

@app.get(PREFIX+'/models/{model_id}/preview/{feature_id}')
def model_prediction_preview(model_id:str,feature_id:str):
    with SessionLocal() as session:
        try:return preview_model(session,model_id,feature_id)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc


# V2.5 Market intelligence: admin-only ingestion, evidence-linked qualification.
from decimal import Decimal
from app.modules.markets.persistence import qualify_from_database
class OddsIntake(BaseModel):
 fixture_id:str
 bookmaker:str=Field(min_length=2,max_length=60)
 market_key:str=Field(min_length=1,max_length=100)
 outcome_key:str=Field(min_length=1,max_length=100)
 decimal_odds:Decimal=Field(gt=1)
 observed_at:datetime
class QualificationIntake(BaseModel):
 prediction_id:str
 odds_id:str

@app.post(PREFIX+'/admin/markets/odds',status_code=201)
def ingest_market_odds(item:OddsIntake,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 if item.observed_at.tzinfo is None:raise HTTPException(422,'Timezone required')
 if item.observed_at>datetime.now(timezone.utc):raise HTTPException(422,'Future odds observations rejected')
 with SessionLocal.begin() as s:
  if s.get(m.Fixture,item.fixture_id) is None:raise HTTPException(404,'Fixture not found')
  o=m.Odds(fixture_id=item.fixture_id,bookmaker=item.bookmaker,market_key=item.market_key,outcome_key=item.outcome_key,decimal_odds=item.decimal_odds,observed_at=item.observed_at)
  s.add(o);s.flush();return {'id':o.id,'mode':'PAPER','status':'RECORDED','verified_external':False}

@app.post(PREFIX+'/admin/qualification/decisions',status_code=201)
def create_qualification(item:QualificationIntake,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 try:
  with SessionLocal.begin() as s:return qualify_from_database(s,item.prediction_id,item.odds_id)
 except LookupError as e:raise HTTPException(404,str(e)) from e

@app.get(PREFIX+'/markets/summary')
def market_summary():
 with SessionLocal() as s:
  return {'mode':'PAPER','odds_snapshots':s.scalar(select(func.count()).select_from(m.Odds)) or 0,'qualification_decisions':s.scalar(select(func.count()).select_from(m.Qualification)) or 0,'qualified':s.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0}

# V2.6: strategy allocation from persisted, qualified, independently evidenced opportunities.
from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES
from sqlalchemy.exc import IntegrityError
class StrategyRunRequest(BaseModel):
 idempotency_key:str=Field(min_length=8,max_length=128)
 limit:int=Field(default=5,ge=1,le=25)
 draw_legs:int|None=None

@app.post(PREFIX+'/admin/programmes/{key}/run',status_code=201)
def run_paper_strategy(key:str,item:StrategyRunRequest,x_admin_token:str|None=Header(default=None)):
 admin_guard(x_admin_token)
 if key not in PROGRAMMES:raise HTTPException(404,'Unknown programme')
 if key=='draws' and item.draw_legs not in (2,5,8,10):raise HTTPException(422,'Select 2, 5, 8 or 10 draw legs')
 with SessionLocal.begin() as db:
  previous=db.scalar(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.idempotency_key==item.idempotency_key))
  if previous:return {'id':previous.id,'replayed':True,**previous.result}
  records=db.execute(select(m.Qualification,m.Prediction,m.Odds,m.Fixture).join(m.Prediction,m.Qualification.prediction_id==m.Prediction.id).join(m.Odds,m.Qualification.odds_id==m.Odds.id).join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id).where(m.Qualification.decision=='QUALIFIED',m.Fixture.kickoff_at>datetime.now(timezone.utc)).limit(200)).all()
  candidates=[]
  for q,p,o,f in records:
   gates=q.gates or {}
   if not gates or any(v!='PASS' for v in gates.values()):continue
   if p.fixture_id!=o.fixture_id or p.market_key!=o.market_key or p.outcome_key!=o.outcome_key:continue
   if o.observed_at.tzinfo is None or (datetime.now(timezone.utc)-o.observed_at).total_seconds()>900:continue
   candidates.append(Candidate(q.id,f.id,Decimal(str(o.decimal_odds)),Decimal(str(p.probability)),p.market_key,p.outcome_key,f.kickoff_at.isoformat()))
  proposals=select_tickets(candidates,key,item.limit,item.draw_legs)
  # No ticket persisted without a fully qualified decision. No paid execution.
  run=m.StrategyRun(programme_key=key,idempotency_key=item.idempotency_key,result={'mode':'PAPER','candidate_count':len(candidates),'proposals':proposals,'count':len(proposals)})
  db.add(run);db.flush()
  db.add(m.AuditEvent(actor='admin',action='strategy.paper_run',correlation_id=run.id,payload={'programme':key,'candidate_count':len(candidates),'proposals':len(proposals)}))
  return {'id':run.id,'replayed':False,**run.result}

from app.modules.tickets.routes import router as paper_ticket_router
app.include_router(paper_ticket_router)

from app.modules.results.routes import router as results_router
app.include_router(results_router)

from app.modules.learning.routes import router as learning_router
app.include_router(learning_router)

from app.modules.vision.routes import router as vision_router
from app.modules.governance.routes import router as governance_router
app.include_router(vision_router)
app.include_router(governance_router)

from app.modules.pipeline.routes import router as pipeline_router
app.include_router(pipeline_router)
from app.modules.live.routes import router as live_router
app.include_router(live_router)

# V3.3: Readiness is deliberately separate from liveness and fails closed.
from app.modules.readiness import assess_readiness
@app.get(PREFIX + '/readiness')
def readiness():
 return assess_readiness()

from app.modules.research.league_routes import router as league_router
app.include_router(league_router)

from app.modules.research.catalog_routes import router as research_catalog_router
app.include_router(research_catalog_router)

from app.modules.autonomy.routes import router as autonomy_router
app.include_router(autonomy_router)

from app.modules.pipeline.context import router as workflow_context_router
app.include_router(workflow_context_router)

from app.modules.research.fixture_intelligence import router as fixture_intelligence_router
app.include_router(fixture_intelligence_router)

from app.modules.standings.routes import router as standings_router
app.include_router(standings_router)

from app.modules.research.deep_workspace_routes import router as deep_workspace_router
app.include_router(deep_workspace_router)
# Version 3.6: read-only, evidence-backed Match Analysis workspace
from app.modules.match_analysis.routes import router as match_analysis_router
app.include_router(match_analysis_router)
# Market catalogue + paper-only prediction evaluation (canonical odds/forecasts; no scraping)
from app.modules.market_scanner.routes import router as market_scanner_router
app.include_router(market_scanner_router)
# Market catalogue, per-fixture availability and AI market scans (scans run in the Evaluate stage)
from app.modules.markets.catalogue_routes import router as market_catalogue_router
app.include_router(market_catalogue_router)
# Market Intelligence: closing-odds archive, coverage, sources and sync history on canonical records
from app.modules.markets.intelligence_routes import router as market_intelligence_router
app.include_router(market_intelligence_router)
# Autonomous AI Qualification (v3.7 patch, runs inside the autonomy cycle)
from app.modules.qualification.routes_autonomous import router as qualification_router
app.include_router(qualification_router)
# Autonomous paper Accumulator Engine (runs inside the autonomy cycle)
from app.modules.strategies.accumulator_routes import router as accumulator_router
app.include_router(accumulator_router)
# Automatic Singles (shared programme engine, runs inside the autonomy cycle)
from app.modules.strategies.singles_routes import router as singles_router
app.include_router(singles_router)
# Jackpot Engine (shared programme engine, runs inside the autonomy cycle)
from app.modules.strategies.jackpot_routes import router as jackpot_router
app.include_router(jackpot_router)
# Weekly Draw Centre (shared programme engine, weekly run inside the autonomy cycle)
from app.modules.strategies.draws_routes import router as draws_router
app.include_router(draws_router)
# Daily Rollover Centre (shared programme engine, daily run inside the autonomy cycle)
from app.modules.strategies.rollover_routes import router as rollover_router
app.include_router(rollover_router)
# Ticket Builder (registers programme-engine paper tickets in the canonical ticket register)
from app.modules.tickets.builder_routes import router as ticket_builder_router
app.include_router(ticket_builder_router)

from app.modules.tickets.workspace_routes import router as betslip_workspace_router
app.include_router(betslip_workspace_router)

from app.modules.tickets.booking_workspace_routes import router as booking_workspace_router
app.include_router(booking_workspace_router)

@app.get(PREFIX+'/{resource:path}')
def list_resource(resource:str):
 if resource not in TABLES:raise HTTPException(404,'Unknown resource')
 try:return rows_for(resource)
 except SQLAlchemyError as exc:raise HTTPException(503,'Database unavailable or migration missing') from exc
