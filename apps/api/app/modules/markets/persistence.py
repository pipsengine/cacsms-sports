"""Persist immutable qualification decisions; server computes gates from stored records."""
from sqlalchemy import select
from app.db import models as m
from app.modules.markets.service import evaluate_market

def qualify_from_database(session,prediction_id,odds_id,*,now=None):
    prediction=session.get(m.Prediction,prediction_id)
    odds=session.get(m.Odds,odds_id)
    if prediction is None or odds is None:raise LookupError('Forecast or odds snapshot not found')
    model=session.get(m.ModelVersion,prediction.model_id)
    feature=session.get(m.Feature,prediction.feature_id)
    research=session.get(m.Research,feature.research_id) if feature else None
    if not all((model,feature,research)):raise LookupError('Missing linked evidence/model/feature')
    verdict=evaluate_market(prediction,odds,model,feature,research,now=now)
    from app.modules.markets.odds_intelligence import record_assessment
    quality=record_assessment(session,odds,now)
    if not quality['eligible']:
        verdict['decision']='REJECTED'
        verdict['gates']['odds_freshness']='FAIL'
        verdict['reason_codes'].extend(quality['rejection_reasons'])
    record=m.Qualification(prediction_id=prediction_id,odds_id=odds_id,gates={**verdict['gates'],'reason_codes':verdict['reason_codes'],'metrics':verdict['metrics']},decision=verdict['decision'])
    session.add(record);session.flush()
    return {'id':record.id,**verdict}
