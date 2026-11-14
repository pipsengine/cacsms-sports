from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from app.modules.results.automation import validate_result_observation

def record(**changes):
 fixture=SimpleNamespace(id='fx',kickoff_at=datetime.now(timezone.utc)-timedelta(hours=4))
 source=SimpleNamespace(id='src',enabled=True,permission='AUTHORIZED')
 observation=SimpleNamespace(fixture_id='fx',source_id='src',observed_at=datetime.now(timezone.utc)-timedelta(hours=1),payload={'section':'official_result','data':{'status':'FINAL','outcomes':{'1X2':{'HOME':'WON','AWAY':'LOST'}}}})
 for k,v in changes.items():setattr(observation,k,v)
 return observation,source,fixture

def test_valid_final_result():
 o,s,f=record(); assert validate_result_observation(o,s,f)['status']=='FINAL'

def test_wrong_fixture_rejected():
 o,s,f=record(fixture_id='other')
 with pytest.raises(ValueError,match='mismatch'):validate_result_observation(o,s,f)

def test_unverified_source_rejected():
 o,s,f=record();s.permission='UNKNOWN'
 with pytest.raises(ValueError,match='authorized'):validate_result_observation(o,s,f)

def test_future_evidence_rejected():
 o,s,f=record(observed_at=datetime.now(timezone.utc)+timedelta(days=1))
 with pytest.raises(ValueError,match='Future'):validate_result_observation(o,s,f)

def test_not_final_rejected():
 o,s,f=record(payload={'section':'official_result','data':{'status':'LIVE','outcomes':{'1X2':{'HOME':'WON'}}}})
 with pytest.raises(ValueError):validate_result_observation(o,s,f)

def test_other_section_rejected():
 o,s,f=record(payload={'section':'standings','data':{'status':'FINAL','outcomes':{'1X2':{'HOME':'WON'}}}})
 with pytest.raises(ValueError,match='Not an official'):validate_result_observation(o,s,f)
