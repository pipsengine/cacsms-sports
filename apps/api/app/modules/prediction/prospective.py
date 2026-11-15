"""Fail-closed prospective inference from independently approved model artifacts."""
from datetime import datetime, timezone
from app.modules.prediction.service import predict_from_artifact, FEATURE_NAMES
from app.modules.research.league import utc

REQUIRED_APPROVALS = ('approved','out_of_sample','calibrated','calibration_verified')

def eligible(model, feature, dossier, fixture, now):
    if not model or not feature or not dossier or not fixture:
        return False, 'Missing model, feature, research, or fixture'
    if model.status != 'ACTIVE' or not isinstance(model.validation, dict) or any(model.validation.get(k) is not True for k in REQUIRED_APPROVALS):
        return False, 'Independent active-model approval and calibration verification required'
    if model.sport_id != fixture.sport_id or dossier.status != 'VERIFIED' or feature.research_id != dossier.id or dossier.fixture_id != fixture.id:
        return False, 'Sport, fixture, research or feature provenance mismatch'
    if not fixture.kickoff_at or not feature.cutoff_at or not utc(feature.cutoff_at) < utc(fixture.kickoff_at) or not now < utc(fixture.kickoff_at):
        return False, 'Prospective cutoff or kickoff invalid'
    if not isinstance(feature.features,dict) or set(feature.features.get('numeric_features',{})) != set(FEATURE_NAMES):
        return False, 'Sport-specific numeric feature contract unavailable'
    return True, None

def infer_approved(db, fixture, now=None, dossier_id=None):
    """Persist only authorized binary home-win forecasts, idempotently. No fabricated models."""
    from sqlalchemy import select
    from app.db import models as m
    now=now or datetime.now(timezone.utc)
    report={'created':[], 'existing':[], 'blocked':[]}
    dossiers=db.scalars(select(m.Research).where(m.Research.fixture_id==fixture.id,m.Research.status=='VERIFIED')).all()
    if dossier_id is not None:dossiers=[row for row in dossiers if row.id==dossier_id]
    models=db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==fixture.sport_id,m.ModelVersion.status=='ACTIVE')).all()
    if not dossiers or not models:
        report['blocked'].append('Verified dossier and independently approved active model required')
        return report
    for dossier in dossiers:
        features=db.scalars(select(m.Feature).where(m.Feature.research_id==dossier.id)).all()
        for feature in features:
            for model in models:
                ok,reason=eligible(model,feature,dossier,fixture,now)
                if not ok:
                    report['blocked'].append(reason);continue
                market='1X2';outcome='HOME'
                prior=db.scalar(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id,m.Prediction.feature_id==feature.id,m.Prediction.model_id==model.id,m.Prediction.market_key==market,m.Prediction.outcome_key==outcome))
                if prior:
                    report['existing'].append(prior.id);continue
                try:
                    probability=predict_from_artifact(model.validation,feature.features['numeric_features'])
                except (KeyError,ValueError,TypeError,OverflowError,ZeroDivisionError) as exc:
                    report['blocked'].append('Invalid approved model artifact: '+str(exc));continue
                if not 0 < probability < 1:
                    report['blocked'].append('Probability out of bounds');continue
                prediction=m.Prediction(fixture_id=fixture.id,feature_id=feature.id,model_id=model.id,market_key=market,outcome_key=outcome,probability=probability,predicted_at=now)
                db.add(prediction);db.flush();report['created'].append(prediction.id)
                db.add(m.AuditEvent(actor='pipeline-inference',action='prediction.prospective_created',correlation_id=fixture.id,payload={'prediction_id':prediction.id,'model_id':model.id,'feature_id':feature.id,'market_key':market,'outcome_key':outcome,'paper_only':True}))
    return report
