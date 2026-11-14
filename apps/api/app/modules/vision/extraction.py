"""Screenshot evidence validation. No pretend vision inference."""
from hashlib import sha256
from datetime import datetime,timezone

def screenshot_record(image:bytes,source_url:str,fixture_id:str,observed_at=None):
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Expected PNG screenshot')
    if len(image)>12_000_000:raise ValueError('Screenshot exceeds size limit')
    return {'fixture_id':fixture_id,'source_url':source_url,'sha256':sha256(image).hexdigest(),
      'bytes':len(image),'observed_at':(observed_at or datetime.now(timezone.utc)).isoformat(),
      'vision_status':'AWAITING_VERIFIED_INTERPRETATION','extracted_fields':{},'verified':False}

def validate_vision_observation(payload:dict):
    if payload.get('vision_status')!='VERIFIED' or not payload.get('reviewed_evidence_hash'):
        raise ValueError('Unverified vision output cannot enter research dossier')
    if not isinstance(payload.get('extracted_fields'),dict) or not payload['extracted_fields']:
        raise ValueError('Vision output has no extracted fields')
    return payload
