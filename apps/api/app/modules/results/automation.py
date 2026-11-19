"""Fail-closed settlement from previously ingested, authorized final-result observations."""
from datetime import datetime, timezone
from sqlalchemy import select,text
from app.db import models as m
from app.modules.results.service import validate_result_payload, settle_outcome, ResultValidationError


def validate_result_observation(observation, source, fixture):
    if not source or not source.enabled or source.permission != 'AUTHORIZED':
        raise ValueError('Source is not authorized')
    if not fixture or observation.fixture_id != fixture.id or observation.source_id != source.id:
        raise ValueError('Fixture/source mismatch')
    if not observation.observed_at or observation.observed_at.tzinfo is None:
        raise ValueError('Evidence timestamp missing timezone')
    kickoff = fixture.kickoff_at if fixture.kickoff_at.tzinfo else fixture.kickoff_at.replace(tzinfo=timezone.utc)  # stored as UTC
    if observation.observed_at < kickoff:
        raise ValueError('Final result evidence precedes kickoff')
    if observation.observed_at > datetime.now(timezone.utc):
        raise ValueError('Future result observation')
    payload=observation.payload
    if not isinstance(payload,dict) or payload.get('section')!='official_result':
        raise ValueError('Not an official result observation')
    return validate_result_payload(payload.get('data'))


def reconcile_observation(db, observation_id):
    observation=db.get(m.Observation,observation_id)
    if observation is None: raise ValueError('Unknown observation')
    source=db.get(m.Source,observation.source_id)
    fixture=db.get(m.Fixture,observation.fixture_id) if observation.fixture_id else None
    outcome=validate_result_observation(observation,source,fixture)
    if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'result:fixture:'+fixture.id})
    existing_evidence=db.scalar(select(m.ResultEvidence).where(m.ResultEvidence.observation_id==observation.id))
    if existing_evidence:
        result=db.get(m.Result,existing_evidence.result_id)
        return {'status':'REPLAYED','result_id':result.id,'version':result.version}
    latest=db.scalars(select(m.Result).where(m.Result.fixture_id==fixture.id).order_by(m.Result.version.desc()).with_for_update()).first()
    if latest and latest.outcome==outcome:
        db.add(m.ResultEvidence(result_id=latest.id,source_id=source.id,observation_id=observation.id))
        return {'status':'ALREADY_CURRENT','result_id':latest.id,'version':latest.version}
    result=m.Result(fixture_id=fixture.id,version=1+(latest.version if latest else 0),outcome=outcome,verified_at=observation.observed_at)
    db.add(result);db.flush()
    db.add(m.ResultEvidence(result_id=result.id,source_id=source.id,observation_id=observation.id))
    forecasts=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id)).all()
    counts={'WON':0,'LOST':0,'VOID':0,'PUSH':0,'UNRESOLVED':0}
    for prediction in forecasts:
        status=settle_outcome(outcome,prediction.market_key,prediction.outcome_key)
        counts[status]+=1
        db.add(m.Settlement(prediction_id=prediction.id,result_id=result.id,outcome=status))
    db.add(m.AuditEvent(actor='system:result-reconciler',action='result.automatic_reconciliation',correlation_id=result.id,payload={'observation_id':observation.id,'fixture_id':fixture.id,'version':result.version,'settlements':counts}))
    return {'status':'RECONCILED','result_id':result.id,'version':result.version,'settlements':counts}


def reconcile_pending(db,limit=100):
    if not 1<=limit<=500:raise ValueError('limit must be 1..500')
    candidates=db.scalars(select(m.Observation).where(m.Observation.payload['section'].as_string()=='official_result',~m.Observation.id.in_(select(m.ResultEvidence.observation_id))).order_by(m.Observation.observed_at.desc()).limit(5000)).all()
    report={'processed':0,'replayed':0,'rejected':0,'errors':[],'mode':'PAPER'}
    for observation in candidates[:limit]:
        try:
            with db.begin_nested():
                outcome=reconcile_observation(db,observation.id)
            report['replayed' if outcome['status'] in ('REPLAYED','ALREADY_CURRENT') else 'processed']+=1
        except (ValueError,ResultValidationError) as exc:
            report['rejected']+=1
            report['errors'].append({'observation_id':observation.id,'reason':str(exc)})
    return report
