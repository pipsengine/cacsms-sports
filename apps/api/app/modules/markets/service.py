"""Evidence-first odds/forecast evaluation; no wagering or synthetic probabilities."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite

REQUIRED_GATES = ('research','model','calibration','odds_freshness','market_mapping','value')

def _utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError('Timestamp must be timezone-aware')
    return value.astimezone(timezone.utc)

def evaluate_market(prediction, odds, model, feature, research, *, now=None, max_age_seconds=900, min_edge=Decimal('0.02')):
    """Return decision + transparent evidence. Never accepts caller-supplied gate results."""
    now=_utc(now or datetime.now(timezone.utc))
    gates={k:'FAIL' for k in REQUIRED_GATES}
    reasons=[]
    def fail(key,reason):reasons.append(reason)
    same_fixture=(prediction.fixture_id==odds.fixture_id)
    same_market=(prediction.market_key==odds.market_key and prediction.outcome_key==odds.outcome_key)
    if same_fixture and same_market and odds.bookmaker and odds.market_key and odds.outcome_key:
        gates['market_mapping']='PASS'
    else:fail('market_mapping','MARKET_OR_FIXTURE_MISMATCH')
    observed=_utc(odds.observed_at)
    forecast_time=_utc(prediction.predicted_at)
    cutoff=_utc(feature.cutoff_at)
    if observed<=now and timedelta(0)<=now-observed<=timedelta(seconds=max_age_seconds):
        gates['odds_freshness']='PASS'
    else:fail('odds_freshness','ODDS_STALE_OR_FUTURE')
    if research.id==feature.research_id and research.fixture_id==prediction.fixture_id and research.status=='VERIFIED' and bool(research.evidence_ids) and cutoff<=forecast_time and _utc(research.created_at)<=forecast_time:
        gates['research']='PASS'
    else:fail('research','RESEARCH_UNVERIFIED_OR_LEAKAGE')
    validation=model.validation if isinstance(model.validation,dict) else {}
    if prediction.model_id==model.id and model.status=='ACTIVE' and validation.get('approved') is True and validation.get('out_of_sample') is True:
        gates['model']='PASS'
    else:fail('model','MODEL_NOT_INDEPENDENTLY_APPROVED')
    if gates['model']=='PASS' and validation.get('calibrated') is True and validation.get('calibration_verified') is True:
        gates['calibration']='PASS'
    else:fail('calibration','CALIBRATION_NOT_VERIFIED')
    try:
        probability=Decimal(str(prediction.probability)); price=Decimal(str(odds.decimal_odds))
        if not probability.is_finite() or not price.is_finite() or not Decimal('0')<probability<Decimal('1') or price<=1:raise ValueError()
        implied=Decimal('1')/price
        edge=probability-implied
        ev=probability*price-Decimal('1')
        if edge>=min_edge and ev>0:gates['value']='PASS'
        else:fail('value','INSUFFICIENT_VALUE')
        metrics={'probability':str(probability),'decimal_odds':str(price),'implied_probability':str(implied.quantize(Decimal('0.0000001'))),'probability_edge':str(edge.quantize(Decimal('0.0000001'))),'expected_return_per_unit':str(ev.quantize(Decimal('0.0000001')))}
    except (InvalidOperation,ValueError,TypeError):
        fail('value','INVALID_PRICE_OR_PROBABILITY');metrics={}
    return {'decision':'QUALIFIED' if all(v=='PASS' for v in gates.values()) else 'REJECTED','gates':gates,'reason_codes':reasons,'metrics':metrics,'execution_mode':'PAPER','evaluated_at':now.isoformat()}
