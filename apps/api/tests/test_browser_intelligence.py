from datetime import datetime,timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.vision import browser_intelligence as bi


def factory():
 engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
 Base.metadata.create_all(engine)
 return sessionmaker(bind=engine)


def test_overview_is_autonomous_and_evidence_backed():
 Session=factory()
 with Session.begin() as db:
  db.add(m.Source(id='s1',name='Open feed',permission='AUTHORIZED',enabled=True))
  db.add(m.Source(id='s2',name='BetExplorer',permission='PROHIBITED',enabled=False))
 with Session() as db:
  snap=bi.overview(db)
  assert snap['autonomous'] is True
  assert snap['mode']=='PAPER'
  assert snap['kpis']['authorized_sources']==1
  assert snap['kpis']['prohibited_sources']==1
  assert snap['pipeline'][0]['name']=='Discover'
  assert snap['readiness']['verification_policy']=='INDEPENDENT_REVIEW_REQUIRED'
  assert any(b['name']=='Paid wagering' for b in snap['boundaries'])


def test_summary_counts_persisted_captures_only():
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
  assert summary['vision_provider'] in ('NOT_CONFIGURED','CONFIGURED_NOT_CLAIMED')
