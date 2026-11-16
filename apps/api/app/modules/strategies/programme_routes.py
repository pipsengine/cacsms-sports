"""Read-only API factory for programmes served by the shared programme engine (Automatic Singles, Jackpot)."""
from datetime import datetime,timezone
from fastapi import APIRouter,Query
from sqlalchemy import select,func
from app.db import models as m
from app.modules.strategies import programme_engine as pe


def make_router(key,session,tag):
 """`session` is a zero-argument callable returning a Session (resolved per request, so tests can patch it)."""
 router=APIRouter(prefix=f'/api/v1/sports/programmes/{key}',tags=[tag])

 @router.get('/overview')
 def get_overview():
  with session() as db:return pe.overview(db,key)

 @router.get('/configuration')
 def get_configuration():return {'policy':pe.policy(key),'mode':'PAPER','autonomous':True,'live_wagers_enabled':False,
                                 'required_gates':list(pe.REQUIRED_GATES)+list(pe.OPTIONAL_GATES),'source':'app.modules.strategies.optimizer.PROGRAMMES'}

 @router.get('/candidates')
 def get_candidates():
  with session() as db:
   rows,excluded=pe.programme_rows(key,*pe.eligible(db,datetime.now(timezone.utc)))
   return {'items':rows,'excluded':excluded,'policy':pe.policy(key),
           'reachable_odds':pe.reachable_odds(rows,key) if key in pe.MIN_COMBINED_ODDS else None}

 @router.get('/run-history')
 def get_runs(limit:int=Query(default=20,ge=1,le=200),offset:int=Query(default=0,ge=0)):
  with session() as db:return pe.runs(db,key,limit,offset)

 @router.get('/tickets')
 def get_tickets(limit:int=Query(default=50,ge=1,le=500)):
  """Paper tickets from completed runs, newest first, with verified settlement when available."""
  with session() as db:
   out=[]
   for r in db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.status=='COMPLETED').order_by(m.StrategyRun.created_at.desc()).limit(200)):
    for t in pe.run_tickets(r):
     legs=t['legs'];one=legs[0] if len(legs)==1 else None
     out.append({'run_id':r.id,'created_at':r.created_at,'legs':len(legs),'fixture':one['fixture'] if one else f'{len(legs)} fixtures',
                 'market_key':one['market_key'] if one else None,'outcome_key':one['outcome_key'] if one else None,'odds':t['combined_odds'],
                 'probability':one['probability'] if one else None,'probability_lower_bound':t.get('probability_lower_bound'),'probability_upper_bound':t.get('probability_upper_bound'),
                 'ev':one['ev'] if one else None,'paper_stake':t.get('paper_stake'),'potential_return':t.get('potential_return'),'settlement':pe.settle_ticket(db,t)})
   return {'total':len(out),'items':out[:limit]}

 @router.get('/validation')
 def get_validation():
  with session() as db:return pe.validation(db,datetime.now(timezone.utc))

 @router.get('/analytics')
 def get_analytics():
  with session() as db:return pe.analytics(db,key,datetime.now(timezone.utc))

 @router.get('/health')
 def get_health():
  with session() as db:
   db.execute(select(func.count()).select_from(m.StrategyRun))
   from app.modules.autonomy.service import runtime_status
   return {'database':'CONNECTED','mode':'PAPER','scheduler':'ACTIVE' if runtime_status(db).get('worker_online') else 'OFFLINE'}

 return router
