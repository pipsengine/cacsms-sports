from fastapi import APIRouter,Header,HTTPException,Query
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
router=APIRouter(prefix='/api/v1/sports',tags=['Model governance'])

@router.get('/models/workspace')
def models_workspace(days:int=Query(30,ge=1,le=365)):
 from sqlalchemy.exc import SQLAlchemyError
 from app.modules.governance.workspace import workspace
 try:
  with SessionLocal() as db:return workspace(db,days)
 except SQLAlchemyError as exc:
  raise HTTPException(503,'Model registry database unavailable') from exc


@router.post('/models/{model_id}/promote')
def promote(model_id:str,x_admin_token:str|None=Header(None)):
 """Promote a challenger only if its out-of-sample validation passes; flags are server-computed."""
 from app.modules.pipeline.routes import admin_guard
 from app.modules.governance.promotion import promote_model
 admin_guard(x_admin_token)
 try:
  with SessionLocal.begin() as db:result=promote_model(db,model_id,actor='admin')
 except LookupError as exc:raise HTTPException(404,str(exc)) from exc
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc
 if not result['promoted']:raise HTTPException(422,{'message':'Out-of-sample validation failed','reasons':result['reasons'],'evidence':result['evidence']})
 return result
@router.get('/governance/summary')
def governance_summary():
 with SessionLocal() as db:
  models=db.scalars(select(m.ModelVersion)).all()
  snapshots=db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc()).limit(200)).all()
  latest={}
  for s in snapshots:latest.setdefault(s.model_id,s)
  return {'mode':'PAPER','automatic_activation':False,'models':[{'id':x.id,'name':x.name,'version':x.version,'status':x.status,'monitoring':latest[x.id].status if x.id in latest else 'NOT_EVALUATED','reasons':latest[x.id].reasons if x.id in latest else [],'monitoring_ready':x.id in latest and latest[x.id].status=='MONITORED','sample_progress':(latest[x.id].recent or {}).get('monitoring_progress',{}) if x.id in latest else {}} for x in models], 'evaluations':len(snapshots)}
@router.get('/governance/evaluations')
def governance_evaluations():
 with SessionLocal() as db:
  return [{'id':x.id,'model_id':x.model_id,'status':x.status,'reasons':x.reasons,'reference':x.reference,'recent':x.recent,'created_at':x.created_at} for x in db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc()).limit(100)).all()]
