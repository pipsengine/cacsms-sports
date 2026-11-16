"""Pipeline read endpoints and authenticated PAPER-only execution.

Stage completion is only ever set by the server-side runner from persisted receipts; there is
no endpoint that accepts client-supplied evidence.
"""
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,text
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.pipeline.logic import STAGES,STATUS_COLORS,SETTLED,BUSINESS_OUTCOMES
from app.core.config import EXECUTION_MODE
import os
from secrets import compare_digest
def admin_guard(token):
 expected=os.getenv("SPORTS_ADMIN_TOKEN","") or os.getenv("ADMIN_API_TOKEN","")
 if not expected or not token or not compare_digest(token,expected):raise HTTPException(403,"Administrator authorization required")
router=APIRouter(prefix='/api/v1/sports/pipeline',tags=['Pipeline'])
class CreateRun(BaseModel):
 idempotency_key:str=Field(min_length=8,max_length=128)
 fixture_id:str|None=None
def stage_href(stage,rid,fixture_id=None):
 from urllib.parse import urlencode
 from app.modules.pipeline.runner import PAGES
 query={'run_id':rid,'stage':stage.stage_key}
 if fixture_id:query['fixture_id']=fixture_id
 return '/sports/'+PAGES[stage.stage_key]+'?'+urlencode(query)


def contract(run,s):
 """The standard versioned stage data contract (latest state)."""
 return {'pipeline_run_id':s.run_id,'fixture_id':run.fixture_id if run else None,'stage':s.stage_key.upper(),'status':s.status,
         'input_version':s.input_version or 0,'output_version':s.output_version or 0,'started_at':s.started_at,'completed_at':s.finished_at,
         'evidence_ids':list(s.evidence_ids or []),'output_reference':s.output_reference,
         'quality_score':float(s.quality_score) if s.quality_score is not None else None,
         'failure_code':s.failure_code,'failure_reason':None if s.status=='VERIFIED' else s.error,
         'next_stage':s.next_stage.upper() if s.next_stage else None}


def serialize_stage(s,run=None):
 return {'id':s.id,'position':s.position,'stage_key':s.stage_key,'name':dict((k,n) for k,n,_ in STAGES)[s.stage_key],'status':s.status,
         'color':STATUS_COLORS.get(s.status,'gray'),'settled':s.status in SETTLED,'business_outcome':s.status in BUSINESS_OUTCOMES,
         'input':s.input_payload,'output':s.output_payload,'evidence_ids':s.evidence_ids,'error':s.error,'retry_count':s.retry_count,
         'started_at':s.started_at,'finished_at':s.finished_at,'duration_ms':s.duration_ms,'next_retry_at':s.next_retry_at,
         'input_version':s.input_version or 0,'output_version':s.output_version or 0,'output_reference':s.output_reference,
         'quality_score':float(s.quality_score) if s.quality_score is not None else None,'failure_code':s.failure_code,'next_stage':s.next_stage,
         'contract':contract(run,s),'href':stage_href(s,s.run_id,run.fixture_id if run else None)}


def serialize_run(db,r):
 stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==r.id).order_by(m.PipelineStage.position)).all()
 settled=sum(s.status in SETTLED for s in stages)
 return {'id':r.id,'fixture_id':r.fixture_id,'mode':r.mode,'status':r.status,'outcome':(r.context or {}).get('outcome'),
         'created_at':r.created_at,'updated_at':r.updated_at,'stages':[serialize_stage(s,r) for s in stages],
         'progress':settled/12,'settled_stages':settled,'verified_stages':sum(s.status=='VERIFIED' for s in stages),'fixture_count':1 if r.fixture_id else 0}
@router.get('/definitions')
def definitions():return {'stages':[{'key':k,'name':n,'evidence_type':e} for k,n,e in STAGES],'colors':STATUS_COLORS,'mode':'PAPER',
                          'business_outcomes':sorted(BUSINESS_OUTCOMES),'settled_statuses':sorted(SETTLED)}
@router.get('/runs')
def runs():
 with SessionLocal() as db:
  return [serialize_run(db,r) for r in db.scalars(select(m.PipelineRun).order_by(m.PipelineRun.created_at.desc()).limit(30)).all()]
@router.get('/runs/{run_id}')
def run_detail(run_id:str):
 with SessionLocal() as db:
  r=db.get(m.PipelineRun,run_id)
  if not r:raise HTTPException(404,'Unknown run')
  return serialize_run(db,r)
@router.post('/runs',status_code=201)
def create_run(item:CreateRun,x_admin_token:str|None=Header(None)):
 admin_guard(x_admin_token)
 if EXECUTION_MODE!='PAPER':raise HTTPException(403,'PAPER-only pipeline')
 with SessionLocal.begin() as db:
  if item.fixture_id:
   if db.get(m.Fixture,item.fixture_id) is None:raise HTTPException(404,'Fixture not found')
   if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'pipeline:fixture:'+item.fixture_id})
   existing=db.scalar(select(m.PipelineRun).where(m.PipelineRun.fixture_id==item.fixture_id,m.PipelineRun.mode=='PAPER').order_by(m.PipelineRun.created_at).limit(1))
   if existing:return serialize_run(db,existing)
  r=db.scalar(select(m.PipelineRun).where(m.PipelineRun.idempotency_key==item.idempotency_key))
  if r:return serialize_run(db,r)
  r=m.PipelineRun(idempotency_key=item.idempotency_key,fixture_id=item.fixture_id,status='PENDING',mode='PAPER',context={})
  db.add(r);db.flush()
  for i,(key,_,_) in enumerate(STAGES):db.add(m.PipelineStage(run_id=r.id,position=i+1,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=[]))
  db.add(m.AuditEvent(actor='admin',action='pipeline.created',correlation_id=r.id,payload={'mode':'PAPER'}))
  db.flush()
  return serialize_run(db,r)
@router.get('/runs/{run_id}/history')
def run_history(run_id:str,stage:str|None=None,limit:int=200):
 """Immutable stage execution history in the standard data contract shape."""
 with SessionLocal() as db:
  if db.get(m.PipelineRun,run_id) is None:raise HTTPException(404,'Unknown run')
  query=select(m.PipelineStageRun).where(m.PipelineStageRun.pipeline_run_id==run_id)
  if stage:query=query.where(m.PipelineStageRun.stage==stage.lower())
  rows=db.scalars(query.order_by(m.PipelineStageRun.started_at.desc(),m.PipelineStageRun.id).limit(min(max(limit,1),1000))).all()
  return [{'id':h.id,'pipeline_run_id':h.pipeline_run_id,'fixture_id':h.fixture_id,'stage':h.stage.upper(),'status':h.status,'attempt':h.attempt,
           'input_version':h.input_version,'output_version':h.output_version,'started_at':h.started_at,'completed_at':h.completed_at,
           'duration_ms':h.duration_ms,'evidence_ids':h.evidence_ids,'output_reference':h.output_reference,
           'quality_score':float(h.quality_score) if h.quality_score is not None else None,'failure_code':h.failure_code,
           'failure_reason':h.failure_reason,'next_stage':h.next_stage.upper() if h.next_stage else None,'details':h.details} for h in rows]


@router.post('/runs/{run_id}/execute')
def execute(run_id:str,x_admin_token:str|None=Header(None)):
 admin_guard(x_admin_token)
 if EXECUTION_MODE!='PAPER':raise HTTPException(403,'PAPER-only pipeline')
 from app.modules.pipeline.executor import execute_run
 with SessionLocal.begin() as db:
  r=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==run_id).with_for_update())
  if not r:raise HTTPException(404,'Unknown run')
  execute_run(db,r)
  db.flush()
  return serialize_run(db,r)


@router.post('/runs/{run_id}/drive')
def drive(run_id:str,x_admin_token:str|None=Header(None)):
 """Run configured engines, persist outcomes, then evaluate evidence gates."""
 admin_guard(x_admin_token)
 if EXECUTION_MODE!='PAPER':raise HTTPException(403,'PAPER-only pipeline')
 from app.modules.pipeline.engine import connect_engines
 from app.modules.pipeline.executor import execute_run
 with SessionLocal.begin() as db:
  run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==run_id).with_for_update())
  if not run:raise HTTPException(404,'Unknown run')
  if run.mode!='PAPER':raise HTTPException(403,'PAPER-only run required')
  report=connect_engines(db,run)
  db.add(m.AuditEvent(actor='pipeline-driver',action='pipeline.engines_connected',correlation_id=run.id,payload=report))
  db.flush()
  result={'run':serialize_run(db,run),'engine_report':report}
 # Dispatch only after transaction commits; jobs can also be picked up by recovery.
 from app.modules.acquisition.tasks import execute as acquisition_execute
 for job_id in report['queued_job_ids']:
  try:acquisition_execute.delay(job_id)
  except Exception:pass  # Durable recovery task will pick up the persisted job.
 return result

@router.get('/fixtures/{fixture_id}/market-monitor')
def market_monitor(fixture_id:str):
 """Read persisted bookmaker snapshots. Not a claim of live provider connectivity."""
 from app.modules.markets.monitoring import inspect_market
 with SessionLocal() as db:
  if db.get(m.Fixture,fixture_id) is None:raise HTTPException(404,'Unknown fixture')
  return inspect_market(db,fixture_id)


@router.get('/events')
def events(fixture_id:str|None=None,status:str|None=None,limit:int=100):
 with SessionLocal() as db:
  query=select(m.PipelineEvent)
  if fixture_id:query=query.where(m.PipelineEvent.fixture_id==fixture_id)
  if status:query=query.where(m.PipelineEvent.status==status)
  rows=db.scalars(query.order_by(m.PipelineEvent.created_at.desc()).limit(min(max(limit,1),500))).all()
  return [{'id':row.id,'fixture_id':row.fixture_id,'kind':row.kind,'status':row.status,'attempts':row.attempts,'available_at':row.available_at,'lease_until':row.lease_until,'completed_at':row.completed_at,'error_code':row.error_code} for row in rows]


@router.get('/contracts')
def workspace_contracts():
 from app.modules.pipeline.workspace_contracts import definitions
 return definitions()


@router.get('/runs/{run_id}/evidence')
def stage_evidence(run_id:str,stage:str):
 """Resolve only references actually recorded on this run/stage, without executing it."""
 from app.modules.pipeline.workspace_contracts import INPUTS
 if stage not in INPUTS:raise HTTPException(422,'Unknown stage')
 with SessionLocal() as db:
  run=db.get(m.PipelineRun,run_id)
  if run is None:raise HTTPException(404,'Unknown run')
  row=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run_id,m.PipelineStage.stage_key==stage))
  if row is None:return []
  models=(m.Observation,m.Fixture,m.Research,m.Feature,m.Prediction,m.Odds,m.Qualification,m.StrategyRun,m.Ticket,m.Betslip,m.TicketVerification,m.StageRecord,m.Result,m.Settlement,m.BookingCode,m.TeamStatistic,m.BrowserCapture)
  identifiers=list(dict.fromkeys(row.evidence_ids or []))[:500]
  resolved={}
  for model in models:
   remaining=set(identifiers)-set(resolved)
   if not remaining:break
   objects=db.scalars(select(model).where(model.id.in_(remaining))).all()
   providers={}
   if model is m.Observation and objects:
    providers={p.id:p for p in db.scalars(select(m.Source).where(m.Source.id.in_({o.source_id for o in objects})))}
   for obj in objects:
    if model is m.Observation:
     source=providers.get(obj.source_id)
     if not source or not source.enabled or source.permission!='AUTHORIZED':
      resolved[obj.id]={'id':obj.id,'type':'Observation','status':'SOURCE_UNAVAILABLE','record':{'source_id':obj.source_id,'observed_at':obj.observed_at}}
      continue
    resolved[obj.id]={'id':obj.id,'type':model.__name__,'status':'RECORDED_REFERENCE','record':{col.name:getattr(obj,col.name) for col in model.__table__.columns}}
  return [resolved.get(ident,{'id':ident,'type':'UNRESOLVED','status':'REFERENCE_NOT_FOUND','record':None}) for ident in identifiers]
