"""Read-only settlement views plus administrator-controlled verified result intake."""
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException,Header
from pydantic import BaseModel,Field
from sqlalchemy import select,func,text
from sqlalchemy.exc import IntegrityError
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.results.service import validate_result_payload,settle_outcome,performance_summary,ResultValidationError

router=APIRouter(prefix='/api/v1/sports',tags=['Results & Learning'])

class OfficialResultIn(BaseModel):
 fixture_id:str
 source_id:str
 observation_id:str
 outcome:dict
 verified_at:datetime


def admin_only(token:str|None):
 # Fail closed: no token configured means admin operations unavailable.
 from os import getenv
 expected=getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not token:
  raise HTTPException(403,'Administrative access is not configured')
 from hmac import compare_digest
 if not compare_digest(token,expected):raise HTTPException(403,'Invalid administrator token')

@router.post('/admin/results/official',status_code=201)
def ingest_official_result(item:OfficialResultIn,x_admin_token:str|None=Header(default=None)):
 admin_only(x_admin_token)
 if item.verified_at.tzinfo is None or item.verified_at>datetime.now(timezone.utc):raise HTTPException(422,'Valid past UTC-aware verification time required')
 try:clean=validate_result_payload(item.outcome)
 except ResultValidationError as exc:raise HTTPException(422,str(exc)) from exc
 with SessionLocal.begin() as db:
  fixture=db.get(m.Fixture,item.fixture_id)
  source=db.get(m.Source,item.source_id)
  observation=db.get(m.Observation,item.observation_id)
  if not fixture:raise HTTPException(404,'Unknown fixture')
  if not source or not source.enabled or source.permission!='AUTHORIZED':raise HTTPException(422,'Authorized result source required')
  if not observation or observation.source_id!=source.id or observation.fixture_id!=fixture.id:
   raise HTTPException(422,'Evidence observation must match source and fixture')
  if observation.observed_at>item.verified_at:raise HTTPException(422,'Evidence cannot postdate result verification')
  if item.verified_at<fixture.kickoff_at:raise HTTPException(422,'Result cannot precede kickoff')
  if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'result:fixture:'+fixture.id})
  previous=db.scalars(select(m.Result).where(m.Result.fixture_id==fixture.id).order_by(m.Result.version.desc()).with_for_update()).first()
  if previous and previous.outcome==clean:return {'id':previous.id,'version':previous.version,'replayed':True,'mode':'PAPER'}
  result=m.Result(fixture_id=fixture.id,version=1+(previous.version if previous else 0),outcome=clean,verified_at=item.verified_at)
  db.add(result);db.flush()
  evidence=m.ResultEvidence(result_id=result.id,source_id=source.id,observation_id=observation.id)
  db.add(evidence)
  forecasts=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id)).all()
  counts={'WON':0,'LOST':0,'VOID':0,'PUSH':0,'UNRESOLVED':0}
  for forecast in forecasts:
   status=settle_outcome(clean,forecast.market_key,forecast.outcome_key)
   counts[status]+=1
   db.add(m.Settlement(prediction_id=forecast.id,result_id=result.id,outcome=status))
  db.add(m.AuditEvent(actor='admin',action='result.official_version_ingested',correlation_id=result.id,payload={'fixture_id':fixture.id,'version':result.version,'source_id':source.id,'observation_id':observation.id,'settlements':counts}))
  return {'id':result.id,'version':result.version,'replayed':False,'settlements':counts,'mode':'PAPER'}

@router.get('/results/verified')
def verified_results(limit:int=50):
 with SessionLocal() as db:
  rows=db.scalars(select(m.Result).order_by(m.Result.verified_at.desc()).limit(min(max(limit,1),200))).all()
  return [{'id':r.id,'fixture_id':r.fixture_id,'version':r.version,'outcome':r.outcome,'verified_at':r.verified_at.isoformat()} for r in rows]

@router.get('/settlements/latest')
def latest_settlements(limit:int=100):
 with SessionLocal() as db:
  # Corrected results supersede earlier versions without erasing the original settlement history.
  rows=db.execute(select(m.Settlement,m.Prediction,m.Result).join(m.Prediction,m.Settlement.prediction_id==m.Prediction.id).join(m.Result,m.Settlement.result_id==m.Result.id).order_by(m.Result.verified_at.desc()).limit(2000)).all()
  latest={}
  for s,p,r in rows:
   if p.id not in latest or r.version>latest[p.id][2].version:latest[p.id]=(s,p,r)
  return [{'prediction_id':p.id,'fixture_id':p.fixture_id,'market_key':p.market_key,'outcome_key':p.outcome_key,'probability':float(p.probability),'outcome':s.outcome,'result_version':r.version,'verified_at':r.verified_at.isoformat()} for s,p,r in list(latest.values())[:min(max(limit,1),200)]]

@router.get('/performance/forecast-quality')
def forecast_quality():
 with SessionLocal() as db:
  rows=db.execute(select(m.Settlement,m.Prediction,m.Result).join(m.Prediction,m.Settlement.prediction_id==m.Prediction.id).join(m.Result,m.Settlement.result_id==m.Result.id)).all()
  latest={}
  for s,p,r in rows:
   if p.id not in latest or r.version>latest[p.id][2].version:latest[p.id]=(s,p,r)
  result=performance_summary([(float(p.probability),s.outcome) for s,p,r in latest.values()])
  return {'mode':'PAPER',**result,'last_verified_at':max((r.verified_at.isoformat() for s,p,r in latest.values()),default=None)}

from app.modules.results.automation import reconcile_pending

@router.get('/results/automation/status')
def results_automation_status():
 return {'mode':'PAPER','operation':'AUTHORIZED_OBSERVATIONS_ONLY','enabled':True,'real_money':False}

@router.post('/admin/results/reconcile-pending')
def reconcile_results_now(limit:int=100,x_admin_token:str|None=Header(default=None)):
 admin_only(x_admin_token)
 if not 1<=limit<=500:raise HTTPException(422,'limit must be 1..500')
 with SessionLocal.begin() as db:return reconcile_pending(db,limit)
