import pytest
from app.modules.vision.security import validate_destination
from app.modules.vision.extraction import screenshot_record,validate_vision_observation
from app.modules.governance.policy import assess_model

def public_resolver(*args,**kwargs):return [(None,None,None,None,('8.8.8.8',443))]
def private_resolver(*args,**kwargs):return [(None,None,None,None,('127.0.0.1',443))]
def test_url_allowlist():
 assert validate_destination('https://example.com/scores',['example.com'],public_resolver)
 with pytest.raises(PermissionError):validate_destination('https://bad.com',['example.com'],public_resolver)
 with pytest.raises(PermissionError):validate_destination('https://example.com',['example.com'],private_resolver)
 with pytest.raises(ValueError):validate_destination('http://example.com',['example.com'],public_resolver)
def test_screenshot_requires_real_png():
 with pytest.raises(ValueError):screenshot_record(b'not-an-image','https://example.com','f1')
 rec=screenshot_record(b'\x89PNG\r\n\x1a\n' + b'abc','https://example.com','f1')
 assert rec['verified'] is False
 with pytest.raises(ValueError):validate_vision_observation(rec)
def test_governance_fails_closed():
 assert assess_model(None,None).status=='BLOCKED'
 assert 'BRIER_DEGRADATION' in assess_model({'n':60,'brier':.15,'ece':.03},{'n':60,'brier':.20,'ece':.04}).reasons
 assert assess_model({'n':60,'brier':.15,'ece':.03},{'n':60,'brier':.16,'ece':.04}).status=='MONITORED'
