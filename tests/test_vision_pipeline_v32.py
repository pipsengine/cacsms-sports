import hashlib,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.vision.provider import validate_inference
PNG=b'\x89PNG\r\n\x1a\n'+b'valid-image-content'
H=hashlib.sha256(PNG).hexdigest()
def payload():return {'evidence_sha256':H,'fixture_id':'f1','source_url':'https://example.org/game','observations':[{'section':'standings','value':'2','visible_text':'Position 2'}]}
def test_valid_output_is_unverified():
 r=validate_inference(payload(),PNG,'f1','https://example.org/game');assert r['status']=='EXTRACTED_UNVERIFIED' and r['requires_independent_verification']
def test_hash_mismatch():
 d=payload();d['evidence_sha256']='0'*64
 with pytest.raises(ValueError):validate_inference(d,PNG,'f1','https://example.org/game')
def test_fixture_mismatch():
 with pytest.raises(ValueError):validate_inference(payload(),PNG,'f2','https://example.org/game')
def test_missing_visible_text():
 d=payload();del d['observations'][0]['visible_text']
 with pytest.raises(ValueError):validate_inference(d,PNG,'f1','https://example.org/game')
def test_unknown_section():
 d=payload();d['observations'][0]['section']='guaranteed_winner'
 with pytest.raises(ValueError):validate_inference(d,PNG,'f1','https://example.org/game')
