from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace as Obj
from app.modules.markets.service import evaluate_market
NOW=datetime(2026,11,14,8,0,tzinfo=timezone.utc)
def objects():
 r=Obj(id='r',fixture_id='f',status='VERIFIED',evidence_ids=['e'],created_at=NOW-timedelta(days=1))
 f=Obj(id='feature',research_id='r',cutoff_at=NOW-timedelta(hours=1))
 m=Obj(id='model',status='ACTIVE',validation={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True})
 p=Obj(fixture_id='f',market_key='1x2',outcome_key='home',probability=Decimal('0.65'),model_id='model',predicted_at=NOW-timedelta(minutes=30))
 o=Obj(fixture_id='f',market_key='1x2',outcome_key='home',bookmaker='example',decimal_odds=Decimal('1.80'),observed_at=NOW-timedelta(minutes=3))
 return p,o,m,f,r
def test_valid_evidence_and_value_can_qualify():
 assert evaluate_market(*objects(),now=NOW)['decision']=='QUALIFIED'
def test_stale_odds_fail_closed():
 p,o,m,f,r=objects();o.observed_at=NOW-timedelta(minutes=20)
 assert 'ODDS_STALE_OR_FUTURE' in evaluate_market(p,o,m,f,r,now=NOW)['reason_codes']
def test_unapproved_model_rejected():
 p,o,m,f,r=objects();m.status='CHALLENGER'
 assert evaluate_market(p,o,m,f,r,now=NOW)['decision']=='REJECTED'
def test_negative_value_rejected():
 p,o,m,f,r=objects();p.probability=Decimal('0.40')
 assert 'INSUFFICIENT_VALUE' in evaluate_market(p,o,m,f,r,now=NOW)['reason_codes']
def test_market_mismatch_rejected():
 p,o,m,f,r=objects();o.outcome_key='away'
 assert evaluate_market(p,o,m,f,r,now=NOW)['gates']['market_mapping']=='FAIL'
def test_missing_evidence_rejected():
 p,o,m,f,r=objects();r.evidence_ids=[]
 assert evaluate_market(p,o,m,f,r,now=NOW)['gates']['research']=='FAIL'
def test_future_features_rejected():
 p,o,m,f,r=objects();f.cutoff_at=NOW
 assert evaluate_market(p,o,m,f,r,now=NOW)['gates']['research']=='FAIL'
def test_future_odds_rejected():
 p,o,m,f,r=objects();o.observed_at=NOW+timedelta(minutes=1)
 assert evaluate_market(p,o,m,f,r,now=NOW)['gates']['odds_freshness']=='FAIL'
