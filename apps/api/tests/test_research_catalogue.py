from datetime import date, datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.research import catalog, catalog_routes
from app.modules.research.league import top_two_research
from app.modules.research.catalog_routes import SnapshotIn

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


@pytest.fixture
def store():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread':False}, execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(m.Sport(id='sport', name='football'))
        db.flush()
        db.add_all([m.Competition(id='league',sport_id='sport',name='League',country='England'),m.Competition(id='other',sport_id='sport',name='Other')])
        db.flush()
        db.add_all([m.CompetitionSeason(id='current',competition_id='league',label='2026',start_date=date(2026,1,1),end_date=date(2026,12,31)),
                    m.CompetitionSeason(id='old',competition_id='league',label='2025',start_date=date(2025,1,1),end_date=date(2025,12,31)),
                    m.CompetitionSeason(id='foreign',competition_id='other',label='2026',start_date=date(2026,1,1),end_date=date(2026,12,31)),
                    m.Source(id='source',name='Authorized Provider',enabled=True,permission='AUTHORIZED')])
        db.flush()
        for ident, season, home, away, score, kickoff in [('f','current','A','B',(2,0),NOW-timedelta(days=2)),('old-f','old','C','D',(9,0),NOW-timedelta(days=400))]:
            db.add(m.Fixture(id=ident,competition_id='league',season_id=season,home_name=home,away_name=away,kickoff_at=kickoff))
            db.flush()
            db.add(m.Observation(id='o-'+ident,source_id='source',fixture_id=ident,source_url='https://provider.example/results',content_hash=ident.ljust(64,'0'),observed_at=kickoff+timedelta(hours=2),payload={'section':'official_result'}))
            db.add(m.Result(id='r-'+ident,fixture_id=ident,version=1,outcome={'status':'FINAL','score':{'home':score[0],'away':score[1]}},verified_at=kickoff+timedelta(hours=3)))
            db.flush()
            db.add(m.ResultEvidence(result_id='r-'+ident,source_id='source',observation_id='o-'+ident))
        db.commit()
        yield db
    engine.dispose()


def entry(club='A',rank=1):
    return dict(club=club,rank=rank,played=1,wins=1,draws=0,losses=0,goals_for=2,goals_against=0,goal_difference=2,points=3)


def snapshot(db, ident='snap',scope='overall', captured=None, verified=None):
    db.add(m.StandingsSnapshot(id=ident,competition_id='league',season_id='current',source_id='source',source_url='https://provider.example/table',source_reference='league-2026',content_hash=ident.ljust(64,'0'),captured_at=captured or NOW-timedelta(days=1),verified_at=verified or NOW-timedelta(hours=12),official=True,scope=scope,entries=[entry('B')]))
    db.commit()


def test_seasons_and_top_two_share_verified_scores(store):
    table=catalog.standings(store,'league','current',NOW)
    assert [r['club'] for r in table['rows']]==['A','B']
    assert table['verified_matches']==1
    assert table['mode']=='computed_unofficial'
    assert top_two_research(store,'league',NOW,season_id='current')['top_two'][0]['club']=='A'
    assert len(catalog.fixtures(store,'league','old'))==1
    with pytest.raises(ValueError):catalog.standings(store,'league','foreign',NOW)
    with pytest.raises(LookupError):catalog.standings(store,'missing',None,NOW)


def test_historical_correction_does_not_leak_or_resurrect(store):
    store.add(m.Result(id='correction',fixture_id='f',version=2,verified_at=NOW+timedelta(days=1),outcome={'status':'FINAL'}))
    store.commit()
    assert catalog.standings(store,'league','current',NOW)['verified_matches']==1
    # Use a historical correction cutoff within today's real date.
    assert catalog.standings(store,'league','current',NOW+timedelta(days=2))['verified_matches']==0


def test_snapshot_scope_cutoff_and_revocation(store):
    snapshot(store)
    report=catalog.standings(store,'league','current',NOW)
    assert report['mode']=='source_snapshot' and report['rows'][0]['club']=='B'
    assert catalog.standings(store,'league','current',NOW,scope='home')['rows']==[]
    assert catalog.standings(store,'league','current',NOW-timedelta(days=1,hours=1))['mode']=='computed_unofficial'
    assert catalog.standings(store,'league',None,NOW)['mode']=='computed_unofficial'
    store.get(m.Source,'source').enabled=False
    store.commit()
    assert catalog.standings(store,'league','current',NOW)['rows']==[]


def test_snapshot_verification_time_and_home_scope(store):
    snapshot(store,scope='home',verified=NOW+timedelta(days=1))
    assert catalog.standings(store,'league','current',NOW,scope='home')['rows']==[]
    assert catalog.standings(store,'league','current',NOW+timedelta(days=2),scope='home')['rows'][0]['club']=='B'


def test_dossier_pre_match_evidence_permissions_and_cutoff(store):
    kickoff=NOW-timedelta(days=2)
    store.add_all([m.Observation(id='early',source_id='source',fixture_id='f',source_url='https://provider.example/research',content_hash='x'*64,observed_at=kickoff-timedelta(days=1),payload={'section':'team_news','data':{'note':'Actual submitted evidence'}}),
                   m.Observation(id='late',source_id='source',fixture_id='f',content_hash='y'*64,observed_at=kickoff+timedelta(minutes=1),payload={'section':'team_news'})])
    store.commit()
    result=catalog.dossier(store,'f',NOW)
    assert [r['id'] for r in result['evidence']]==['early']
    assert result['evidence'][0]['verification']=='AUTHORIZED_SOURCE_OBSERVATION'
    assert catalog.dossier(store,'f',kickoff-timedelta(days=2))['evidence']==[]
    store.get(m.Source,'source').permission='RESTRICTED'
    store.commit()
    assert catalog.dossier(store,'f',NOW)['evidence']==[]


def test_standings_intake_validates_provenance_and_rows():
    payload=dict(competition_id='league',season_id='current',source_id='source',source_url='https://provider.example/table',source_reference='reference',captured_at=NOW-timedelta(days=1),verified_at=NOW,entries=[entry()])
    assert SnapshotIn(**payload).scope=='overall'
    for patch in ({'entries':[entry(),entry()]},{'entries':[dict(entry(),played=3)]},{'verified_at':NOW-timedelta(days=2)},{'source_url':'http://localhost/table'},{'entries':[dict(entry(),rank=True)]},{'scope':'fake'}):
        with pytest.raises(ValueError):SnapshotIn(**dict(payload,**patch))


def test_read_validation_and_admin_auth(monkeypatch):
    from app.main import app
    monkeypatch.delenv('SPORTS_ADMIN_TOKEN',raising=False)
    client=TestClient(app)
    assert client.get('/api/v1/sports/research/catalog/fixtures').status_code==422
    response=client.post('/api/v1/sports/admin/research/seasons',json=dict(competition_id='x',label='2026',start_date='2026-01-01',end_date='2026-12-31'))
    assert response.status_code==403


def test_admin_intake_replay_and_season_assignment(store, monkeypatch):
    from app.main import app
    monkeypatch.setenv('SPORTS_ADMIN_TOKEN','test-admin-token')
    monkeypatch.setattr(catalog_routes,'SessionLocal',sessionmaker(bind=store.bind))
    client=TestClient(app)
    headers={'X-Admin-Token':'test-admin-token'}
    result=client.post('/api/v1/sports/admin/research/seasons',headers=headers,json=dict(competition_id='league',label='2026',start_date='2026-01-01',end_date='2026-12-31',is_current=True,country='England'))
    assert result.status_code==201
    assert result.json()['id']=='current'
    assert client.post('/api/v1/sports/admin/research/seasons/current/fixtures',headers=headers,json={'fixture_ids':['f','old-f']}).status_code==422
    assert client.post('/api/v1/sports/admin/research/seasons/current/fixtures',headers=headers,json={'fixture_ids':['f']}).json()['assigned']==1
    payload=dict(competition_id='league',season_id='current',source_id='source',source_url='https://provider.example/table',source_reference='ref',captured_at=(NOW-timedelta(days=1)).isoformat(),verified_at=NOW.isoformat(),entries=[entry()])
    first=client.post('/api/v1/sports/admin/research/standings',headers=headers,json=payload)
    assert first.status_code==201,first.text
    replay=client.post('/api/v1/sports/admin/research/standings',headers=headers,json=payload)
    assert replay.json()['id']==first.json()['id'] and replay.json()['replayed']
    table=client.get('/api/v1/sports/research/catalog/standings',params={'league_id':'league','season_id':'current'})
    assert table.status_code==200 and table.json()['mode']=='source_snapshot'
    assert client.get('/api/v1/sports/research/catalog/standings',params={'league_id':'league','season_id':'foreign'}).status_code==422
    assert client.get('/api/v1/sports/research/catalog/sports').json()[0]['name']=='football'
    assert client.get('/api/v1/sports/research/catalog/countries',params={'sport':'football'}).json()==[{'name':'England'}]
