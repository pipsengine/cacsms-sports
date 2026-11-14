"""Capture -> vision inference -> explicit independent evidence review -> dossier.
This pipeline does not generate probabilities or claim screenshot text is verified truth.
"""
import hashlib,os
from pathlib import Path
from sqlalchemy import select
from app.db import models as m
from app.modules.vision.provider import infer_screenshot
from app.modules.research.service import build_dossier,SECTIONS

async def interpret_capture(db,capture_id:str):
    row=db.get(m.BrowserCapture,capture_id)
    if row is None:raise ValueError('Unknown browser capture')
    if row.status!='CAPTURED' or not row.evidence_hash:raise ValueError('Capture is not complete')
    source=db.get(m.Source,row.source_id)
    if source is None or not source.enabled or source.permission!='AUTHORIZED':raise PermissionError('Source is not authorized')
    root=Path(os.getenv('SPORTS_EVIDENCE_ROOT','/tmp/cacsms-evidence')).resolve()
    image=(root/(row.evidence_hash+'.png')).read_bytes()
    if hashlib.sha256(image).hexdigest()!=row.evidence_hash:raise ValueError('Screenshot hash mismatch')
    result=await infer_screenshot(image,row.fixture_id,row.url)
    row.vision_status='EXTRACTED_UNVERIFIED'
    row.error=None
    db.add(m.AuditEvent(actor='vision',action='vision.inferred_unverified',correlation_id=row.id,payload={'evidence_sha256':row.evidence_hash,'observation_count':len(result['observations'])}))
    db.flush()
    return result

def review_observations(db,capture_id:str,extracted:dict,reviewed_sections:list[str],reviewer:str):
    """Explicit human/independent-source review is required; a model cannot self-verify."""
    row=db.get(m.BrowserCapture,capture_id)
    if row is None or row.vision_status!='EXTRACTED_UNVERIFIED':raise ValueError('Inference must run first')
    if extracted.get('evidence_sha256')!=row.evidence_hash or extracted.get('fixture_id')!=row.fixture_id:raise ValueError('Evidence mismatch')
    if not reviewer or reviewer=='vision':raise ValueError('Independent reviewer identity required')
    if not reviewed_sections or not set(reviewed_sections)<=set(SECTIONS):raise ValueError('Invalid reviewed sections')
    evidence_ids=[];sections={}
    for section in reviewed_sections:
        values=[x for x in extracted.get('observations',[]) if x['section']==section]
        if not values:raise ValueError('Cannot verify absent observation')
        digest=hashlib.sha256((row.evidence_hash+section+str(values)).encode()).hexdigest()
        record=db.scalar(select(m.Observation).where(m.Observation.source_id==row.source_id,m.Observation.content_hash==digest))
        if record is None:
            record=m.Observation(source_id=row.source_id,fixture_id=row.fixture_id,source_url=row.url,content_hash=digest,payload={'screenshot_hash':row.evidence_hash,'section':section,'values':values,'reviewer':reviewer,'verification':'INDEPENDENT_REVIEW'})
            db.add(record);db.flush()
        evidence_ids.append(record.id)
        sections[section]={'status':'VERIFIED','evidence_ids':[record.id],'details':{'reviewer':reviewer}}
    dossier=build_dossier(db,row.fixture_id,sections,evidence_ids)
    row.vision_status='PARTIALLY_VERIFIED' if len(reviewed_sections)<len(SECTIONS) else 'VERIFIED'
    db.add(m.AuditEvent(actor=reviewer,action='vision.review',correlation_id=row.id,payload={'sections':reviewed_sections,'dossier_id':dossier['id']}))
    return dossier
