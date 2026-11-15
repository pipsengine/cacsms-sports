"""The single evidence-gated executor shared by scheduled, event and administrator entry points."""
from datetime import datetime,timedelta,timezone
from time import monotonic
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc
from app.modules.pipeline.operations import OPERATIONS,Waiting,acquire
from app.modules.pipeline.logic import STAGES

PAGES={'discover':'fixtures','acquire':'browser','research':'research','analyse':'match-analysis','predict':'predictions','evaluate':'markets','qualify':'qualification','allocate':'programmes/singles','prepare':'tickets','verify':'betslip','monitor':'live-operations','reconcile':'results'}


def drive_run(db,run,*,at=None,recovery=False):
 at=at or datetime.now(timezone.utc)
 if run.mode!='PAPER':raise PermissionError('Only PAPER-mode runs may execute')
 report={'fixture_id':run.fixture_id,'actions':[],'queued_job_ids':[],'blocked':[]}
 stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id).order_by(m.PipelineStage.position).with_for_update()).all()
 if len(stages)!=12:raise ValueError('The run must contain exactly twelve stage records')
 for stage in stages:
  if stage.status=='VERIFIED':
   ident=(stage.output_payload or {}).get('record_id');proof=db.get(m.StageRecord,ident) if ident else None
   if proof is None or proof.run_id!=run.id or proof.stage_key!=stage.stage_key or proof.status!='PASS':
    stage.status='PENDING';stage.error='Revalidating legacy or unsupported completion state'
 fixture=db.get(m.Fixture,run.fixture_id)
 upcoming=fixture is not None and at<utc(fixture.kickoff_at)
 # Acquisition and monitoring run continuously through this same executor, never a second driver.
 if stages[1].status=='VERIFIED':stages[1].status='PENDING'
 if recovery:
  for stage in stages:
   if upcoming or stage.stage_key in ('monitor','reconcile') or stage.status!='VERIFIED':
    prior=(stage.output_payload or {}).get('record_id')
    stage.status='PENDING';stage.next_retry_at=None;stage.evidence_ids=[]
    stage.output_payload={'decision':'PENDING','previous_record_id':prior,'reason':'Committed input changed; revalidation required'}
    if stage.retry_count>=5:stage.retry_count=0
 upstream=True
 for stage in stages:
  independent=stage.stage_key=='reconcile' or stage.stage_key=='monitor' and db.scalar(select(m.StageRecord.id).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='PAPER_BETSLIPS_VERIFIED').limit(1)) is not None
  if not upstream and not independent:
   if stage.status!='VERIFIED':stage.error='Waiting for upstream verification'
   continue
  if stage.status=='VERIFIED' and stage.stage_key not in ('monitor','reconcile'):
   continue
  if stage.status=='FAILED' and not recovery:
   upstream=False;continue
  if stage.next_retry_at and utc(stage.next_retry_at)>at:
   upstream=False;continue
  start=monotonic();stage.started_at=at;stage.status='RUNNING';waiting=None;record=None
  try:
   with db.begin_nested():
    try:record=OPERATIONS[stage.stage_key](db,run,at)
    except Waiting as exc:waiting=exc
   if waiting:
    stage.status=waiting.state;stage.error=str(waiting);stage.evidence_ids=waiting.evidence
    stage.output_payload={'decision':stage.status,'reason':stage.error,'operation':stage.stage_key,'external_submission':False}
    report['blocked'].append(stage.stage_key+': '+stage.error)
   else:
    stage.status='VERIFIED';stage.error=None;stage.next_retry_at=None;stage.operation_key=record.operation_key
    stage.evidence_ids=[record.id,*record.evidence_ids]
    stage.output_payload={'decision':'VERIFIED','record_id':record.id,'operation':record.kind,'verification_scope':'PAPER','details':record.details}
    report['actions'].append(stage.stage_key+':'+record.kind)
    for incident in db.scalars(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like('PIPELINE_STAGE:'+run.id+':'+stage.stage_key+'%'))):incident.status='RESOLVED'
  except Exception as exc:
   stage.retry_count+=1;stage.status='FAILED' if stage.retry_count>=5 else 'RETRY_SCHEDULED'
   stage.next_retry_at=None if stage.status=='FAILED' else at+timedelta(seconds=min(900,30*2**(stage.retry_count-1)))
   if stage.status=='FAILED':
    marker='PIPELINE_STAGE:'+run.id+':'+stage.stage_key
    if db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%'))) is None:db.add(m.Incident(severity='HIGH',message=marker+' '+type(exc).__name__))
   stage.error=type(exc).__name__;stage.output_payload={'decision':stage.status,'error_code':type(exc).__name__,'attempt':stage.retry_count}
   report['blocked'].append(stage.stage_key+': '+stage.error)
  stage.finished_at=at;stage.duration_ms=max(0,int((monotonic()-start)*1000))
  stage.input_payload={'fixture_id':run.fixture_id,'run_id':run.id,'stage_key':stage.stage_key,'mode':'PAPER'}
  db.add(m.AuditEvent(actor='pipeline-runner',action='pipeline.stage_executed',correlation_id=run.id,
       payload={'stage':stage.stage_key,'status':stage.status,'evidence_ids':stage.evidence_ids,'error':stage.error,'attempts':stage.retry_count}))
  if stage.status!='VERIFIED':upstream=False
 run.status='COMPLETED' if all(s.status=='VERIFIED' for s in stages) else 'FAILED' if any(s.status=='FAILED' for s in stages) else 'RETRY_SCHEDULED' if any(s.status=='RETRY_SCHEDULED' for s in stages) else 'BLOCKED' if any(s.status=='BLOCKED' for s in stages) else 'MONITORING' if all(s.status=='VERIFIED' for s in stages[:11]) else 'WAITING_FOR_DATA'
 report['queued_job_ids']=list((run.context or {}).get('queued_job_ids',[]))
 run.updated_at=at;run.context={**(run.context or {}),'last_engine_report':report}
 db.flush();return report
