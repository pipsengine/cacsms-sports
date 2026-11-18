"""Browser & Vision Operator workspace: evidence-backed overview for autonomous capture.

Screenshot capture is not computer-vision verification. Captured images are not research
observations until independent review. Prohibited hosts remain blocked.
"""
import os
from datetime import datetime,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.acquisition.source_policy import registry,PROHIBITED,prohibition
from app.modules.autonomy.service import runtime_status
from app.modules.research.league import utc

PIPELINE=('Discover','Authorize','Browse','Capture','Analyse','Verify')


def _now(at=None):
 return at or datetime.now(timezone.utc)


def _stamp(value):
 if value is None:return None
 try:return utc(value).isoformat()
 except Exception:return value.isoformat() if hasattr(value,'isoformat') else str(value)


def _vision_configured():
 return all(os.getenv(k) for k in ('SPORTS_VISION_ENDPOINT','SPORTS_VISION_API_KEY','SPORTS_VISION_MODEL','SPORTS_VISION_ALLOWED_HOSTS'))


def sessions(db,limit=100):
 rows=db.scalars(select(m.BrowserCapture).order_by(m.BrowserCapture.created_at.desc()).limit(limit)).all()
 names={s.id:s.name for s in db.scalars(select(m.Source)).all()}
 return [{
  'id':s.id,'fixture_id':s.fixture_id,'source_id':s.source_id,'source':names.get(s.source_id,'—'),
  'url':s.url,'status':s.status,'vision_status':s.vision_status,'evidence_hash':s.evidence_hash,
  'error':s.error,'created_at':_stamp(s.created_at),
 } for s in rows]


def overview(db,at=None):
 at=_now(at)
 captures=db.scalars(select(m.BrowserCapture).order_by(m.BrowserCapture.created_at.desc()).limit(500)).all()
 sources=registry(db,at)
 runtime=runtime_status(db,at)
 authorized=[r for r in sources if r['permission']=='AUTHORIZED' and r['status']=='ACTIVE']
 prohibited=[r for r in sources if r['status']=='PROHIBITED']
 captured=[c for c in captures if c.status=='CAPTURED']
 failed=[c for c in captures if c.status=='FAILED']
 pending=[c for c in captures if c.status in ('PENDING','RUNNING')]
 vision_verified=[c for c in captures if c.vision_status=='VERIFIED']
 vision_ok=_vision_configured()
 hosts=bool(os.getenv('SPORTS_BROWSER_ALLOWED_HOSTS'))
 evidence_root=bool(os.getenv('SPORTS_EVIDENCE_ROOT'))
 has_auth=len(authorized)>0
 has_capture=len(captured)>0
 has_browse=has_capture
 pipeline=[{'key':step.lower(),'name':step,'status':'DONE' if (
  step=='Discover' or
  (step=='Authorize' and has_auth) or
  (step=='Browse' and has_browse) or
  (step=='Capture' and has_capture) or
  (step=='Analyse' and any(c.vision_status in ('EXTRACTED_UNVERIFIED','PARTIALLY_VERIFIED','VERIFIED') for c in captures)) or
  (step=='Verify' and len(vision_verified)>0)
 ) else 'PENDING'} for step in PIPELINE]
 pct=round(100*len(vision_verified)/len(captured),1) if captured else 0
 restricted='; '.join(f"{e['name']} ({d})" for d,e in PROHIBITED.items() if prohibition(d)) or 'None'
 health_checks=[
  {'name':'Browser service','status':'READY' if hosts else 'WAITING','detail':'Host allowlist configured' if hosts else 'SPORTS_BROWSER_ALLOWED_HOSTS unset'},
  {'name':'Capture service','status':'READY' if evidence_root or has_capture else 'WAITING','detail':'Evidence root or stored captures'},
  {'name':'Vision model','status':'CONFIGURED' if vision_ok else 'NOT_CONFIGURED','detail':'Provider env present' if vision_ok else 'Inference provider not configured'},
  {'name':'Evidence store','status':'READY' if evidence_root or any(c.evidence_hash for c in captures) else 'WAITING','detail':'Hashes persisted when captures succeed'},
  {'name':'Browser scheduler','status':'NOT_CONFIGURED','detail':'No autonomous browser jobs are dispatched; captures require an administrator'},
  {'name':'Autonomous controller','status':'ACTIVE' if runtime.get('worker_online') else 'OFFLINE','detail':runtime.get('status') or 'NOT_STARTED'},
 ]
 return {
  'mode':'PAPER','autonomous':False,'updated_at':_stamp(at),
  'runtime':{
   'worker_online':bool(runtime.get('worker_online')),
   'status':runtime.get('status'),
   'next_run_at':_stamp(runtime.get('next_run_at')),
   'last_success_at':_stamp(runtime.get('last_success_at')),
   'cycles':runtime.get('cycles') or 0,
   'interval_seconds':runtime.get('interval_seconds') or 30,
   'blockers':list(((runtime.get('report') or {}).get('blockers') or [])[:6]),
  },
  'kpis':{
   'sessions':len(captures),
   'captured':len(captured),
   'vision_verified':len(vision_verified),
   'in_progress':len(pending),
   'failed':len(failed),
   'authorized_sources':len(authorized),
   'prohibited_sources':len(prohibited),
   'readiness_pct':pct,
  },
  'pipeline':pipeline,
  'readiness':{
   'vision_configured':vision_ok,
   'browser_hosts_configured':hosts,
   'evidence_root_configured':evidence_root,
   'inference_status':'CONFIGURED_NOT_CLAIMED' if vision_ok else 'NOT_CONFIGURED',
   'verification_policy':'INDEPENDENT_REVIEW_REQUIRED',
   'prediction_pipeline':'BLOCKED_UNTIL_APPROVED_MODEL_AND_FEATURES',
   'restricted_sources':restricted,
   'autonomous_acquisition':'Fixture discovery uses configured authorized feeds; browser capture is administrator initiated',
  },
  'health':health_checks,
  'boundaries':[
   {'name':'Source authorization','detail':'Explicit permission and hostname allowlist'},
   {'name':'Browser capture','detail':'Restricted Playwright session with screenshot hashing'},
   {'name':'Vision interpretation','detail':'Configured provider inference is unverified until independent review'},
   {'name':'Research validation','detail':'Evidence and fixture matching required'},
   {'name':'Paid wagering','detail':'Disabled (PAPER only)'},
  ],
  'sources':[{
   'id':r['id'],'name':r['source'],'status':r['status'],'permission':r['permission'],
   'observations':r.get('observations') or 0,'restriction':r.get('restriction'),
   'terms_url':r.get('terms_url'),'last_sync':_stamp(r.get('last_sync')),'next_sync':_stamp(r.get('next_sync')),
  } for r in sources],
  'recent':sessions(db,12),
  'notice':'Browser capture is administrator initiated and only runs for allowlisted, authorized HTTPS origins. Screenshots are not vision-verified research. Prohibited hosts are refused. PAPER mode — no live wagers.',
 }


def summary(db):
 snap=overview(db)
 return {
  'mode':'PAPER',
  'sessions':snap['kpis']['sessions'],
  'captured':snap['kpis']['captured'],
  'vision_verified':snap['kpis']['vision_verified'],
  'vision_provider':'CONFIGURED_NOT_CLAIMED' if snap['readiness']['vision_configured'] else 'NOT_CONFIGURED',
  'recent':snap['recent'][:10],
  'autonomous':False,
 }
