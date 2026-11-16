"""Automatic Singles API (singles patch contract, served by the shared programme engine)."""
from datetime import datetime,timezone
from fastapi import APIRouter,Query
from sqlalchemy import select,func
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.strategies import programme_engine as pe

KEY='singles'
router=APIRouter(prefix='/api/v1/sports/programmes/singles',tags=['Automatic Singles'])


@router.get('/overview')
def get_overview():
 with SessionLocal() as db:return pe.overview(db,KEY)


@router.get('/configuration')
def get_configuration():return {'policy':pe.policy(KEY),'mode':'PAPER','autonomous':True,'live_wagers_enabled':False,
                                'required_gates':list(pe.REQUIRED_GATES)+list(pe.OPTIONAL_GATES),'source':'app.modules.strategies.optimizer.PROGRAMMES'}


@router.get('/candidates')
def get_candidates():
 with SessionLocal() as db:
  rows,excluded=pe.eligible(db,datetime.now(timezone.utc))
  return {'items':rows,'excluded':excluded,'policy':pe.policy(KEY)}


@router.get('/run-history')
def get_runs(limit:int=Query(default=20,ge=1,le=200),offset:int=Query(default=0,ge=0)):
 with SessionLocal() as db:return pe.runs(db,KEY,limit,offset)


@router.get('/tickets')
def get_tickets(limit:int=Query(default=50,ge=1,le=500)):
 """Paper singles (one row per ticket) from completed runs, newest first, with verified settlement when available."""
 with SessionLocal() as db:
  out=[]
  for r in db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY,m.StrategyRun.status=='COMPLETED').order_by(m.StrategyRun.created_at.desc()).limit(200)):
   for t in pe.run_tickets(r):
    leg=t['legs'][0]
    out.append({'run_id':r.id,'created_at':r.created_at,'fixture':leg['fixture'],'market_key':leg['market_key'],'outcome_key':leg['outcome_key'],'odds':t['combined_odds'],
                'probability':leg['probability'],'ev':leg['ev'],'paper_stake':t.get('paper_stake'),'potential_return':t.get('potential_return'),'settlement':pe.settle_ticket(db,t)})
  return {'total':len(out),'items':out[:limit]}


@router.get('/validation')
def get_validation():
 with SessionLocal() as db:return pe.validation(db,datetime.now(timezone.utc))


@router.get('/analytics')
def get_analytics():
 with SessionLocal() as db:return pe.analytics(db,KEY,datetime.now(timezone.utc))


@router.get('/health')
def get_health():
 with SessionLocal() as db:
  db.execute(select(func.count()).select_from(m.StrategyRun))
  from app.modules.autonomy.service import runtime_status
  return {'database':'CONNECTED','mode':'PAPER','scheduler':'ACTIVE' if runtime_status(db).get('worker_online') else 'OFFLINE'}
