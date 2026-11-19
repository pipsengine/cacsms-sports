from fastapi import APIRouter,Query
from datetime import timedelta
from sqlalchemy import select,func
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
                  limit:int=Query(default=10,ge=1,le=200),offset:int=Query(default=0,ge=0),group:str|None=Query(default=None,pattern='^fixture$')):
 with SessionLocal() as db:
  # Decisions first (newest), then forecasts still awaiting a price (by kickoff). PENDING rows are never decisions.
  decided=[] if status=='PENDING' else aq._rows(db,status,search,sport,country,competition,category)
  pending=aq.pending_rows(db,aq._now(),search,sport,country,competition,category) if status in ('ALL','PENDING') else []
  if group=='fixture':return grouped(db,decided,pending,limit,offset)
  total=len(decided)+len(pending)
  page=[aq.decision_dict(db,*r) for r in decided[offset:offset+limit]]
  if len(page)<limit:page+=pending[max(0,offset-len(decided)):max(0,offset-len(decided))+limit-len(page)]
  return {'total':total,'decided':len(decided),'pending':len(pending),'limit':limit,'offset':offset,'items':page}


def best_selection(items):
 """Headline selection for a fixture: qualified first, then highest edge, then highest model probability."""
 return max(items,key=lambda d:(d['decision']=='QUALIFIED',d.get('edge') is not None,d.get('edge') or 0,d.get('probability') or 0))


REASON_TEXT={'DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE':'Did not beat the base-rate forecast on held-out matches',
             'CALIBRATION_ERROR_TOO_HIGH':'Calibration error above the allowed limit',
             'OUTCOME_NEVER_OR_ALWAYS_OCCURS_IN_TRAINING':'Outcome never or always occurred in training'}


def not_forecast(db,fixture_id,forecast_keys,cache):
 """Outcomes the active market model validated but did NOT approve, so no probability is published for them.
 Correct-score lines are summarised by the approved ones; only named markets are listed."""
 from app.modules.prediction.market_model import active_model
 from app.modules.market_scanner.service import market_name,selection_name
 fixture=db.get(m.Fixture,fixture_id);comp=db.get(m.Competition,fixture.competition_id) if fixture else None
 if comp is None:return []
 if comp.id not in cache:
  model=active_model(db,comp.sport_id,comp.id);rows=[]
  for key,v in sorted(((model.validation or {}).get('markets') or {}).items()) if model else ():
   market,outcome=key.split('|',1)
   if v.get('approved') or market=='CS':continue
   rows.append({'id':'not-forecast:'+key,'market_key':market,'outcome_key':outcome,'market':market_name(market),'selection':selection_name(market,outcome),
                'decision':'NOT_FORECAST','skill':round(v['skill']*100,2) if isinstance(v.get('skill'),(int,float)) else None,
                'calibration_error':v.get('calibration_error'),'reason_codes':v.get('reasons') or [],
                'reasons':[REASON_TEXT.get(r,r.replace('_',' ').lower()) for r in v.get('reasons') or []],
                'model':model.name,'model_version':model.version})
  cache[comp.id]=rows
 return [r for r in cache[comp.id] if r['market_key'] not in forecast_keys]


def grouped(db,decided,pending,limit,offset):
 """Page by fixture (order of each fixture's first row), so one fixture never splits across pages."""
 order,members={},{}
 for row in decided:
  members.setdefault(row[3].id,[]).append(row);order.setdefault(row[3].id,len(order))
 for row in pending:
  members.setdefault(row['fixture_id'],[]).append(row);order.setdefault(row['fixture_id'],len(order))
 fixture_ids=sorted(order,key=order.get)
 groups=[];models={}
 for fixture_id in fixture_ids[offset:offset+limit]:
  items=[row if isinstance(row,dict) else aq.decision_dict(db,*row) for row in members[fixture_id]]
  counts={k:sum(d['decision']==k for d in items) for k in ('QUALIFIED','REJECTED','PENDING')}
  head=items[0]
  unavailable=not_forecast(db,fixture_id,{d['market_key'] for d in items},models)
  groups.append({'fixture_id':fixture_id,'fixture':head['fixture'],'sport':head['sport'],'competition':head['competition'],'country':head['country'],
                 'kickoff_at':head['kickoff_at'],'markets':len(items),'qualified':counts['QUALIFIED'],'rejected':counts['REJECTED'],'pending':counts['PENDING'],
                 'best':best_selection(items),'items':items,'not_forecast':unavailable})
 return {'total':len(fixture_ids),'decisions':len(decided)+len(pending),'decided':len(decided),'pending':len(pending),'limit':limit,'offset':offset,'groups':groups}


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
  # Every competition with upcoming fixtures, so countries without forecasts are visible (with the reason) rather than missing.
  at=aq._now()
  upcoming=db.execute(select(m.Competition.id,m.Competition.name,m.Competition.country,m.Sport.name,func.count(func.distinct(m.Fixture.id)),
                             func.count(func.distinct(m.Prediction.fixture_id)),func.count(func.distinct(m.Research.fixture_id)))
                      .join(m.Sport,m.Sport.id==m.Competition.sport_id).join(m.Fixture,m.Fixture.competition_id==m.Competition.id)
                      .outerjoin(m.Prediction,m.Prediction.fixture_id==m.Fixture.id)
                      .outerjoin(m.Research,(m.Research.fixture_id==m.Fixture.id)&(m.Research.status=='VERIFIED'))
                      .where(m.Fixture.kickoff_at>at,m.Fixture.kickoff_at<=at+timedelta(days=7),
                             m.Fixture.status.notin_(('FINISHED','CANCELLED','CANCELED','ABANDONED','POSTPONED')))
                      .group_by(m.Competition.id,m.Competition.name,m.Competition.country,m.Sport.name)).all()
  stats={}
  for cid,name,country,sport,fixtures,forecasts,verified in upcoming:
   stats[cid]={'id':cid,'name':name,'country':country,'sport':sport,'fixtures':fixtures,'forecast_fixtures':forecasts,'verified_research':verified}
  # Competitions with stored decisions but no fixture in the next 7 days stay filterable.
  for i,n,c,s in comps:stats.setdefault(i,{'id':i,'name':n,'country':c,'sport':s,'fixtures':0,'forecast_fixtures':0,'verified_research':0})
  by_country={}
  for row in stats.values():
   key=row['country'] or 'Unspecified';agg=by_country.setdefault(key,{'country':key,'fixtures':0,'forecast_fixtures':0,'verified_research':0,'competitions':0})
   agg['fixtures']+=row['fixtures'];agg['forecast_fixtures']+=row['forecast_fixtures'];agg['verified_research']+=row['verified_research'];agg['competitions']+=1
  countries=sorted(by_country.values(),key=lambda r:(-r['forecast_fixtures'],-r['fixtures'],r['country']))
  return {'sports':sorted({r['sport'] for r in stats.values()}),'countries':[r['country'] for r in countries],'country_stats':countries,
          'competitions':sorted(stats.values(),key=lambda r:(-r['forecast_fixtures'],-r['fixtures'],r['name'])),
          'categories':[{'key':k,'name':n} for k,n in CATEGORIES],
          'coverage_note':'Forecasts need verified research: two independent result sources must agree for the competition.'}


@router.get('/opportunities')
def get_opportunities(only_qualified:bool=True,min_probability:float|None=Query(default=None,ge=0,le=100),min_ev:float|None=Query(default=None,ge=-100,le=1000),
                      search:str=Query(default='',max_length=100),sport:str|None=Query(default=None,max_length=60),country:str|None=Query(default=None,max_length=60),
                      competition:str|None=Query(default=None,max_length=40),category:str|None=Query(default=None,max_length=40),
                      limit:int=Query(default=5,ge=1,le=200),offset:int=Query(default=0,ge=0)):
 from app.modules.qualification.opportunities import opportunities
 with SessionLocal() as db:
  rows=opportunities(db,only_qualified,min_probability,min_ev,search,sport,country,competition,category)
  return {'total':len(rows),'limit':limit,'offset':offset,'items':rows[offset:offset+limit]}


@router.get('/opportunities/{opportunity_id}/evidence')
def get_opportunity_evidence(opportunity_id:str):
 from fastapi import HTTPException
 from app.modules.qualification.opportunities import evidence
 with SessionLocal() as db:
  try:return evidence(db,opportunity_id)
  except LookupError as exc:raise HTTPException(404,str(exc)) from exc
