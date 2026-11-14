"""Conservative engine connector: executes existing services, never synthesizes evidence.

A run is advanced by the evidence resolver only after persisted checks succeed.
External feed acquisition is queued, not executed while holding a database lock.
"""
from datetime import timedelta
from sqlalchemy import select
from app.db import models as m
from app.modules.pipeline.logic import utcnow
from app.modules.acquisition.service import ALLOWED_SECTIONS
from app.modules.research.service import SECTIONS, build_dossier
from app.modules.acquisition.jobs import enqueue, feed_config
from app.modules.acquisition.service import build_feature_snapshot
from app.modules.markets.persistence import qualify_from_database


def connect_engines(db, run):
    """Connect acquisition, dossier, feature and market engines idempotently.

    Returns dispatchable acquisition job IDs. All other downstream services remain
    fail-closed when the required approved models, prices or verified evidence are absent.
    """
    fixture=db.get(m.Fixture,run.fixture_id) if run.fixture_id else None
    report={'fixture_id':run.fixture_id,'actions':[],'queued_job_ids':[],'blocked':[]}
    if fixture is None:
        report['blocked'].append('discover: no canonical fixture')
        return report
    if fixture.kickoff_at<=utcnow():
        # Post-event operations: acquire authorized final-result evidence; never backfill prospective forecasts.
        feeds=feed_config()
        for source in db.scalars(select(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')).all():
            if 'official_result' not in feeds.get(source.id,{}):continue
            try:
                result=enqueue(db,source.id,fixture.id,'official_result',utcnow().strftime('%Y%m%d%H'))
                if result['status'] in ('PENDING','RETRY_SCHEDULED'):report['queued_job_ids'].append(result['id'])
                report['actions'].append('official_result:'+result['status'])
            except (ValueError,PermissionError) as exc:report['blocked'].append('official_result:'+str(exc))
        from app.modules.results.automation import reconcile_pending
        report['result_reconciliation']=reconcile_pending(db,limit=100)
        return report
    observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id)).all()
    usable=[]
    for obs in observations:
        source=db.get(m.Source,obs.source_id)
        if source and source.enabled and source.permission=='AUTHORIZED' and obs.content_hash and obs.observed_at and obs.observed_at<=utcnow() and obs.payload.get('section') in SECTIONS:
            usable.append(obs)
    available={o.payload['section'] for o in usable}
    feeds=feed_config()
    for source in db.scalars(select(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')).all():
        config=feeds.get(source.id,{})
        if not isinstance(config,dict):continue
        for section in sorted((set(config)&set(ALLOWED_SECTIONS))-available):
            try:
                result=enqueue(db,source.id,fixture.id,section,utcnow().strftime('%Y%m%d%H'))
                if result['status'] in ('PENDING','RETRY_SCHEDULED'):
                    report['queued_job_ids'].append(result['id'])
                report['actions'].append('acquisition:'+section+':'+result['status'])
            except (ValueError,PermissionError) as exc:
                report['blocked'].append('acquisition:'+section+':'+str(exc))
    if not usable:
        report['blocked'].append('research: awaiting authorized observations')
        return report
    # Automatic dossiers remain PARTIAL until an independent verification step.
    existing=db.scalars(select(m.Research).where(m.Research.fixture_id==fixture.id)).all()
    latest_hashes={tuple(sorted(d.evidence_ids)) for d in existing}
    refs=sorted({o.id for o in usable})
    if tuple(refs) not in latest_hashes:
        sections={section:{'status':'PENDING','evidence_ids':[o.id for o in usable if o.payload.get('section')==section]} for section in SECTIONS}
        dossier=build_dossier(db,fixture.id,sections,refs)
        report['actions'].append('research:created_'+dossier['status'].lower())
    verified=[d for d in existing if d.status=='VERIFIED' and d.evidence_ids and set(d.evidence_ids).issubset(set(refs))]
    if not verified:
        report['blocked'].append('analyse: independently verified dossier required')
        return report
    dossier=max(verified,key=lambda d:d.version)
    features=db.scalars(select(m.Feature).where(m.Feature.research_id==dossier.id)).all()
    if not features:
        cutoff=min(utcnow(),fixture.kickoff_at-timedelta(seconds=1))
        try:
            built=build_feature_snapshot(db,research_id=dossier.id,cutoff_at=cutoff,required_sections=list(SECTIONS))
            report['actions'].append('features:materialized:'+built['id'])
        except ValueError as exc:
            report['blocked'].append('analyse:'+str(exc))
            return report
    # Produce forecasts only from explicitly approved, calibrated artifacts and verified research.
    from app.modules.prediction.prospective import infer_approved
    inference=infer_approved(db,fixture)
    report['actions'].extend('prediction:created:'+pid for pid in inference['created'])
    report['blocked'].extend('prediction:'+reason for reason in inference['blocked'])
    # Flush before downstream market qualification queries.
    db.flush()
    # No invented forecasts. Only independently approved existing predictions may be qualified.
    predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id)).all()
    odds=db.scalars(select(m.Odds).where(m.Odds.fixture_id==fixture.id)).all()
    if not predictions:
        report['blocked'].append('predict: no approved inference adapter has produced a forecast')
    if not odds:
        report['blocked'].append('evaluate: no verified bookmaker price')
    for pred in predictions:
        model=db.get(m.ModelVersion,pred.model_id)
        if not model or model.status!='ACTIVE' or model.validation.get('approved') is not True or model.validation.get('out_of_sample') is not True:
            continue
        for price in odds:
            if pred.market_key!=price.market_key or pred.outcome_key!=price.outcome_key:continue
            if price.observed_at>utcnow() or utcnow()-price.observed_at>timedelta(minutes=15):continue
            exists=db.scalar(select(m.Qualification.id).where(m.Qualification.prediction_id==pred.id,m.Qualification.odds_id==price.id))
            if exists:continue
            decision=qualify_from_database(db,pred.id,price.id)
            report['actions'].append('qualification:'+decision['decision']+':'+decision['id'])
    from app.modules.strategies.automation import allocate_paper
    allocation=allocate_paper(db,fixture_id=fixture.id)
    report['actions'].extend('paper_ticket:'+item['programme']+':'+item['ticket_id'] for item in allocation['created'])
    report['blocked'].extend('allocation:'+item['programme']+':'+item['reason'] for item in allocation['rejected'])
    from app.modules.markets.monitoring import inspect_market
    monitoring=inspect_market(db,fixture.id)
    report['market_monitor']={'snapshots':len(monitoring['snapshots']),'alerts':monitoring['alerts'],'verified_external':False}
    return report
