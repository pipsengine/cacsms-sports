from fastapi import APIRouter,Query
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.qualification import autonomous as aq

router=APIRouter(prefix='/api/v1/sports/qualification',tags=['Autonomous Qualification'])


@router.get('/summary')
def get_summary():
 with SessionLocal() as db:return aq.summary(db)


@router.get('/decision-details')
def get_decisions(status:str=Query(default='ALL',pattern='^(ALL|QUALIFIED|REJECTED|PENDING)$'),search:str=Query(default='',max_length=100),sport:str|None=Query(default=None,max_length=60),
                  country:str|None=Query(default=None,max_length=60),competition:str|None=Query(default=None,max_length=40),category:str|None=Query(default=None,max_length=40),
                  limit:int=Query(default=10,ge=1,le=200),offset:int=Query(default=0,ge=0)):
 with SessionLocal() as db:
  # Decisions first (newest), then forecasts still awaiting a price (by kickoff). PENDING rows are never decisions.
  decided=[] if status=='PENDING' else aq._rows(db,status,search,sport,country,competition,category)
  pending=aq.pending_rows(db,aq._now(),search,sport,country,competition,category) if status in ('ALL','PENDING') else []
  total=len(decided)+len(pending)
  page=[aq.decision_dict(db,*r) for r in decided[offset:offset+limit]]
  if len(page)<limit:page+=pending[max(0,offset-len(decided)):max(0,offset-len(decided))+limit-len(page)]
  return {'total':total,'decided':len(decided),'pending':len(pending),'limit':limit,'offset':offset,'items':page}


@router.get('/rejections')
def get_rejections():
 with SessionLocal() as db:return aq.breakdown(db)


@router.get('/gates')
def get_gates():
 with SessionLocal() as db:return aq.gate_summary(db)


@router.get('/history')
def get_history(days:int=Query(default=30,ge=1,le=365)):
 with SessionLocal() as db:return aq.history(db,days)


@router.get('/comparison')
def get_comparison(limit:int=Query(default=100,ge=1,le=500)):
 with SessionLocal.begin() as db:return aq.comparison(db,limit=limit)


@router.get('/filters')
def get_filters():
 with SessionLocal() as db:
  comps=db.execute(select(m.Competition.id,m.Competition.name,m.Competition.country,m.Sport.name).join(m.Sport,m.Sport.id==m.Competition.sport_id)
                   .join(m.Fixture,m.Fixture.competition_id==m.Competition.id).join(m.Prediction,m.Prediction.fixture_id==m.Fixture.id).distinct()).all()
  from app.modules.markets.catalogue_data import CATEGORIES
  return {'sports':sorted({s for *_,s in comps}),'countries':sorted({c for _,_,c,_ in comps if c}),'competitions':[{'id':i,'name':n,'country':c} for i,n,c,_ in comps],
          'categories':[{'key':k,'name':n} for k,n in CATEGORIES]}
