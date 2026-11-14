from fastapi import APIRouter,Header,HTTPException
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
router=APIRouter(prefix='/api/v1/sports',tags=['Model governance'])
@router.get('/governance/summary')
def governance_summary():
 with SessionLocal() as db:
  models=db.scalars(select(m.ModelVersion)).all()
  snapshots=db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc()).limit(200)).all()
  latest={}
  for s in snapshots:latest.setdefault(s.model_id,s)
  return {'mode':'PAPER','automatic_activation':False,'models':[{'id':x.id,'name':x.name,'version':x.version,'status':x.status,'monitoring':latest[x.id].status if x.id in latest else 'NOT_EVALUATED','reasons':latest[x.id].reasons if x.id in latest else []} for x in models], 'evaluations':len(snapshots)}
@router.get('/governance/evaluations')
def governance_evaluations():
 with SessionLocal() as db:
  return [{'id':x.id,'model_id':x.model_id,'status':x.status,'reasons':x.reasons,'reference':x.reference,'recent':x.recent,'created_at':x.created_at} for x in db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc()).limit(100)).all()]
