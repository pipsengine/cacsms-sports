"""The single evidence-gated executor shared by scheduled, event and administrator entry points.

Dependency control is versioned. Each chain stage records the upstream ``output_version`` it
consumed as its ``input_version``. A stage executes only when it has not settled, was explicitly
invalidated (change event or monitor revalidation trigger), or its upstream output version moved.
Operations write idempotent receipts, so an unchanged re-execution keeps the same output version
and leaves downstream stages alone: changes invalidate only the affected calculations.
"""
import logging
from datetime import datetime,timedelta,timezone
from time import monotonic
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc
from app.modules.pipeline.operations import OPERATIONS,Waiting,receipt
from app.modules.pipeline.logic import (STAGE_KEYS,CHAIN,PRE_MATCH,BUSINESS_OUTCOMES,SETTLED,
     next_stage_key,run_status,run_outcome)
from app.modules.pipeline.events import RUNNER_FLAG

log=logging.getLogger(__name__)
PAGES={'discover':'fixtures','acquire':'browser','research':'research','analyse':'match-analysis','predict':'predictions','evaluate':'markets','qualify':'qualification','allocate':'programmes/singles','prepare':'tickets','verify':'betslip','monitor':'live-operations','reconcile':'results'}
MAX_ATTEMPTS=5
# Continuous stages: acquisition keeps queueing collection, monitoring keeps watching,
# reconciliation keeps waiting for (and re-checking) verified final results.
ALWAYS_RUN=('acquire','monitor','reconcile')


def _proof_valid(db,run,stage):
 ident=stage.output_reference or (stage.output_payload or {}).get('record_id')
 proof=db.get(m.StageRecord,ident) if ident else None
 if proof is None or proof.run_id!=run.id or proof.stage_key!=stage.stage_key:return False
 if proof.status!=('PASS' if stage.status=='VERIFIED' else stage.status):return False
 if not stage.output_reference:stage.output_reference=proof.id
 return True


def _invalidate(stage,reason):
 if stage.status=='PENDING' and not stage.next_retry_at:return
 stage.status='PENDING';stage.next_retry_at=None;stage.retry_count=0
 stage.error=reason;stage.failure_code='REVALIDATION_REQUIRED'


def _history(db,run,stage,*,started,completed,duration,attempt,failure_reason,details):
 db.add(m.PipelineStageRun(pipeline_run_id=run.id,fixture_id=run.fixture_id,stage=stage.stage_key,status=stage.status,attempt=attempt,
      input_version=stage.input_version or 0,output_version=stage.output_version or 0,started_at=started,completed_at=completed,
      duration_ms=duration,evidence_ids=list(stage.evidence_ids or []),output_reference=stage.output_reference,
      quality_score=stage.quality_score,failure_code=stage.failure_code,failure_reason=failure_reason,next_stage=stage.next_stage,details=details or {}))
 db.add(m.AuditEvent(actor='pipeline-runner',action='pipeline.stage_executed',correlation_id=run.id,
      payload={'stage':stage.stage_key,'status':stage.status,'input_version':stage.input_version,'output_version':stage.output_version,
               'output_reference':stage.output_reference,'failure_code':stage.failure_code,'error':stage.error,'attempt':attempt}))


def _settle(stage,upstream,record,status,reason,code):
 """Apply a validated output or terminal outcome receipt to the latest-state projection."""
 if record.id!=stage.output_reference:
  stage.output_version=(stage.output_version or 0)+1;stage.output_reference=record.id
 stage.input_version=upstream.output_version if upstream is not None else 0
 stage.status=status;stage.error=None if status=='VERIFIED' else reason
 stage.failure_code=None if status=='VERIFIED' else code
 stage.next_retry_at=None;stage.retry_count=0;stage.operation_key=record.operation_key
 details=record.details if isinstance(record.details,dict) else {}
 score=details.get('quality_score')
 stage.quality_score=score if isinstance(score,(int,float)) else None
 stage.next_stage=next_stage_key(stage.stage_key,status)
 stage.evidence_ids=[record.id,*record.evidence_ids]
 stage.output_payload={'decision':status,'record_id':record.id,'operation':record.kind,'verification_scope':'PAPER','details':details}


def _input_payload(run,stage,upstream):
 return {'pipeline_run_id':run.id,'fixture_id':run.fixture_id,'stage':stage.stage_key,'mode':'PAPER',
         'upstream_stage':upstream.stage_key if upstream is not None else None,
         'upstream_output_reference':upstream.output_reference if upstream is not None else None,
         'input_version':upstream.output_version if upstream is not None else 0}


def _record_outcome(db,run,stage,upstream,status,reason,code,refs,details,at):
 """Persist a derived terminal outcome (window closed / not applicable) with history."""
 before=(stage.status,stage.output_reference)
 record=receipt(db,run,stage.stage_key,'OUTCOME_'+status,refs,{'reason':reason,'failure_code':code,**details},at,status=status)
 _settle(stage,upstream,record,status,reason,code)
 stage.input_payload=_input_payload(run,stage,upstream)
 if before!=(stage.status,stage.output_reference):
  stage.started_at=at;stage.finished_at=at;stage.duration_ms=0
  _history(db,run,stage,started=at,completed=at,duration=0,attempt=1,failure_reason=reason,details=details)


def _execute(db,run,stage,upstream,at):
 started=monotonic();stage.started_at=at
 before=(stage.status,stage.output_reference,stage.failure_code,stage.error)
 attempt=stage.retry_count+1;stage.status='RUNNING'
 waiting=record=error=None
 db.info[RUNNER_FLAG]=True
 try:
  with db.begin_nested():
   try:record=OPERATIONS[stage.stage_key](db,run,at)
   except Waiting as exc:
    waiting=exc
    if exc.state in BUSINESS_OUTCOMES:
     record=receipt(db,run,stage.stage_key,'OUTCOME_'+exc.state,exc.evidence,{'reason':str(exc),'failure_code':exc.code,**exc.details},at,status=exc.state)
 except Exception as exc:
  error=exc;record=None;waiting=None
  log.exception('Pipeline stage %s failed for run %s (attempt %s)',stage.stage_key,run.id,attempt)
 finally:
  db.info.pop(RUNNER_FLAG,None)
 failure_reason=None;details={}
 if error is not None:
  stage.retry_count+=1;stage.status='FAILED' if stage.retry_count>=MAX_ATTEMPTS else 'RETRY_SCHEDULED'
  stage.next_retry_at=None if stage.status=='FAILED' else at+timedelta(seconds=min(900,30*2**(stage.retry_count-1)))
  stage.failure_code=type(error).__name__;failure_reason=(str(error) or type(error).__name__)[:500]
  stage.error=stage.failure_code+': '+failure_reason if str(error) else stage.failure_code;stage.next_stage=None
  stage.output_payload={'decision':stage.status,'failure_code':stage.failure_code,'failure_reason':failure_reason,'attempt':attempt}
  if stage.status=='FAILED':
   marker='PIPELINE_STAGE:'+run.id+':'+stage.stage_key
   if db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%'))) is None:
    db.add(m.Incident(severity='HIGH',message=marker+' '+stage.failure_code))
 elif record is not None:
  status='VERIFIED' if waiting is None else waiting.state
  _settle(stage,upstream,record,status,str(waiting) if waiting else None,waiting.code if waiting else None)
  failure_reason=str(waiting) if waiting else None;details=record.details if isinstance(record.details,dict) else {}
  for incident in db.scalars(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like('PIPELINE_STAGE:'+run.id+':'+stage.stage_key+'%'))):incident.status='RESOLVED'
 else:
  stage.status=waiting.state;stage.error=str(waiting);stage.failure_code=waiting.code;stage.next_retry_at=None
  stage.retry_count=0;stage.evidence_ids=list(waiting.evidence);stage.next_stage=None
  stage.input_version=upstream.output_version if upstream is not None else 0
  stage.output_payload={'decision':stage.status,'reason':stage.error,'failure_code':waiting.code,'details':waiting.details,'external_submission':False}
  failure_reason=str(waiting);details=waiting.details
 stage.finished_at=at;stage.duration_ms=max(0,int((monotonic()-started)*1000))
 stage.input_payload=_input_payload(run,stage,upstream)
 # Continuous stages append history only when their state changes, not on every poll.
 if stage.stage_key not in ('acquire','monitor','reconcile') or before!=(stage.status,stage.output_reference,stage.failure_code,stage.error):
  _history(db,run,stage,started=at,completed=at,duration=stage.duration_ms,attempt=attempt,failure_reason=failure_reason,details=details)
 return (record.details if record is not None and isinstance(record.details,dict) else {}) if waiting is None else waiting.details


def drive_run(db,run,*,at=None,recovery=False,invalidate_from=None):
 at=at or datetime.now(timezone.utc)
 if run.mode!='PAPER':raise PermissionError('Only PAPER-mode runs may execute')
 db.flush()  # publish any pending external changes before runner writes are suppressed
 report={'fixture_id':run.fixture_id,'actions':[],'queued_job_ids':[],'blocked':[],'outcomes':[]}
 stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id).order_by(m.PipelineStage.position).with_for_update()).all()
 if len(stages)!=12 or tuple(s.stage_key for s in stages)!=STAGE_KEYS:raise ValueError('The run must contain the twelve ordered stage records')
 by_key={s.stage_key:s for s in stages}
 fixture=db.get(m.Fixture,run.fixture_id) if run.fixture_id else None
 window_closed=fixture is not None and at>=utc(fixture.kickoff_at)
 for stage in stages:
  if stage.status in SETTLED and not _proof_valid(db,run,stage):
   _invalidate(stage,'Revalidating a completion state without a matching server receipt')
 targets=list(STAGE_KEYS) if recovery else [invalidate_from] if invalidate_from in by_key else []
 for key in targets:
  if window_closed and key in PRE_MATCH and by_key[key].status in SETTLED:continue
  _invalidate(by_key[key],'Committed input changed; revalidation required')
 for index,stage in enumerate(stages):
  key=stage.stage_key
  upstream=stages[index-1] if key in CHAIN and index>0 else None
  if window_closed and key in PRE_MATCH:
   if stage.status in SETTLED or stage.status=='FAILED':continue
   if upstream.status in BUSINESS_OUTCOMES or upstream.status=='NOT_APPLICABLE':
    _record_outcome(db,run,stage,upstream,'NOT_APPLICABLE','Upstream stage '+upstream.stage_key+' ended with '+upstream.status,'UPSTREAM_OUTCOME',
                    [upstream.output_reference] if upstream.output_reference else [],{'upstream_status':upstream.status},at)
   elif upstream.status!='FAILED':
    status='REJECTED' if stage.status=='BLOCKED' else 'INSUFFICIENT_DATA'
    _record_outcome(db,run,stage,upstream,status,'Pre-match window closed before '+key+' completed','PRE_MATCH_WINDOW_CLOSED',[],
                    {'previous_status':stage.status,'previous_reason':stage.error},at)
   continue
  stale=False
  if upstream is not None:
   if upstream.status in BUSINESS_OUTCOMES or upstream.status=='NOT_APPLICABLE':
    if stage.status!='NOT_APPLICABLE' or stage.input_version!=upstream.output_version:
     _record_outcome(db,run,stage,upstream,'NOT_APPLICABLE','Upstream stage '+upstream.stage_key+' ended with '+upstream.status,'UPSTREAM_OUTCOME',
                     [upstream.output_reference] if upstream.output_reference else [],{'upstream_status':upstream.status},at)
    continue
   if upstream.status!='VERIFIED':
    if stage.status!='PENDING' or stage.error!='Waiting for upstream stage '+upstream.stage_key:
     stage.status='PENDING';stage.next_retry_at=None;stage.next_stage=None
     stage.error='Waiting for upstream stage '+upstream.stage_key;stage.failure_code='UPSTREAM_NOT_VERIFIED'
    continue
   stale=stage.input_version!=upstream.output_version
  if stage.status in SETTLED and not stale and key not in ALWAYS_RUN:continue
  if stage.status=='FAILED':continue
  if stage.status=='RETRY_SCHEDULED' and stage.next_retry_at and utc(stage.next_retry_at)>at:continue
  details=_execute(db,run,stage,upstream,at)
  if stage.status=='VERIFIED':report['actions'].append(key+':'+(stage.output_payload or {}).get('operation',''))
  elif stage.status in BUSINESS_OUTCOMES:report['outcomes'].append(key+': '+stage.status+' - '+(stage.error or ''))
  else:report['blocked'].append(key+': '+(stage.error or stage.status))
  # Monitor revalidation triggers: re-run only the named stage on the next pass.
  for target in (details or {}).get('revalidate',[]) if key=='monitor' else []:
   if target in by_key and not (window_closed and target in PRE_MATCH):
    _invalidate(by_key[target],'Revalidation requested by continuous monitoring')
 statuses={s.stage_key:s.status for s in stages}
 run.status=run_status(statuses)
 report['queued_job_ids']=list((run.context or {}).get('queued_job_ids',[]))
 report['outcome']=run_outcome(statuses)
 run.updated_at=at;run.context={**(run.context or {}),'last_engine_report':report,'outcome':report['outcome']}
 db.flush();return report
