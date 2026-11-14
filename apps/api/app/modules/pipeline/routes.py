"""Pipeline read endpoints and explicitly authenticated PAPER-only evaluation."""
from datetime import datetime,timezone
from time import monotonic
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.pipeline.logic import STAGES,STATUS_COLORS,gate,utcnow
from app.core.config import EXECUTION_MODE
import os
from secrets import compare_digest
def admin_guard(token):
 expected=os.getenv("ADMIN_API_TOKEN","")
 if not expected or not token or not compare_digest(token,expected):raise HTTPException(403,"Administrator authorization required")
router=APIRouter(prefix='/api/v1/sports/pipeline',tags=['Pipeline'])
class CreateRun(BaseModel):
 idempotency_key:str=Field(min_length=8,max_length=128)
 fixture_id:str|None=None
class EvidenceUpdate(BaseModel):
 context:dict=Field(default_factory=dict)
def serialize_stage(s):
 return {'id':s.id,'position':s.position,'stage_key':s.stage_key,'name':dict((k,n) for k,n,_ in STAGES)[s.stage_key],'status':s.status,'color':STATUS_COLORS.get(s.status,'gray'),'input':s.input_payload,'output':s.output_payload,'evidence_ids':s.evidence_ids,'error':s.error,'retry_count':s.retry_count,'started_at':s.started_at,'finished_at':s.finished_at,'duration_ms':s.duration_ms}
def serialize_run(db,r):
 stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==r.id).order_by(m.PipelineStage.position)).all()
 return {'id':r.id,'fixture_id':r.fixture_id,'mode':r.mode,'status':r.status,'created_at':r.created_at,'updated_at':r.updated_at,'stages':[serialize_stage(s) for s in stages]}
@router.get('/definitions')
def definitions():return {'stages':[{'key':k,'name':n,'evidence_type':e} for k,n,e in STAGES],'colors':STATUS_COLORS,'mode':'PAPER'}
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
  r=db.scalar(select(m.PipelineRun).where(m.PipelineRun.idempotency_key==item.idempotency_key))
  if r:return serialize_run(db,r)
  r=m.PipelineRun(idempotency_key=item.idempotency_key,fixture_id=item.fixture_id,status='PENDING',mode='PAPER',context={})
  db.add(r);db.flush()
  for i,(key,_,_) in enumerate(STAGES):db.add(m.PipelineStage(run_id=r.id,position=i+1,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=[]))
  db.add(m.AuditEvent(actor='admin',action='pipeline.created',correlation_id=r.id,payload={'mode':'PAPER'}))
  db.flush()
  return serialize_run(db,r)
@router.post('/runs/{run_id}/evaluate')
def evaluate(run_id:str,item:EvidenceUpdate,x_admin_token:str|None=Header(None)):
 admin_guard(x_admin_token)
 if EXECUTION_MODE!='PAPER':raise HTTPException(403,'PAPER-only pipeline')
 # Evidence references are only evaluated, not independently authenticated by this endpoint.
 # They cannot be used to create qualified selections or booking codes.
 with SessionLocal.begin() as db:
  r=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==run_id).with_for_update())
  if not r:raise HTTPException(404,'Unknown run')
  if r.status in ('FAILED','REJECTED','EXPIRED'):raise HTTPException(409,'Terminal run')
  # Untrusted client claims are not evidence. Persist them only for review,
  # never use them to mark a stage VERIFIED.
  context={**(r.context or {}),**item.context}
  verified_context={}
  stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run_id).order_by(m.PipelineStage.position).with_for_update()).all()
  for s in stages:
   if s.status=='VERIFIED':continue
   if s.status in ('BLOCKED','FAILED','REJECTED','EXPIRED'):break
   started=monotonic();s.started_at=utcnow();s.status='RUNNING'
   state,error=gate(s.stage_key,verified_context)
   s.finished_at=utcnow();s.duration_ms=max(0,int((monotonic()-started)*1000));s.status=state;s.error=error
   s.input_payload={'required_evidence_type':STAGES[s.position-1][2]}
   s.evidence_ids=[str(v) for k,vs in context.items() if k.endswith('_ids') and isinstance(vs,list) for v in vs][:100]
   s.output_payload={'decision':state,'reason':error,'attestation':'NOT_VERIFIED'}
   if state!='VERIFIED':break
  r.context=context;r.updated_at=utcnow()
  r.status='VERIFIED' if all(s.status=='VERIFIED' for s in stages) else ('BLOCKED' if any(s.status=='BLOCKED' for s in stages) else 'WAITING_FOR_DATA')
  db.add(m.AuditEvent(actor='admin',action='pipeline.evaluated',correlation_id=r.id,payload={'status':r.status,'stage_states':[s.status for s in stages]}))
  db.flush();return serialize_run(db,r)

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
  execute_run(db,run)
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
