"""Celery worker and periodic recovery of due jobs."""
import os
from celery import Celery
from celery.schedules import crontab
from sqlalchemy import select,or_
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.acquisition.jobs import run_job,utcnow
celery_app=Celery('sports_acquisition',broker=os.getenv('REDIS_URL','redis://redis:6379/0'))
celery_app.conf.update(task_serializer='json',accept_content=['json'],result_backend=None,task_acks_late=True,worker_prefetch_multiplier=1,broker_connection_retry_on_startup=True)
celery_app.conf.beat_schedule={'recover-acquisition-jobs':{'task':'acquisition.recover','schedule':30.0},'reconcile-results':{'task':'results.reconcile','schedule':300.0},'model-governance':{'task':'models.governance','schedule':3600.0},'autonomous-cycle':{'task':'autonomy.cycle','schedule':5.0}}
@celery_app.task(name='acquisition.execute',acks_late=True)
def execute(job_id):return run_job(job_id)
@celery_app.task(name='acquisition.recover')
def recover():
    now=utcnow()
    with SessionLocal() as session:
        ids=session.scalars(select(m.AcquisitionJob.id).where(m.AcquisitionJob.attempts<m.AcquisitionJob.max_attempts,m.AcquisitionJob.next_run_at<=now,or_(m.AcquisitionJob.status.in_(['PENDING','RETRY_SCHEDULED']), (m.AcquisitionJob.status=='RUNNING') & (m.AcquisitionJob.lease_until<now))).limit(100)).all()
    for job_id in ids:execute.delay(job_id)
    return {'dispatched':len(ids)}

@celery_app.task(name='results.reconcile')
def reconcile_results():
 from app.modules.results.automation import reconcile_pending
 with SessionLocal.begin() as db:
  return reconcile_pending(db,limit=100)

@celery_app.task(name='models.governance')
def run_governance():
 from app.modules.governance.service import evaluate_models
 with SessionLocal.begin() as db:return evaluate_models(db,window=50)

@celery_app.task(name='pipeline.recheck')
def recheck_pipelines():
 from app.modules.pipeline.executor import execute_run
 with SessionLocal() as db:
  ids=db.scalars(select(m.PipelineRun.id).where(m.PipelineRun.status.in_(['PENDING','WAITING_FOR_DATA'])).order_by(m.PipelineRun.created_at).limit(50)).all()
 completed=0
 for run_id in ids:
  with SessionLocal.begin() as db:
   run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==run_id).with_for_update(skip_locked=True))
   if run:
    execute_run(db,run)
    completed+=1
 return {'processed':completed}


@celery_app.task(name='pipeline.drive')
def drive_pipelines():
 """Periodically connect engines for waiting PAPER runs; never places wagers."""
 from app.modules.pipeline.engine import connect_engines
 from app.modules.pipeline.executor import execute_run
 with SessionLocal() as db:
  ids=db.scalars(select(m.PipelineRun.id).where(m.PipelineRun.mode=='PAPER',m.PipelineRun.status.in_(['PENDING','WAITING_FOR_DATA'])).order_by(m.PipelineRun.created_at).limit(25)).all()
 processed=0;queued=[];errors=0
 for run_id in ids:
  try:
   with SessionLocal.begin() as db:
    run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.id==run_id).with_for_update(skip_locked=True))
    if not run:continue
    report=connect_engines(db,run)
    queued.extend(report['queued_job_ids'])
    processed+=1
  except Exception:
   errors+=1
 for job_id in set(queued):
  try:execute.delay(job_id)
  except Exception:errors+=1
 return {'processed':processed,'queued':len(set(queued)),'errors':errors}


@celery_app.task(name='autonomy.cycle')
def autonomous_cycle():
 from app.modules.autonomy.service import cycle
 return cycle()
