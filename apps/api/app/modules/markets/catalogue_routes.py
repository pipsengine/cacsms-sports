import os,secrets
from datetime import datetime
from fastapi import APIRouter,HTTPException,Header,Query
from pydantic import BaseModel
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.markets import catalogue as cat

router=APIRouter(prefix='/api/v1/sports/markets',tags=['Market catalogue & scanning'])


def admin(token):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not token or not secrets.compare_digest(expected,token):raise HTTPException(403,'Administrator token required')


def guarded(fn):
 try:return fn()
 except LookupError as exc:raise HTTPException(404,str(exc)) from exc
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.get('/catalogue')
def get_catalogue(sport:str|None=Query(default=None,max_length=60)):
 with SessionLocal.begin() as db:return cat.catalogue(db,sport)


@router.get('/categories')
def get_categories(sport:str|None=Query(default=None,max_length=60)):
 with SessionLocal.begin() as db:return cat.categories(db,sport)


@router.get('/sports/{sport_id}')
def get_sport(sport_id:str):
 with SessionLocal.begin() as db:
  sport=db.get(m.Sport,sport_id)
  return cat.catalogue(db,sport.name if sport else sport_id)


@router.get('/fixtures/{fixture_id}')
def get_fixture(fixture_id:str):
 with SessionLocal.begin() as db:return guarded(lambda:cat.fixture_view(db,fixture_id))


@router.get('/fixtures/{fixture_id}/availability')
def get_availability(fixture_id:str):
 with SessionLocal() as db:
  if db.get(m.Fixture,fixture_id) is None:raise HTTPException(404,'Fixture not found')
  return [{'bookmaker':a.bookmaker,'definition_id':a.definition_id,'line':a.line,'source_market_key':a.source_market_key,'status':a.status,
           'first_seen_at':a.first_seen_at,'last_seen_at':a.last_seen_at,'last_odds_at':a.last_odds_at,'source_id':a.source_id}
          for a in db.scalars(select(m.BookmakerMarketAvailability).where(m.BookmakerMarketAvailability.fixture_id==fixture_id))]


@router.get('/fixtures/{fixture_id}/odds')
def get_odds(fixture_id:str):
 with SessionLocal() as db:
  if db.get(m.Fixture,fixture_id) is None:raise HTTPException(404,'Fixture not found')
  rows=db.execute(select(m.Odds,m.MarketEvidence).join(m.MarketEvidence,m.MarketEvidence.odds_id==m.Odds.id,isouter=True)
                  .where(m.Odds.fixture_id==fixture_id).order_by(m.Odds.observed_at.desc()).limit(1000)).all()
  return [{'id':o.id,'bookmaker':o.bookmaker,'market_key':o.market_key,'outcome_key':o.outcome_key,'decimal_odds':float(o.decimal_odds),'observed_at':o.observed_at,
           'source_id':e.source_id if e else None,'observation_id':e.observation_id if e else None,'source_backed':e is not None} for o,e in rows]


@router.get('/fixtures/{fixture_id}/coverage')
def get_coverage(fixture_id:str):
 with SessionLocal.begin() as db:return guarded(lambda:cat.fixture_view(db,fixture_id)['coverage'])


@router.get('/fixtures/{fixture_id}/evaluations')
def get_evaluations(fixture_id:str):
 with SessionLocal() as db:
  run=cat.latest_scan(db,fixture_id)
  if run is None:return {'scan':None,'results':[]}
  results=db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id).order_by(m.MarketScanResult.rank)).all()
  return {'scan':cat.scan_dict(run),'results':[cat.result_dict(r,db.get(m.MarketDefinition,r.definition_id)) for r in results]}


@router.get('/fixtures/{fixture_id}/best-fit')
def get_best_fit(fixture_id:str,limit:int=Query(default=10,ge=1,le=50)):
 with SessionLocal() as db:
  run=cat.latest_scan(db,fixture_id)
  if run is None:return {'scan':None,'results':[],'reason':'NO_SCAN_YET'}
  results=db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id,m.MarketScanResult.decision!='UNSUPPORTED').order_by(m.MarketScanResult.rank).limit(limit)).all()
  return {'scan':cat.scan_dict(run),'results':[cat.result_dict(r,db.get(m.MarketDefinition,r.definition_id)) for r in results],
          'ranking':'Qualified first, then probability lower bound, lower-bound expected value and probability. High probability with negative EV never qualifies.'}


@router.get('/sources/health')
def get_sources_health():
 from app.modules.acquisition.source_policy import registry
 with SessionLocal() as db:return registry(db)


@router.get('/scans')
def list_scans(fixture_id:str|None=None,limit:int=Query(default=50,ge=1,le=200)):
 with SessionLocal() as db:
  query=select(m.MarketScanRun).order_by(m.MarketScanRun.started_at.desc()).limit(limit)
  if fixture_id:query=query.where(m.MarketScanRun.fixture_id==fixture_id)
  return [cat.scan_dict(r) for r in db.scalars(query)]


@router.get('/scans/{scan_id}')
def get_scan(scan_id:str):
 with SessionLocal() as db:
  run=db.get(m.MarketScanRun,scan_id)
  if run is None:raise HTTPException(404,'Scan not found')
  results=db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id).order_by(m.MarketScanResult.rank)).all()
  return {'scan':cat.scan_dict(run),'results':[cat.result_dict(r,db.get(m.MarketDefinition,r.definition_id)) for r in results]}


class ScanRequest(BaseModel):
 fixture_id:str


@router.post('/scans',status_code=201)
def post_scan(item:ScanRequest,x_admin_token:str|None=Header(default=None)):
 admin(x_admin_token)
 with SessionLocal.begin() as db:
  run=guarded(lambda:cat.scan(db,item.fixture_id,trigger='API',force=True))
  return cat.scan_dict(run)


@router.post('/sync')
def post_sync(x_admin_token:str|None=Header(default=None)):
 """Re-seed the registry and pull permitted odds now (same code paths as the autonomous cycle)."""
 admin(x_admin_token)
 from app.modules.autonomy.open_intelligence import collect_odds,enabled
 with SessionLocal.begin() as db:seeded=cat.seed(db)
 odds=collect_odds(SessionLocal) if enabled() else {'enabled':False}
 return {'seeded':seeded,'odds':odds}
