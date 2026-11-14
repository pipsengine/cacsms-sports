import pytest
from app.modules.results.service import validate_result_payload,settle_outcome,binary_scores,performance_summary,ResultValidationError

def sample():return {'status':'FINAL','outcomes':{'1X2':{'HOME':'WON','AWAY':'LOST'},'TOTAL':{'OVER_2_5':'VOID'}}}
def test_final_result_validation():assert validate_result_payload(sample())==sample()
def test_partial_reject():
 with pytest.raises(ResultValidationError):validate_result_payload({'status':'LIVE','outcomes':{'1X2':{'HOME':'WON'}}})
def test_bad_outcome_reject():
 with pytest.raises(ResultValidationError):validate_result_payload({'status':'FINAL','outcomes':{'1X2':{'HOME':'UNKNOWN'}}})
def test_settlement():
 assert settle_outcome(sample(),'1X2','HOME')=='WON'
 assert settle_outcome(sample(),'1X2','AWAY')=='LOST'
 assert settle_outcome(sample(),'TOTAL','OVER_2_5')=='VOID'
 assert settle_outcome(sample(),'CORNERS','OVER_10')=='UNRESOLVED'
def test_scores():
 assert binary_scores(.8,'WON')['brier']==.04
 assert binary_scores(.8,'LOST')['brier']==.64
 assert binary_scores(.8,'VOID') is None
def test_summary():
 s=performance_summary([(.8,'WON'),(.3,'LOST'),(.5,'UNRESOLVED')]);assert s['settled_forecasts']==2 and s['unresolved_or_void']==1 and s['status']=='INSUFFICIENT_DATA'
def test_invalid_probability():
 with pytest.raises(ResultValidationError):binary_scores(1.0,'WON')
