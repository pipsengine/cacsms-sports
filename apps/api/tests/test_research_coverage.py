"""Research coverage: an optional section closes as NO_SOURCE_COVERAGE only when no authorized source could supply it."""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.pipeline import operations


@pytest.fixture
def db(monkeypatch):
 monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0');monkeypatch.setenv('SPORTS_SOURCE_FEEDS_JSON','{}')
 engine=create_engine('sqlite://',poolclass=StaticPool,execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
 Base.metadata.create_all(engine)
 with sessionmaker(bind=engine).begin() as session:
  session.add_all([m.Source(id='reviewed',name='Reviewed push source',permission='AUTHORIZED',enabled=True),
                   m.Source(id='disabled',name='Disabled push source',permission='AUTHORIZED',enabled=False)])
  session.flush();yield session
 engine.dispose()


def test_no_quorum_policy_means_no_push_coverage(db):
 assert operations.covered_sections(db)==set()


def test_reviewed_quorum_source_may_still_supply_every_section(db,monkeypatch):
 monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON',json.dumps({'reviewed':{'reviewed':True,'independence_group':'g1'}}))
 assert operations.covered_sections(db)==set(operations.SECTIONS)


def test_declared_sections_limit_push_coverage(db,monkeypatch):
 monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON',json.dumps({'reviewed':{'reviewed':True,'independence_group':'g1','sections':['lineups','not_a_section']}}))
 assert operations.covered_sections(db)=={'lineups'}


def test_unreviewed_disabled_or_invalid_policy_entries_cover_nothing(db,monkeypatch):
 monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON',json.dumps({'reviewed':{'reviewed':'yes'},'disabled':{'reviewed':True},'unknown':{'reviewed':True}}))
 assert operations.covered_sections(db)==set()
 monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON','not json')
 assert operations.covered_sections(db)==set()
