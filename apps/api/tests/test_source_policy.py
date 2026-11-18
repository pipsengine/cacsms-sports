import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.acquisition import source_policy as policy
from app.modules.acquisition.jobs import validate_feed_url
from app.modules.vision.security import validate_destination

PUBLIC=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))]


@pytest.fixture
def factory():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.mark.parametrize('url',['https://www.betexplorer.com/','https://betexplorer.com/football/germany/bundesliga/','https://m.betexplorer.com/x'])
def test_prohibited_source_is_refused_everywhere_even_if_allowlisted(url):
    with pytest.raises(PermissionError,match='BetExplorer is prohibited'):
        validate_destination(url,['www.betexplorer.com','betexplorer.com','m.betexplorer.com'],resolver=PUBLIC)
    with pytest.raises(ValueError,match='prohibited by its terms'):
        validate_feed_url(url,resolve=False)


def test_unrelated_hosts_are_unaffected():
    assert validate_feed_url('https://api.openligadb.de/getavailableleagues/2026',resolve=False)
    assert validate_destination('https://notbetexplorer.com/',['notbetexplorer.com'],resolver=PUBLIC)


def test_recorded_written_consent_lifts_the_block(monkeypatch):
    monkeypatch.setenv('SPORTS_SOURCE_CONSENT','betexplorer.com=Livesport licence 2027-001')
    assert policy.prohibition('www.betexplorer.com') is None
    assert validate_feed_url('https://www.betexplorer.com/',resolve=False)


def test_registration_is_idempotent_and_downgrades_authorized_rows(factory):
    with factory.begin() as db:
        db.add(m.Source(name='BetExplorer',permission='AUTHORIZED',enabled=True))
    with factory.begin() as db:assert set(policy.register_prohibited_sources(db))=={'betexplorer.com','football-data.co.uk'}
    with factory.begin() as db:assert policy.register_prohibited_sources(db)==[]
    with factory() as db:
        source=db.scalar(select(m.Source).where(m.Source.name=='BetExplorer'))
        assert (source.permission,source.enabled)==('PROHIBITED',False)
        assert db.scalar(select(func.count()).select_from(m.AuditEvent).where(m.AuditEvent.action=='source.prohibited'))==2
        row=next(r for r in policy.registry(db) if r['source']=='BetExplorer')
        assert row['status']=='PROHIBITED' and 'scraping' in row['restriction'] and row['observations']==0


def test_registry_reports_only_recorded_activity(factory):
    with factory.begin() as db:
        db.add(m.Source(id='s',name='Open feed',permission='AUTHORIZED',enabled=True))
    with factory() as db:
        row=policy.registry(db)[0]
        assert row['status']=='ACTIVE' and row['last_sync'] is None and row['freshness_minutes'] is None and row['observations']==0


def test_current_football_data_restriction_applies_to_csv_collector_before_network():
    from app.modules.autonomy.open_intelligence import fetch_csv
    with pytest.raises(PermissionError,match='Football-Data.co.uk'):
        fetch_csv('https://football-data.co.uk/fixtures.csv')
