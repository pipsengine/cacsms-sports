"""Adapted standings API: authorization, corrections, scope, history and worker tests."""
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.standings import service,routes
from app.modules.research import catalog


@pytest.fixture
def factory():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def registration(authorized=True):
    return dict(id='eng-e0',sport='Football',country='England',name='Premier League',division_code='E0',source_url='https://www.football-data.co.uk/mmz4281/2526/E0.csv',authorized=authorized,points_win=3)


def csv(h=2,a=0):
    result='H' if h>a else 'A' if h<a else 'D'
    return f'Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/11/2025,Alpha,Beta,{h},{a},{result}\n02/11/2025,Beta,Alpha,1,1,D\n'.encode()


def register(factory,authorized=True):
    with factory.begin() as db:return service.register(db,registration(authorized))['id']


@pytest.mark.parametrize('url',['http://www.football-data.co.uk/mmz4281/2526/E0.csv','https://www.football-data.co.uk/secret.csv','https://www.football-data.co.uk.evil.example/mmz4281/2526/E0.csv','https://www.football-data.co.uk/mmz4281/2526/E0.csv?redirect=1','https://user@www.football-data.co.uk/mmz4281/2526/E0.csv'])
def test_url_boundaries(url):
    with pytest.raises(ValueError):service.safe_source(url)


def test_registration_permission_and_season_validation(factory):
    register(factory,False)
    def forbidden(url):raise AssertionError('Unauthorized source fetched')
    with pytest.raises(PermissionError):service.sync(factory,'eng-e0','2025/2026',forbidden)
    register(factory)
    with pytest.raises(ValueError):service.sync(factory,'eng-e0','2024/2025',forbidden)
    with pytest.raises(ValueError):service.season_year('2025/2027')


def test_parse_rejects_invalid_and_conflicting_rows():
    at=datetime.now(timezone.utc)
    for data in [csv().replace(b',2,0,H',b',2,0,A'),csv()+b'01/11/2025,Alpha,Beta,0,2,A\n',csv().replace(b'01/11/2025',b'01/11/2099'),b'hello,world\n1,2\n']:
        with pytest.raises(ValueError):service.parse_csv(data,'2025/2026',at)
    values,rejected=service.parse_csv(csv()+b'01/11/2025,Alpha,Beta,2,0,H\n','2025/2026',at)
    assert len(values)==2 and rejected==0


def test_corrections_idempotence_and_historical_cutoff(factory):
    cid=register(factory);at=datetime.now(timezone.utc)-timedelta(hours=1)
    first=service.sync(factory,'eng-e0','2025/2026',lambda _:csv(),at)
    assert first['changed'] and first['valid_rows']==2
    again=service.sync(factory,'eng-e0','2025/2026',lambda _:csv(),at+timedelta(seconds=10))
    assert not again['changed']
    changed=service.sync(factory,'eng-e0','2025/2026',lambda _:csv(0,2),at+timedelta(seconds=20))
    assert changed['changed']
    service.sync(factory,'eng-e0','2025/2026',lambda _:csv(),at+timedelta(seconds=30))
    with factory() as db:
        state=service.resolve_state(db,'eng-e0');sid=state.payload['season_id']
        assert catalog.standings(db,cid,sid,at+timedelta(seconds=1))['rows'][0]['club']=='Alpha'
        assert catalog.standings(db,cid,sid,at+timedelta(seconds=21))['rows'][0]['club']=='Beta'
        latest=catalog.standings(db,cid,sid,at+timedelta(seconds=31))
        assert latest['rows'][0]['club']=='Alpha' and latest['mode']=='csv_computed'
        assert latest['source']['verified_at'] is None
        home=catalog.standings(db,cid,sid,scope='home')
        assert next(r for r in home['rows'] if r['club']=='Alpha')['played']==1
        assert db.scalar(select(func.count()).select_from(m.Observation))==3
        assert db.scalar(select(func.count()).select_from(m.PipelineEvent).where(m.PipelineEvent.kind=='standings.updated'))==3
        assert db.scalar(select(func.count()).select_from(m.Result))==0
        assert db.scalar(select(func.count()).select_from(m.StandingsSnapshot))==0
    def broken(_):raise TimeoutError('secret provider contents')
    with pytest.raises(TimeoutError):service.sync(factory,'eng-e0','2025/2026',broken,at+timedelta(seconds=40))
    with factory() as db:
        assert catalog.standings(db,cid,sid)['rows'][0]['club']=='Alpha'
        run=db.scalars(select(m.AuditEvent).where(m.AuditEvent.action=='standings.sync')).all()[-1]
        assert run.payload['status']=='FAILED' and 'secret' not in str(run.payload)
    with factory.begin() as db:db.get(m.Source,service.resolve_state(db,'eng-e0').source_id).enabled=False
    with factory() as db:assert catalog.standings(db,cid,sid)['rows']==[]


def test_existing_worker_collects_only_due_sources(factory):
    register(factory)
    at=datetime.now(timezone.utc)
    report=service.collect(factory,lambda _:csv(),at)
    assert report['configured_sources']==1 and report['processed']==1 and not report['errors']
    def forbidden(_):raise AssertionError('Cache not respected')
    assert service.collect(factory,forbidden,at+timedelta(seconds=1))['processed']==0


def test_health_does_not_advertise_disabled_legacy_collector_schedule(factory,monkeypatch):
    cid=register(factory)
    next_check=datetime.now(timezone.utc)+timedelta(hours=1)
    with factory.begin() as db:
        state=service.resolve_state(db,'eng-e0')
        db.add(m.ProviderSyncState(id='openligadb:bl1:2026',source_id=state.source_id,
                                  payload={'competition_id':cid},next_check_at=next_check,failures=0))
        state.next_check_at=None
    monkeypatch.setattr(routes,'SessionLocal',factory)
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    monkeypatch.setenv('SPORTS_FIXTURE_DISCOVERY_ENABLED','1')
    assert client.get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()['next_sync'] is None
    monkeypatch.setenv('SPORTS_FIXTURE_DISCOVERY_ENABLED','0')
    assert client.get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()['next_sync'] is not None


def test_non_football_analytics_do_not_present_football_goals(factory,monkeypatch):
    with factory.begin() as db:
        sport=m.Sport(name='Basketball');db.add(sport);db.flush()
        comp=m.Competition(sport_id=sport.id,name='Basketball league');db.add(comp);db.flush();cid=comp.id
    monkeypatch.setattr(routes,'SessionLocal',factory)
    app=FastAPI();app.include_router(routes.router)
    data=TestClient(app).get('/api/v1/sports/standings/analytics',params={'competition_id':cid}).json()
    assert data['average_goals'] is None and data['home_win_pct'] is None
    assert 'unavailable for this sport' in data['note']


def test_api_uses_existing_admin_and_canonical_data(factory,monkeypatch):
    monkeypatch.setattr(routes,'SessionLocal',factory)
    monkeypatch.setenv('SPORTS_ADMIN_TOKEN','test-secret')
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    assert client.post('/api/v1/sports/standings/admin/competitions',json=registration()).status_code==403
    response=client.post('/api/v1/sports/standings/admin/competitions',headers={'X-Admin-Token':'test-secret'},json=registration())
    assert response.status_code==201
    cid=response.json()['id']
    service.sync(factory,'eng-e0','2025/2026',lambda _:csv())
    params={'competition_id':'eng-e0','season':'2025/2026'}
    table=client.get('/api/v1/sports/standings/table',params={**params,'page_size':1}).json()
    assert table['total_teams']==2 and len(table['rows'])==1 and table['rows'][0]['Pts']==4
    full=client.get('/api/v1/sports/standings/table',params={**params,'page_size':1,'all_rows':True}).json()
    assert len(full['rows'])==full['total_teams']==2
    assert table['classification']=='csv_computed' and table['official'] is False
    assert client.get('/api/v1/sports/standings/table',params={**params,'mode':'invalid'}).status_code==422
    assert client.get('/api/v1/sports/standings/table',params={**params,'as_of':'2099-01-01T00:00:00Z'}).status_code==422
    assert len(client.get('/api/v1/sports/standings/top-two',params=params).json()['clubs'])==2
    analytics=client.get('/api/v1/sports/standings/analytics',params=params).json()
    assert analytics['sample_size']==2 and analytics['home_win_pct']==50
    assert analytics['goals_by_matchday'] is None
    assert client.get('/api/v1/sports/standings/history',params=params).json()['syncs'][0]['status']=='COMPLETED'
    assert client.get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()['source_online'] is None
