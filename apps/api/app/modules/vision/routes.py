"""Read-only vision session API and restricted admin capture."""
import os, secrets
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.vision.browser import capture
router=APIRouter(prefix='/api/v1/sports',tags=['Browser evidence'])
class CaptureRequest(BaseModel):
 fixture_id:str
 source_id:str
 url:str=Field(max_length=2000)


@router.get('/browser/overview')
def browser_overview():
 from app.modules.vision import browser_intelligence as bi
 with SessionLocal() as db:return bi.overview(db)


@router.get('/browser/sessions')
def browser_sessions():
 from app.modules.vision import browser_intelligence as bi
 with SessionLocal() as db:return bi.sessions(db)


@router.get('/browser/summary')
def browser_summary():
 from app.modules.vision import browser_intelligence as bi
 with SessionLocal() as db:return bi.summary(db)


@router.post('/admin/browser/capture',status_code=201)
async def capture_admin(item:CaptureRequest,x_admin_token:str|None=Header(default=None)):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not x_admin_token or not secrets.compare_digest(expected,x_admin_token):raise HTTPException(403,'Administrator token required')
 with SessionLocal() as db:
  source=db.get(m.Source,item.source_id)
  if not source or not source.enabled or source.permission!='AUTHORIZED':raise HTTPException(422,'Source must be explicitly authorized and enabled')
  if db.get(m.Fixture,item.fixture_id) is None:raise HTTPException(404,'Fixture not found')
  approved=[h.strip() for h in os.getenv('SPORTS_BROWSER_ALLOWED_HOSTS','').split(',') if h.strip()]
  if not approved:raise HTTPException(403,'Browser host allowlist is not configured')
  session=m.BrowserCapture(fixture_id=item.fixture_id,source_id=item.source_id,url=item.url,status='PENDING',vision_status='NOT_PERFORMED')
  db.add(session);db.commit();db.refresh(session);sid=session.id
 try:
  result=await capture(item.url,item.fixture_id,approved,os.getenv('SPORTS_EVIDENCE_ROOT','/tmp/cacsms-evidence'))
  status=result['capture_status'];error=result['error']
 except Exception as exc:
  result={};status='FAILED';error=str(exc)[:500]
 with SessionLocal.begin() as db:
  row=db.get(m.BrowserCapture,sid);row.status=status;row.evidence_hash=result.get('sha256');row.vision_status=result.get('vision_status','NOT_PERFORMED');row.error=error
  db.add(m.AuditEvent(actor='admin',action='browser.capture',correlation_id=sid,payload={'status':status,'source_id':item.source_id,'url':item.url,'hash':result.get('sha256'),'http_status':result.get('http_status'),'page_title':result.get('page_title'),'navigation_duration_ms':result.get('navigation_duration_ms'),'error':error}))
 return {'id':sid,'status':status,'evidence':result,'error':error,'vision_verified':False}


@router.get('/browser/readiness')
def browser_readiness():
 configured=all(os.getenv(k) for k in ('SPORTS_VISION_ENDPOINT','SPORTS_VISION_API_KEY','SPORTS_VISION_MODEL','SPORTS_VISION_ALLOWED_HOSTS'))
 from app.modules.acquisition.source_policy import PROHIBITED,prohibition
 restricted='; '.join(f"{e['name']} ({d}): {e['reason']}" for d,e in PROHIBITED.items() if prohibition(d)) or 'None'
 return {'restricted_sources':restricted,'autonomous_acquisition':'Fixture discovery uses configured authorized feeds; browser capture is administrator initiated','browser_scheduler':'NOT_CONFIGURED','mode':'PAPER','vision_configured':configured,'browser_hosts_configured':bool(os.getenv('SPORTS_BROWSER_ALLOWED_HOSTS')),'evidence_root_configured':bool(os.getenv('SPORTS_EVIDENCE_ROOT')),'inference_status':'CONFIGURED_NOT_CLAIMED' if configured else 'NOT_CONFIGURED','verification_policy':'INDEPENDENT_REVIEW_REQUIRED','prediction_pipeline':'BLOCKED_UNTIL_APPROVED_MODEL_AND_FEATURES'}


@router.post('/admin/browser/{capture_id}/infer')
async def infer_admin(capture_id:str,x_admin_token:str|None=Header(default=None)):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not x_admin_token or not secrets.compare_digest(expected,x_admin_token):raise HTTPException(403,'Administrator token required')
 from app.modules.vision.pipeline import interpret_capture
 try:
  with SessionLocal.begin() as db:
   return await interpret_capture(db,capture_id)
 except (ValueError,PermissionError,FileNotFoundError) as exc:raise HTTPException(422,str(exc)) from exc
