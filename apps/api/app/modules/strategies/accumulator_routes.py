from datetime import datetime,timezone
from fastapi import APIRouter,Query
from app.db.base import SessionLocal
from app.modules.strategies import accumulator as acc, programme_engine as pe

router=APIRouter(prefix='/api/v1/sports/programmes/accumulator',tags=['Accumulator Engine'])


@router.get('/overview')
def get_overview():
 with SessionLocal() as db:return acc.overview(db)


@router.get('/configuration')
def get_configuration():return {'policy':acc.policy(),'mode':'PAPER','autonomous':True,'live_wagers_enabled':False,
                                'required_gates':list(acc.REQUIRED_GATES)+list(acc.OPTIONAL_GATES),'source':'app.modules.strategies.optimizer.PROGRAMMES'}


@router.get('/candidates')
def get_candidates():
 with SessionLocal() as db:
  rows,excluded=acc.eligible(db,datetime.now(timezone.utc));rows=pe.strip(rows)
  return {'items':rows,'excluded':excluded,'policy':acc.policy()}


@router.get('/run-history')
def get_runs(limit:int=Query(default=20,ge=1,le=200),offset:int=Query(default=0,ge=0)):
 with SessionLocal() as db:return acc.runs(db,limit,offset)


@router.get('/validation')
def get_validation():
 with SessionLocal() as db:return acc.validation(db,datetime.now(timezone.utc))


@router.get('/analytics')
def get_analytics():
 with SessionLocal() as db:return acc.analytics(db,datetime.now(timezone.utc))
