"""Context-preserving read model used by every assigned sidebar workspace."""
from fastapi import APIRouter,HTTPException
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.pipeline.routes import serialize_run
router=APIRouter(prefix='/api/v1/sports/pipeline',tags=['Workflow context'])


def columns(obj):return {column.name:getattr(obj,column.name) for column in obj.__table__.columns}


def workflow_context(db,run_id=None,fixture_id=None):
 run=db.get(m.PipelineRun,run_id) if run_id else None
 if run_id and not run:raise LookupError('Pipeline run not found')
 if run:
  if fixture_id and fixture_id!=run.fixture_id:raise ValueError('Fixture and run context do not match')
  fixture_id=run.fixture_id
 if not fixture_id:raise ValueError('A fixture or run context is required')
 fixture=db.get(m.Fixture,fixture_id)
 if fixture is None:raise LookupError('Fixture not found')
 if not run:run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.fixture_id==fixture_id).order_by(m.PipelineRun.updated_at.desc()).limit(1))
 competition=db.get(m.Competition,fixture.competition_id);sport=db.get(m.Sport,competition.sport_id)
 def records(model,condition):
  query=select(model).where(condition)
  stamp=next((getattr(model,key) for key in ('created_at','observed_at','verified_at','cutoff_at') if hasattr(model,key)),None)
  if stamp is not None:query=query.order_by(stamp.desc())
  return [columns(obj) for obj in db.scalars(query.limit(100))]
 predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture_id)).all();pids=[p.id for p in predictions]
 qualifications=db.scalars(select(m.Qualification).where(m.Qualification.prediction_id.in_(pids))).all();qids=[q.id for q in qualifications]
 legs=db.scalars(select(m.TicketLeg).where(m.TicketLeg.qualification_id.in_(qids))).all();tids=list({leg.ticket_id for leg in legs})
 dossiers=db.scalars(select(m.Research).where(m.Research.fixture_id==fixture_id)).all();dids=[row.id for row in dossiers]
 operation_records=records(m.StageRecord,m.StageRecord.run_id==run.id) if run else []
 by_stage={key:[] for key in ('discover','acquire','research','analyse','predict','evaluate','qualify','allocate','prepare','verify','monitor','reconcile')}
 teams=[columns(row) for row in (db.get(m.Team,ident) for ident in (fixture.home_team_id,fixture.away_team_id) if ident) if row]
 country=db.get(m.Country,competition.country_id) if competition.country_id else None
 by_stage['discover']=[{**columns(fixture),'sport':sport.name,'competition':competition.name,'country':country.name if country else competition.country}]+teams
 by_stage['acquire']=records(m.Observation,m.Observation.fixture_id==fixture_id)+records(m.TeamStatistic,m.TeamStatistic.fixture_id==fixture_id)+records(m.AcquisitionJob,m.AcquisitionJob.fixture_id==fixture_id)+records(m.BrowserCapture,m.BrowserCapture.fixture_id==fixture_id)
 by_stage['research']=[columns(row) for row in dossiers]
 by_stage['analyse']=records(m.Feature,m.Feature.research_id.in_(dids))
 by_stage['predict']=[columns(row) for row in predictions]
 by_stage['evaluate']=records(m.Odds,m.Odds.fixture_id==fixture_id)
 by_stage['qualify']=[columns(row) for row in qualifications]
 by_stage['allocate']=records(m.StrategyRun,m.StrategyRun.result['run_id'].as_string()==run.id) if run else []
 by_stage['prepare']=records(m.Ticket,m.Ticket.id.in_(tids))
 by_stage['verify']=records(m.Betslip,m.Betslip.ticket_id.in_(tids))+records(m.TicketVerification,m.TicketVerification.ticket_id.in_(tids))
 by_stage['monitor']=[row for row in operation_records if row['stage_key']=='monitor'][:20]
 results=db.scalars(select(m.Result).where(m.Result.fixture_id==fixture_id)).all()
 by_stage['reconcile']=[columns(row) for row in results]+records(m.Settlement,m.Settlement.result_id.in_([row.id for row in results]))
 history=[columns(row) for row in db.scalars(select(m.PipelineStageRun).where(m.PipelineStageRun.pipeline_run_id==run.id).order_by(m.PipelineStageRun.started_at.desc()).limit(200))] if run else []
 return {'fixture':{**columns(fixture),'sport':sport.name,'competition':competition.name,'sport_id':sport.id},
         'run':serialize_run(db,run) if run else None,'datasets':by_stage,'operations':operation_records,'history':history}


@router.get('/context')
def context(run_id:str|None=None,fixture_id:str|None=None):
 try:
  with SessionLocal() as db:return workflow_context(db,run_id,fixture_id)
 except LookupError as exc:raise HTTPException(404,str(exc)) from exc
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
