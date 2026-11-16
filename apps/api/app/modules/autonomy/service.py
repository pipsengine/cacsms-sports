"""Persistent, leased background controller. It operates without dashboard clients."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from sqlalchemy import select,func,or_,case
from sqlalchemy.exc import IntegrityError
from app.db import models as m
from app.db.base import SessionLocal
from app.modules.pipeline.logic import STAGES,earliest
from app.modules.research.league import utc
from app.modules.prediction.prospective import REQUIRED_APPROVALS

RUNTIME_ID='paper-autonomy'
INTERVAL=30
LEASE_SECONDS=300


def now():return datetime.now(timezone.utc)


def claim(factory=SessionLocal,at=None,force=False):
 at=at or now()
 with factory.begin() as db:
  row=db.scalar(select(m.AutonomousRuntime).where(m.AutonomousRuntime.id==RUNTIME_ID).with_for_update())
  if row is None:
   try:
    with db.begin_nested():
     row=m.AutonomousRuntime(id=RUNTIME_ID,status='STARTING',report={});db.add(row);db.flush()
   except IntegrityError:
    row=db.scalar(select(m.AutonomousRuntime).where(m.AutonomousRuntime.id==RUNTIME_ID).with_for_update())
  if row.lease_until and utc(row.lease_until)>at:return None
  if not force and row.next_run_at and utc(row.next_run_at)>at:return None
  token=str(uuid4());row.owner=token;row.status='RUNNING';row.started_at=at
  row.lease_until=at+timedelta(seconds=LEASE_SECONDS);row.next_run_at=at+timedelta(seconds=INTERVAL)
  return token


def finish(factory,token,report,error=False,at=None):
 at=at or now()
 with factory.begin() as db:
  row=db.scalar(select(m.AutonomousRuntime).where(m.AutonomousRuntime.id==RUNTIME_ID).with_for_update())
  if row is None or row.owner!=token:return False
  previous=row.status
  row.report=report;row.finished_at=at;row.lease_until=None;row.owner=None;row.cycles+=1
  row.consecutive_errors=row.consecutive_errors+1 if error else 0
  if not error:row.last_success_at=at
  row.status='DEGRADED' if error or report.get('errors') else 'WAITING_FOR_DATA' if report.get('blockers') else 'OPERATING'
  row.next_run_at=at+timedelta(seconds=min(300,INTERVAL*2**min(row.consecutive_errors,3)))
  if previous!=row.status or report.get('errors'):
   db.add(m.AuditEvent(actor='autonomous-controller',action='autonomy.cycle_finished',correlation_id=m.uid(),
      payload={'status':row.status,'created_runs':report.get('created_runs',0),'processed_runs':report.get('processed_runs',0),'errors':report.get('errors',[]),'blockers':report.get('blockers',[])[:6]}))
  return True


def create_runs(db,at):
 fixtures=db.scalars(select(m.Fixture).where(m.Fixture.kickoff_at>=at-timedelta(days=2),m.Fixture.kickoff_at<=at+timedelta(hours=168),
                     m.Fixture.status.notin_(['CANCELLED','CANCELED','ABANDONED']),
                     ~m.Fixture.id.in_(select(m.PipelineRun.fixture_id).where(m.PipelineRun.fixture_id.is_not(None),m.PipelineRun.mode=='PAPER')))
                     .order_by(m.Fixture.kickoff_at,m.Fixture.id).limit(500)).all()
 created=[]
 for fixture in fixtures:
  key='autonomous:fixture:'+fixture.id
  if db.scalar(select(m.PipelineRun.id).where(m.PipelineRun.idempotency_key==key)):continue
  run=m.PipelineRun(idempotency_key=key,fixture_id=fixture.id,mode='PAPER',status='PENDING',context={'autonomous':True})
  db.add(run);db.flush()
  for i,(key,_,_) in enumerate(STAGES,1):
   db.add(m.PipelineStage(run_id=run.id,position=i,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=[]))
  created.append(run.id)
 return created


def cycle(factory=SessionLocal,fetcher=None):
 from app.modules.pipeline.events import publish_configuration
 publish_configuration(factory)
 with factory() as check:
  has_events=check.scalar(select(m.PipelineEvent.id).where(m.PipelineEvent.available_at<=now(),or_(m.PipelineEvent.status.in_(['PENDING','RETRY_SCHEDULED']), (m.PipelineEvent.status=='PROCESSING') & (m.PipelineEvent.lease_until<now()))).limit(1)) is not None
 token=claim(factory,force=has_events)
 if token is None:return {'status':'NOT_DUE_OR_ALREADY_RUNNING'}
 report={'created_runs':0,'processed_runs':0,'queued_jobs':0,'blockers':[],'errors':[],'consumed_events':0}
 event_ids=[];event_fixtures=set();global_event=False;target_ids=set();processed_ids=set();failed_ids=set();plan={}
 try:
  from app.modules.autonomy.openligadb import collect as collect_open_data
  report['open_data']=collect_open_data(factory)
  report['errors'].extend(report['open_data']['errors'])
  from app.modules.standings.service import collect as collect_standings
  report['standings']=collect_standings(factory)
  report['errors'].extend(report['standings']['errors'])
  from app.modules.acquisition.source_policy import register_prohibited_sources
  with factory.begin() as db:report['prohibited_sources_recorded']=register_prohibited_sources(db)
  from app.modules.autonomy.open_intelligence import collect as collect_intelligence
  report['open_intelligence']=collect_intelligence(factory)
  report['errors'].extend(report['open_intelligence'].get('errors',[]))
  from app.modules.autonomy.discovery import collect
  discovery=collect(factory,**({'fetcher':fetcher} if fetcher is not None else {}))
  report['discovery']=discovery
  report['errors'].extend(discovery['errors'])
  with factory.begin() as db:
   report['created_runs']=len(create_runs(db,now()))
   events=db.scalars(select(m.PipelineEvent).where(m.PipelineEvent.available_at<=now(),or_(m.PipelineEvent.status.in_(['PENDING','RETRY_SCHEDULED']), (m.PipelineEvent.status=='PROCESSING') & (m.PipelineEvent.lease_until<now()))).order_by(m.PipelineEvent.created_at).limit(500).with_for_update(skip_locked=True)).all()
   for event in events:
    event.status='PROCESSING';event.attempts+=1;event.lease_until=now()+timedelta(seconds=LEASE_SECONDS)
    event_ids.append(event.id)
    if event.fixture_id:event_fixtures.add(event.fixture_id)
    else:global_event=True
    remaining=event.payload.get('remaining_run_ids')
    if remaining is None:
     query=select(m.PipelineRun.id)
     if event.fixture_id:query=query.where(m.PipelineRun.fixture_id==event.fixture_id)
     else:
      query=query.where(m.PipelineRun.status!='COMPLETED')
      if event.payload.get('competition_id'):
       query=query.where(m.PipelineRun.fixture_id.in_(select(m.Fixture.id).where(m.Fixture.competition_id==event.payload['competition_id'])))
     remaining=list(db.scalars(query))
     event.payload={**event.payload,'remaining_run_ids':remaining}
    target_ids.update(remaining)
    # Each change names the earliest stage it can affect; only that stage is invalidated.
    stage=event.payload.get('invalidate_from') or 'discover'
    for ident in remaining:plan[ident]=earliest([plan.get(ident),stage])
   sources=db.scalar(select(func.count()).select_from(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')) or 0
   fixtures=db.scalar(select(func.count()).select_from(m.Fixture)) or 0
   models=db.scalars(select(m.ModelVersion).where(m.ModelVersion.status=='ACTIVE')).all()
   if not sources:report['blockers'].append('No enabled authorized sports data source is registered')
   if not fixtures and not discovery['configured_feeds']:report['blockers'].append('No fixture discovery feed is configured and no fixtures are stored')
   elif not fixtures:report['blockers'].append('Waiting for real fixtures from configured sources')
   if not any(isinstance(model.validation,dict) and all(model.validation.get(k) is True for k in REQUIRED_APPROVALS) for model in models):
    report['blockers'].append('No independently approved and calibrated active prediction model')
   # Revisit oldest-updated work first so waiting runs cannot starve newer fixtures.
   ids=db.scalars(select(m.PipelineRun.id).where(m.PipelineRun.mode=='PAPER',or_(m.PipelineRun.status.in_(['PENDING','WAITING_FOR_DATA','RETRY_SCHEDULED','MONITORING','BLOCKED']),m.PipelineRun.id.in_(target_ids)))
      .order_by(case((m.PipelineRun.id.in_(target_ids),0),else_=1),m.PipelineRun.updated_at,m.PipelineRun.id).limit(25)).all()
  jobs=set()
  from app.modules.pipeline.runner import drive_run
  for ident in ids:
   try:
    with factory.begin() as db:
     run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==ident).with_for_update(skip_locked=True))
     if run is None:continue
     detail=drive_run(db,run,invalidate_from=plan.get(run.id))
     run.context={**(run.context or {}),'last_engine_report':detail}
     jobs.update(detail['queued_job_ids']);report['processed_runs']+=1;processed_ids.add(run.id)
     report['blockers'].extend(detail['blocked'])
   except Exception as exc:
    failed_ids.add(ident);report['errors'].append({'run_id':ident,'code':type(exc).__name__})
  with factory.begin() as db:
   for event in db.scalars(select(m.PipelineEvent).where(m.PipelineEvent.id.in_(event_ids))):
    remaining=set(event.payload.get('remaining_run_ids',[]))-processed_ids
    event.payload={**event.payload,'remaining_run_ids':sorted(remaining)}
    failed=bool(remaining & failed_ids)
    if remaining and not failed:
     event.status='PENDING';event.lease_until=None;event.attempts=max(0,event.attempts-1);event.available_at=now()+timedelta(seconds=5);continue
    event.status=('DEAD' if event.attempts>=5 else 'RETRY_SCHEDULED') if failed else 'DONE'
    event.error_code='PIPELINE_EXECUTION_ERROR' if failed else None;event.lease_until=None
    event.available_at=now()+timedelta(seconds=min(900,30*2**min(event.attempts,5)))
    if not failed:event.completed_at=now();report['consumed_events']+=1
  report['queued_jobs']=len(jobs)
  # Dispatch durable jobs only after database transactions have committed.
  from app.modules.acquisition.tasks import execute
  for ident in sorted(jobs):
   try:execute.delay(ident)
   except Exception as exc:report['errors'].append({'job_id':ident,'code':type(exc).__name__})
  report['blockers']=list(dict.fromkeys(report['blockers']))[:20];report['errors']=report['errors'][:25]
  finish(factory,token,report)
  return report
 except Exception as exc:
  report['errors'].append({'code':type(exc).__name__})
  finish(factory,token,report,error=True)
  return report


def runtime_status(db,at=None):
 at=at or now()
 row=db.get(m.AutonomousRuntime,RUNTIME_ID)
 if row is None:return {'status':'NOT_STARTED','worker_online':False,'interval_seconds':INTERVAL,'report':{'blockers':['Background controller has not reported a cycle']}}
 heartbeat=row.started_at if row.status=='RUNNING' else row.finished_at
 online=heartbeat is not None and 0<=(at-utc(heartbeat)).total_seconds()<=180
 return dict(status=row.status if online else 'OFFLINE',worker_online=online,interval_seconds=INTERVAL,cycles=row.cycles,
             started_at=row.started_at,finished_at=row.finished_at,last_success_at=row.last_success_at,
             next_run_at=row.next_run_at,consecutive_errors=row.consecutive_errors,report=row.report)
