"""Read-only, evidence-derived orchestration. Never turns client assertions into evidence."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.db import models as m
from app.modules.pipeline.logic import STAGES, gate, utcnow


def evidence_for(db, fixture_id):
    """Resolve actual persisted records; return evidence only when cross-references agree."""
    ctx={'paper_only': True}
    if not fixture_id: return ctx
    fixture=db.get(m.Fixture,fixture_id)
    if not fixture: return ctx
    ctx['fixture_ids']=[fixture.id]
    observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture_id)).all()
    approved=[]
    for obs in observations:
        source=db.get(m.Source,obs.source_id)
        if source and source.enabled and source.permission=='AUTHORIZED' and obs.content_hash and obs.observed_at:
            approved.append(obs)
    if approved:
        ctx['authorized_source_ids']=sorted(set(o.source_id for o in approved))
        ctx['observation_ids']=[o.id for o in approved]
    dossiers=db.scalars(select(m.Research).where(m.Research.fixture_id==fixture_id).order_by(m.Research.version.desc())).all()
    dossier=next((d for d in dossiers if d.status=='VERIFIED' and d.evidence_ids and set(d.evidence_ids).issubset(set(ctx.get('observation_ids',[])))),None)
    if dossier:
        ctx['verified_dossier_ids']=[dossier.id]
        features=db.scalars(select(m.Feature).where(m.Feature.research_id==dossier.id)).all()
        valid_features=[f for f in features if f.features and f.cutoff_at <= fixture.kickoff_at and all(o.observed_at<=f.cutoff_at for o in approved if o.id in dossier.evidence_ids)]
        if valid_features:ctx['validated_feature_ids']=[f.id for f in valid_features]
    predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture_id)).all()
    valid_predictions=[]
    for pred in predictions:
        model=db.get(m.ModelVersion,pred.model_id)
        if model and model.status=='ACTIVE' and isinstance(model.validation,dict) and model.validation.get('approved') is True and model.validation.get('out_of_sample') is True and model.validation.get('calibrated') is True and model.validation.get('calibration_verified') is True and pred.feature_id in ctx.get('validated_feature_ids',[]) and 0<float(pred.probability)<1:
            valid_predictions.append(pred)
    if valid_predictions:
        ctx['approved_model_ids']=sorted(set(p.model_id for p in valid_predictions))
        ctx['prediction_ids']=[p.id for p in valid_predictions]
    odds=db.scalars(select(m.Odds).where(m.Odds.fixture_id==fixture_id)).all()
    now=utcnow()
    fresh=[o for o in odds if o.observed_at and timedelta(0)<=now-o.observed_at<=timedelta(minutes=15) and float(o.decimal_odds)>1]
    matching=[o for o in fresh if any(p.market_key==o.market_key and p.outcome_key==o.outcome_key for p in valid_predictions)]
    if matching:
        ctx['fresh_odds_ids']=[o.id for o in matching]
        ctx['matching_market_ids']=[o.id for o in matching]
    qualifications=db.scalars(select(m.Qualification)).all() if valid_predictions and matching else []
    qualifying=[q for q in qualifications if q.decision=='QUALIFIED' and q.prediction_id in ctx.get('prediction_ids',[]) and q.odds_id in ctx.get('matching_market_ids',[]) and isinstance(q.gates,dict) and all(q.gates.get(k)=='PASS' for k in ('research','model','calibration','odds_freshness','market_mapping','value'))]
    if qualifying:
        ctx['qualified_decision_ids']=[q.id for q in qualifying]
        ctx['all_mandatory_gates_passed']=True
    # Programme allocations must be backed by persisted paper ticket legs.
    legs=db.scalars(select(m.TicketLeg)).all() if qualifying else []
    tickets=[]
    for leg in legs:
        if leg.qualification_id not in ctx.get('qualified_decision_ids',[]):continue
        ticket=db.get(m.Ticket,leg.ticket_id)
        if ticket and ticket.status.startswith('PAPER') and ticket.programme_id and ticket.id not in [t.id for t in tickets]:tickets.append(ticket)
    if tickets:
        ctx['programme_allocation_ids']=[t.programme_id for t in tickets]
        ctx['verified_paper_ticket_ids']=[t.id for t in tickets]
    # Booking code is verified only when a real provider reference and evidence exist.
    codes=db.scalars(select(m.BookingCode)).all() if tickets else []
    verified_codes=[c for c in codes if c.ticket_id in ctx.get('verified_paper_ticket_ids',[]) and c.code and c.evidence_url and c.verified_at]
    if verified_codes:
        ctx['booking_provider_configured']=True
        ctx['verified_booking_code_ids']=[c.id for c in verified_codes]
    # No monitoring claim without an independently persisted monitor observation.
    # Final results can still be inspected independently, but cannot bypass earlier stages.
    results=db.scalars(select(m.Result).where(m.Result.fixture_id==fixture_id)).all()
    settlements=db.scalars(select(m.Settlement)).all() if results else []
    final=[r for r in results if r.outcome and r.verified_at and any(s.result_id==r.id and s.prediction_id in ctx.get('prediction_ids',[]) for s in settlements)]
    if final:
        ctx['official_result_final']=True
        ctx['official_result_ids']=[r.id for r in final]
        ctx['settlement_ids']=[s.id for s in settlements if s.result_id in ctx['official_result_ids']]
    return ctx


def execute_run(db, run):
    """Advance sequentially; fail closed on missing evidence, persist measured status."""
    from time import monotonic
    context=evidence_for(db,run.fixture_id)
    stages=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id).order_by(m.PipelineStage.position).with_for_update()).all()
    upstream=True
    for s in stages:
        if not upstream:
            if s.status not in ('VERIFIED','FAILED','BLOCKED','REJECTED'):
                s.status='PENDING';s.error='Waiting for upstream verification'
            continue
        if s.status in ('FAILED','BLOCKED','REJECTED','EXPIRED'):
            upstream=False;continue
        start=monotonic();s.started_at=utcnow();s.status='RUNNING'
        state,error=gate(s.stage_key,context)
        s.finished_at=utcnow();s.duration_ms=max(0,round((monotonic()-start)*1000))
        s.status=state;s.error=error
        s.input_payload={'fixture_id':run.fixture_id,'evidence_type':STAGES[s.position-1][2]}
        required={
            'discover':['fixture_ids'],'acquire':['authorized_source_ids','observation_ids'],
            'research':['verified_dossier_ids'],'analyse':['validated_feature_ids'],
            'predict':['approved_model_ids','prediction_ids'],'evaluate':['fresh_odds_ids','matching_market_ids'],
            'qualify':['qualified_decision_ids'],'allocate':['programme_allocation_ids'],
            'prepare':['verified_paper_ticket_ids'],'verify':['verified_booking_code_ids'],
            'monitor':['monitoring_evidence_ids'],'reconcile':['official_result_ids','settlement_ids']}
        s.evidence_ids=[v for key in required[s.stage_key] for v in context.get(key,[])]
        s.output_payload={'decision':state,'reason':error,'attestation':'DATABASE_VERIFIED' if state=='VERIFIED' else 'NOT_VERIFIED'}
        upstream=state=='VERIFIED'
    run.updated_at=utcnow()
    run.status='VERIFIED' if all(s.status=='VERIFIED' for s in stages) else ('BLOCKED' if any(s.status=='BLOCKED' for s in stages) else 'WAITING_FOR_DATA')
    db.add(m.AuditEvent(actor='pipeline-worker',action='pipeline.executed',correlation_id=run.id,payload={'status':run.status,'stages':{s.stage_key:s.status for s in stages}}))
    return run
