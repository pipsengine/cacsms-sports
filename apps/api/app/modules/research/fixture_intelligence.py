"""Fixtures & Competitions read model: catalogue, fixtures, pipeline progress and activity.

Every figure is counted from persisted records. Nothing is estimated, seeded or inferred from
HTTP availability: fixtures without prices, forecasts or pipeline runs are reported as such.
"""
from datetime import datetime,timedelta,timezone
from fastapi import APIRouter,HTTPException,Query
from sqlalchemy import select,func,and_,or_
from sqlalchemy.exc import SQLAlchemyError
from app.db import models as m
from app.db.base import SessionLocal
from app.modules.pipeline.logic import STAGE_KEYS,CHAIN,SETTLED,BUSINESS_OUTCOMES,STAGES
from app.modules.research.league import utc

router=APIRouter(prefix='/api/v1/sports/fixture-intelligence',tags=['Fixtures & Competitions'])
LIVE={'LIVE','IN_PLAY','IN-PLAY','INPLAY','HALFTIME','HT','1H','2H','ET','PEN'}
FINISHED={'FINAL','FINISHED','COMPLETED','FT','AET','AP'}
CANCELLED={'CANCELLED','CANCELED','ABANDONED','POSTPONED'}
STATUSES=('upcoming','live','completed','all')
NAMES=dict((key,name) for key,name,_ in STAGES)
ENGINES=(('discover','Competition Discovery & Mapping'),('acquire','Fixtures & Evidence Collection'),('research','Match Research & Enrichment'),
         ('analyse','Data Validation & Feature Quality'),('predict','Prediction Engine'),('monitor','Continuous Monitoring'))


def _scope(query,*,sport=None,country=None,competition_id=None,season_id=None):
 if sport:query=query.where(m.Sport.name==sport)
 if country:query=query.where(m.Competition.country==country)
 if competition_id:query=query.where(m.Fixture.competition_id==competition_id)
 if season_id:query=query.where(m.Fixture.season_id==season_id)
 return query


def _window(status,at,hours):
 end=at+timedelta(hours=hours);start=at-timedelta(hours=hours)
 upper=func.upper(func.coalesce(m.Fixture.status,''))
 if status=='live':return upper.in_(LIVE)
 if status=='completed':
  done=select(m.Result.fixture_id).where(m.Result.fixture_id==m.Fixture.id).exists()
  return and_(m.Fixture.kickoff_at>=start,m.Fixture.kickoff_at<at,or_(upper.in_(FINISHED),done))
 if status=='all':return and_(m.Fixture.kickoff_at>=start,m.Fixture.kickoff_at<=end)
 return and_(m.Fixture.kickoff_at>=at,m.Fixture.kickoff_at<=end,upper.notin_(LIVE|FINISHED|CANCELLED))


def _joined(*columns):
 return select(*columns).select_from(m.Fixture).join(m.Competition,m.Competition.id==m.Fixture.competition_id).join(m.Sport,m.Sport.id==m.Competition.sport_id)


def _pipeline(stages):
 by_key={s.stage_key:s.status for s in stages}
 current=next((key for key in CHAIN if by_key.get(key) not in SETTLED),None)
 if current is None:current='reconcile' if by_key.get('reconcile') not in SETTLED else None
 outcome=next((key for key in CHAIN if by_key.get(key) in BUSINESS_OUTCOMES),None)
 return {'settled':sum(by_key.get(k) in SETTLED for k in STAGE_KEYS),'current_stage':current,
         'current_status':by_key.get(current) if current else 'COMPLETED',
         'outcome_stage':outcome,'outcome':by_key.get(outcome) if outcome else None,
         'stages':[{'key':k,'status':by_key.get(k,'PENDING')} for k in STAGE_KEYS]}


def _rows(db,fixtures,at):
 ids=[f.id for f,_,_ in fixtures]
 if not ids:return []
 quotes={}
 for quote in db.scalars(select(m.Odds).where(m.Odds.fixture_id.in_(ids),m.Odds.observed_at<=at).order_by(m.Odds.observed_at.desc())):
  quotes.setdefault(quote.fixture_id,{}).setdefault((quote.bookmaker,quote.market_key,quote.outcome_key),quote)
 forecasts={}
 for prediction in db.scalars(select(m.Prediction).where(m.Prediction.fixture_id.in_(ids)).order_by(m.Prediction.predicted_at.desc())):
  forecasts.setdefault(prediction.fixture_id,prediction)
 runs={}
 for run in db.scalars(select(m.PipelineRun).where(m.PipelineRun.fixture_id.in_(ids),m.PipelineRun.mode=='PAPER').order_by(m.PipelineRun.updated_at.desc())):
  runs.setdefault(run.fixture_id,run)
 stages={}
 if runs:
  for stage in db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id.in_([r.id for r in runs.values()])).order_by(m.PipelineStage.position)):
   stages.setdefault(stage.run_id,[]).append(stage)
 results={}
 for result in db.scalars(select(m.Result).where(m.Result.fixture_id.in_(ids)).order_by(m.Result.version.desc())):
  results.setdefault(result.fixture_id,result)
 rows=[]
 for fixture,competition,sport in fixtures:
  latest=list(quotes.get(fixture.id,{}).values())
  prices=[float(q.decimal_odds) for q in latest]
  observed=max((utc(q.observed_at) for q in latest),default=None)
  prediction=forecasts.get(fixture.id);run=runs.get(fixture.id);result=results.get(fixture.id)
  markets=sorted({q.market_key for q in latest})
  rows.append({'id':fixture.id,'kickoff_at':fixture.kickoff_at,'home':fixture.home_name,'away':fixture.away_name,
   'home_team_id':fixture.home_team_id,'away_team_id':fixture.away_team_id,'status':fixture.status,
   'competition':{'id':competition.id,'name':competition.name,'country':competition.country},'sport':sport.name,
   'market_focus':prediction.market_key if prediction else (markets[0] if markets else None),
   'odds':{'min':min(prices),'max':max(prices),'quotes':len(prices),'bookmakers':len({q.bookmaker for q in latest}),
           'observed_at':observed,'fresh':bool(observed and timedelta(0)<=at-observed<=timedelta(minutes=15))} if prices else None,
   'prediction':{'id':prediction.id,'market':prediction.market_key,'outcome':prediction.outcome_key,'probability':float(prediction.probability),
                 'interval':(prediction.details or {}).get('interval')} if prediction else None,
   'pipeline':{'run_id':run.id,'status':run.status,'run_outcome':(run.context or {}).get('outcome'),**_pipeline(stages.get(run.id,[]))} if run else None,
   'result':{'id':result.id,'version':result.version,'outcome':result.outcome} if result else None})
 return rows


def overview(db,*,at=None,hours=72,sport=None,country=None,competition_id=None,season_id=None,status='upcoming',page=1,page_size=10):
 at=at or datetime.now(timezone.utc)
 if status not in STATUSES:raise ValueError('status must be one of '+', '.join(STATUSES))
 scope=dict(sport=sport,country=country,competition_id=competition_id,season_id=season_id)
 upcoming=_window('upcoming',at,hours)
 metrics={'sports':db.scalar(select(func.count()).select_from(m.Sport)) or 0,
          'competitions':db.scalar(select(func.count()).select_from(m.Competition)) or 0,
          'countries':db.scalar(select(func.count(func.distinct(m.Competition.country))).where(m.Competition.country.is_not(None))) or 0,
          'teams':db.scalar(select(func.count()).select_from(m.Team)) or 0,
          'fixtures_window':db.scalar(_joined(func.count()).where(upcoming)) or 0,
          'live_fixtures':db.scalar(_joined(func.count()).where(_window('live',at,hours))) or 0,
          'window_hours':hours}
 window_count=func.count(m.Fixture.id).filter(upcoming)
 sports=[{'id':i,'name':n,'competitions':c,'fixtures_window':w} for i,n,c,w in db.execute(
  select(m.Sport.id,m.Sport.name,func.count(func.distinct(m.Competition.id)),window_count).select_from(m.Sport)
  .outerjoin(m.Competition,m.Competition.sport_id==m.Sport.id).outerjoin(m.Fixture,m.Fixture.competition_id==m.Competition.id)
  .group_by(m.Sport.id,m.Sport.name).order_by(func.count(func.distinct(m.Competition.id)).desc(),m.Sport.name))]
 competition_query=(select(m.Competition.id,m.Competition.name,m.Competition.country,m.Sport.name,window_count,func.count(m.Fixture.id))
  .select_from(m.Competition).join(m.Sport,m.Sport.id==m.Competition.sport_id).outerjoin(m.Fixture,m.Fixture.competition_id==m.Competition.id))
 if sport:competition_query=competition_query.where(m.Sport.name==sport)
 if country:competition_query=competition_query.where(m.Competition.country==country)
 competitions=[{'id':i,'name':n,'country':c,'sport':s,'fixtures_window':w,'fixtures_total':t} for i,n,c,s,w,t in db.execute(
  competition_query.group_by(m.Competition.id,m.Competition.name,m.Competition.country,m.Sport.name).order_by(window_count.desc(),m.Competition.name).limit(300))]
 country_query=(select(m.Competition.country,func.count(func.distinct(m.Competition.id)),window_count).select_from(m.Competition)
  .join(m.Sport,m.Sport.id==m.Competition.sport_id).outerjoin(m.Fixture,m.Fixture.competition_id==m.Competition.id).where(m.Competition.country.is_not(None)))
 if sport:country_query=country_query.where(m.Sport.name==sport)
 countries=[{'name':n,'competitions':c,'fixtures_window':w} for n,c,w in db.execute(country_query.group_by(m.Competition.country).order_by(m.Competition.country))]
 listing=_scope(_joined(m.Fixture,m.Competition,m.Sport).where(_window(status,at,hours)),**scope)
 total=db.scalar(_scope(_joined(func.count()).where(_window(status,at,hours)),**scope)) or 0
 order=(m.Fixture.kickoff_at.desc(),m.Fixture.id) if status=='completed' else (m.Fixture.kickoff_at,m.Fixture.id)
 page=max(1,page);page_size=min(max(1,page_size),50)
 fixtures=db.execute(listing.order_by(*order).offset((page-1)*page_size).limit(page_size)).all()
 # Pipeline progress across every fixture in scope (planning window both sides of now).
 in_scope=_scope(_joined(m.Fixture.id).where(_window('all',at,hours)),**scope).subquery()
 counts={key:{} for key in STAGE_KEYS}
 for key,state,n in db.execute(select(m.PipelineStage.stage_key,m.PipelineStage.status,func.count()).join(m.PipelineRun,m.PipelineRun.id==m.PipelineStage.run_id)
   .where(m.PipelineRun.fixture_id.in_(select(in_scope.c.id)),m.PipelineRun.mode=='PAPER').group_by(m.PipelineStage.stage_key,m.PipelineStage.status)):
  counts.setdefault(key,{})[state]=n
 runs=db.scalar(select(func.count()).select_from(m.PipelineRun).where(m.PipelineRun.fixture_id.in_(select(in_scope.c.id)),m.PipelineRun.mode=='PAPER')) or 0
 run_states=dict(db.execute(select(m.PipelineRun.status,func.count()).where(m.PipelineRun.fixture_id.in_(select(in_scope.c.id)),m.PipelineRun.mode=='PAPER').group_by(m.PipelineRun.status)).all())
 pipeline={'runs':runs,'fixtures_in_scope':db.scalar(select(func.count()).select_from(in_scope)) or 0,'run_status':run_states,
           'stages':[{'key':key,'name':NAMES[key],'total':sum(counts[key].values()),'counts':counts[key],
                      'verified':counts[key].get('VERIFIED',0),'settled':sum(n for s,n in counts[key].items() if s in SETTLED),
                      'outcomes':sum(n for s,n in counts[key].items() if s in BUSINESS_OUTCOMES),
                      'waiting':sum(n for s,n in counts[key].items() if s in ('PENDING','WAITING_FOR_DATA','RETRY_SCHEDULED','RUNNING')),
                      'blocked':sum(n for s,n in counts[key].items() if s in ('BLOCKED','FAILED'))} for key in STAGE_KEYS]}
 dossiers=dict(db.execute(select(m.Research.status,func.count(func.distinct(m.Research.fixture_id))).where(m.Research.fixture_id.in_(select(in_scope.c.id))).group_by(m.Research.status)).all())
 coverage={'fixtures':pipeline['fixtures_in_scope'],'verified_dossiers':dossiers.get('VERIFIED',0),'partial_dossiers':dossiers.get('PARTIAL',0),
           'team_statistics':db.scalar(select(func.count()).select_from(m.TeamStatistic).where(m.TeamStatistic.fixture_id.in_(select(in_scope.c.id)))) or 0,
           'observations':db.scalar(select(func.count()).select_from(m.Observation).where(m.Observation.fixture_id.in_(select(in_scope.c.id)))) or 0}
 activity=[{'at':h.started_at,'stage':h.stage,'stage_name':NAMES.get(h.stage,h.stage),'status':h.status,'failure_code':h.failure_code,
            'fixture_id':h.fixture_id,'fixture':(f.home_name+' vs '+f.away_name) if f else None,'run_id':h.pipeline_run_id}
           for h,f in db.execute(select(m.PipelineStageRun,m.Fixture).outerjoin(m.Fixture,m.Fixture.id==m.PipelineStageRun.fixture_id)
                                 .order_by(m.PipelineStageRun.started_at.desc(),m.PipelineStageRun.id).limit(8))]
 from app.modules.autonomy.service import runtime_status
 runtime=runtime_status(db,at)
 jobs=dict(db.execute(select(m.AcquisitionJob.status,func.count()).group_by(m.AcquisitionJob.status)).all())
 sources=db.scalar(select(func.count()).select_from(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')) or 0
 by_key={s['key']:s for s in pipeline['stages']}
 engines=[]
 for key,label in ENGINES:
  stage=by_key[key]
  state='OFFLINE' if not runtime.get('worker_online') else 'ACTIVE' if stage['settled'] else 'BLOCKED' if stage['blocked'] else 'WAITING' if stage['total'] else 'IDLE'
  engines.append({'stage':key,'name':label,'state':state,'detail':f"{stage['settled']}/{stage['total']} settled" if stage['total'] else 'No runs in scope'})
 automation={'runtime':runtime,'engines':engines,'interval_seconds':runtime.get('interval_seconds'),'authorized_sources':sources,'acquisition_jobs':jobs}
 return {'updated_at':at,'mode':'PAPER','scope':{**scope,'status':status,'hours':hours},'metrics':metrics,'sports':sports,'competitions':competitions,
         'countries':countries,'fixtures':{'total':total,'page':page,'page_size':page_size,'pages':max(1,-(-total//page_size)),'rows':_rows(db,fixtures,at)},
         'pipeline':pipeline,'coverage':coverage,'activity':activity,'automation':automation}


@router.get('/overview')
def fixture_overview(hours:int=Query(72,ge=1,le=168),sport:str|None=None,country:str|None=None,competition_id:str|None=None,season_id:str|None=None,
                     status:str='upcoming',page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=50)):
 try:
  with SessionLocal() as db:
   return overview(db,hours=hours,sport=sport or None,country=country or None,competition_id=competition_id or None,season_id=season_id or None,
                   status=status.lower(),page=page,page_size=page_size)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 except SQLAlchemyError as exc:raise HTTPException(503,'Fixture database unavailable or migrations missing') from exc
