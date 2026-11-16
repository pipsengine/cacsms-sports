from datetime import datetime,timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.acquisition import source_intelligence as si


def factory():
 engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
 Base.metadata.create_all(engine)
 return sessionmaker(bind=engine)


def test_overview_reports_persisted_sources_only():
 Session=factory()
 with Session.begin() as db:
  db.add(m.Source(id='a',name='Open feed',permission='AUTHORIZED',enabled=True))
  db.add(m.Source(id='b',name='Blocked',permission='PROHIBITED',enabled=False))
 with Session() as db:
  snap=si.overview(db)
  assert snap['mode']=='PAPER'
  assert snap['autonomous'] is True
  assert snap['kpis']['active_sources']==1
  assert snap['kpis']['authorized_sources']==1
  assert snap['health']['prohibited']==1
  assert 'sports' in snap['coverage']
  assert snap['pipeline'][0]['name']=='Discover'
  assert all('status' in step for step in snap['pipeline'])


def test_analytics_and_jobs_are_evidence_backed():
 Session=factory()
 at=datetime.now(timezone.utc)
 with Session.begin() as db:
  db.add(m.Source(id='s1',name='Feed',permission='AUTHORIZED',enabled=True))
  db.add(m.AcquisitionJob(id='j1',source_id='s1',fixture_id='f1',section='standings',idempotency_key='k1',status='COMPLETED',created_at=at,updated_at=at))
  db.add(m.AcquisitionJob(id='j2',source_id='s1',fixture_id='f1',section='recent_form',idempotency_key='k2',status='FAILED',error_code='HTTP_ERROR',created_at=at,updated_at=at))
 with Session() as db:
  analytics=si.analytics(db)
  assert analytics['jobs']==2
  assert analytics['successful_jobs']==1
  assert analytics['failed_jobs']==1
  assert len(analytics['activity_24h'])==24
  jobs=si.acquisition_jobs(db)
  assert jobs[0]['source']=='Feed'
  assert 'started_at' in jobs[0]
