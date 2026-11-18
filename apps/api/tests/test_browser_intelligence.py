from datetime import datetime,timezone
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.vision import browser_intelligence as bi


def factory():
 engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
 Base.metadata.create_all(engine)
 return sessionmaker(bind=engine)


def test_overview_reports_manual_browser_capture_and_evidence_backed_state(monkeypatch):
 monkeypatch.setenv('SPORTS_BROWSER_ALLOWED_HOSTS','example.org')
 monkeypatch.setenv('SPORTS_VISION_ENDPOINT','https://vision.example.org')
 monkeypatch.setenv('SPORTS_VISION_API_KEY','test')
 monkeypatch.setenv('SPORTS_VISION_MODEL','test')
 monkeypatch.setenv('SPORTS_VISION_ALLOWED_HOSTS','vision.example.org')
 Session=factory()
 with Session.begin() as db:
  db.add(m.Source(id='s1',name='Open feed',permission='AUTHORIZED',enabled=True))
  db.add(m.Source(id='s2',name='BetExplorer',permission='PROHIBITED',enabled=False))
 with Session() as db:
  snap=bi.overview(db)
  assert snap['autonomous'] is False
  assert snap['mode']=='PAPER'
  assert snap['kpis']['authorized_sources']==1
  assert snap['kpis']['prohibited_sources']==1
  assert snap['pipeline'][0]['name']=='Discover'
  assert next(step for step in snap['pipeline'] if step['key']=='browse')['status']=='PENDING'
  assert next(step for step in snap['pipeline'] if step['key']=='analyse')['status']=='PENDING'
  assert next(check for check in snap['health'] if check['name']=='Browser scheduler')['status']=='NOT_CONFIGURED'
  assert snap['readiness']['verification_policy']=='INDEPENDENT_REVIEW_REQUIRED'
  assert any(b['name']=='Paid wagering' for b in snap['boundaries'])


def test_summary_counts_persisted_captures_only(monkeypatch):
 for name in ('SPORTS_VISION_ENDPOINT','SPORTS_VISION_API_KEY','SPORTS_VISION_MODEL','SPORTS_VISION_ALLOWED_HOSTS'):
  monkeypatch.setenv(name,'configured')
 Session=factory()
 with Session.begin() as db:
  db.add(m.Source(id='s1',name='Open feed',permission='AUTHORIZED',enabled=True))
  # BrowserCapture requires fixture FK; create minimal fixture graph
  db.add(m.Sport(id='sp',name='Football'))
  db.add(m.Competition(id='c1',sport_id='sp',name='League',country='X'))
  db.add(m.Fixture(id='f1',competition_id='c1',home_name='A',away_name='B',kickoff_at=datetime.now(timezone.utc),status='SCHEDULED'))
  db.add(m.BrowserCapture(id='cap1',fixture_id='f1',source_id='s1',url='https://example.org/',status='CAPTURED',vision_status='NOT_PERFORMED',evidence_hash='abc'))
 with Session() as db:
  summary=bi.summary(db)
  assert summary['sessions']==1
  assert summary['captured']==1
  assert summary['vision_verified']==0
  assert summary['vision_provider']=='CONFIGURED_NOT_CLAIMED'
  assert next(step for step in bi.overview(db)['pipeline'] if step['key']=='analyse')['status']=='PENDING'


def test_failed_navigation_keeps_screenshot_and_audit(monkeypatch):
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 from app.modules.vision import routes
 Session=factory()
 with Session.begin() as db:
  db.add(m.Source(id='s1',name='Open feed',permission='AUTHORIZED',enabled=True))
  db.add(m.Sport(id='sp',name='Football'))
  db.add(m.Competition(id='c1',sport_id='sp',name='League'))
  db.add(m.Fixture(id='f1',competition_id='c1',home_name='A',away_name='B',kickoff_at=datetime.now(timezone.utc),status='SCHEDULED'))
 async def failed_capture(*args):
  return {'capture_status':'FAILED','error':'HTTP_403','sha256':'evidence','vision_status':'NOT_PERFORMED',
          'http_status':403,'page_title':'Access denied','navigation_duration_ms':12}
 monkeypatch.setattr(routes,'SessionLocal',Session)
 monkeypatch.setattr(routes,'capture',failed_capture)
 monkeypatch.setenv('SPORTS_ADMIN_TOKEN','test-token')
 monkeypatch.setenv('SPORTS_BROWSER_ALLOWED_HOSTS','example.org')
 app=FastAPI();app.include_router(routes.router)
 response=TestClient(app).post('/api/v1/sports/admin/browser/capture',headers={'x-admin-token':'test-token'},
                               json={'fixture_id':'f1','source_id':'s1','url':'https://example.org/'})
 assert response.status_code==201
 assert response.json()['status']=='FAILED' and response.json()['error']=='HTTP_403'
 with Session() as db:
  row=db.get(m.BrowserCapture,response.json()['id'])
  event=db.scalar(select(m.AuditEvent).where(m.AuditEvent.correlation_id==row.id))
  assert row.status=='FAILED' and row.evidence_hash=='evidence'
  assert event.payload['http_status']==403 and event.payload['page_title']=='Access denied'
