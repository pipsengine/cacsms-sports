from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import create_engine,select,func,event,DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.markets import history_import as hi, intelligence as mi, intelligence_routes
from app.modules.autonomy import open_intelligence as oi

AT=datetime(2026,11,16,12,tzinfo=timezone.utc)


def row(date,time,home,away,**prices):
    base={'Div':'E0','Date':date,'Time':time,'HomeTeam':home,'AwayTeam':away,'B365CH':'1.90','B365CD':'3.50','B365CA':'4.20','AvgCH':'1.95','AvgCD':'3.40','AvgCA':'4.00',
          'B365C>2.5':'1.80','B365C<2.5':'2.00','AHCh':'-0.75','B365CAHH':'1.92','B365CAHA':'1.98'}
    base.update(prices);return base


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    def aware(target,*_):
        for col in target.__table__.columns:
            v=target.__dict__.get(col.key)
            if isinstance(col.type,DateTime) and isinstance(v,datetime) and v.tzinfo is None:target.__dict__[col.key]=v.replace(tzinfo=timezone.utc)
    event.listen(Base,'load',aware,propagate=True)
    factory=sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(m.Source(id='ol',name='OpenLigaDB (ODbL 1.0)',permission='AUTHORIZED',enabled=True));oi.ensure_source(db)
    yield factory
    event.remove(Base,'load',aware);engine.dispose()


def test_kickoff_uses_uk_local_time_and_requires_a_time():
    assert hi.kickoff({'Date':'16/08/2025','Time':'15:00'})==datetime(2025,8,16,14,0,tzinfo=timezone.utc), 'BST'
    assert hi.kickoff({'Date':'16/01/2026','Time':'15:00'})==datetime(2026,1,16,15,0,tzinfo=timezone.utc), 'GMT'
    assert hi.kickoff({'Date':'16/01/26','Time':''}) is None


def test_closing_prices_parse_and_reject_invalid():
    prices,rejected=hi.closing_prices(row('1/1/2026','15:00','A','B',PSCH='0.5',PSCD='3.1',PSCA='4'))
    keys={(b,mk,o) for b,mk,o,_ in prices}
    assert ('Bet365','1X2','HOME') in keys and ('Bet365','OU_2.5','OVER') in keys and ('Bet365','AH_-0.75','AWAY') in keys
    assert ('Market average (closing)','1X2','DRAW') in keys and not any(b=='Pinnacle' for b,*_ in prices)
    assert rejected==1


def test_archive_import_is_idempotent_evidence_backed_and_quiet(factory):
    rows=[row('16/08/2025','15:00','Arsenal','Chelsea'),row('17/08/2025','16:30','Leeds','Everton'),row('18/08/2025','','Wolves','Fulham')]
    url='https://football-data.co.uk/mmz4281/2526/E0.csv'
    with factory.begin() as db:
        events=db.scalar(select(func.count()).select_from(m.PipelineEvent))
        report=hi.import_file(db,'E0',2025,rows,url,AT)
        assert report['matches']==2 and report['prices']==2*(6+2+2) and report['skipped_no_time']==1
        assert db.scalar(select(func.count()).select_from(m.PipelineEvent))==events, 'archive import emits no per-record pipeline events'
    with factory.begin() as db:
        assert hi.import_file(db,'E0',2025,rows,url,AT)['matches']==0, 'idempotent per match'
        comp=db.scalar(select(m.Competition).where(m.Competition.name=='Premier League'))
        assert comp.country=='England'
        fx=db.scalar(select(m.Fixture).where(m.Fixture.home_name=='Arsenal'))
        assert fx.competition_id==comp.id and fx.kickoff_at==datetime(2025,8,16,14,0,tzinfo=timezone.utc)
        odds=db.scalars(select(m.Odds).where(m.Odds.fixture_id==fx.id)).all()
        assert all(o.observed_at==fx.kickoff_at for o in odds), 'closing prices stamped at kickoff'
        assert all(db.get(m.MarketEvidence,o.id).source_id==oi.FD_SOURCE_ID for o in odds)
        assert db.scalar(select(func.count()).select_from(m.Result))==0, 'single-source archives never verify results'


def test_bundesliga_rows_never_create_single_source_fixtures(factory):
    with factory.begin() as db:
        report=hi.import_file(db,'D1',2025,[row('22/08/2025','19:30','Bayern Munich','RB Leipzig',Div='D1')],'https://football-data.co.uk/mmz4281/2526/D1.csv',AT)
        assert report['skipped_unmatched']==1 and db.scalar(select(func.count()).select_from(m.Fixture))==0
        comp=db.scalar(select(m.Competition).where(m.Competition.name=='Bundesliga'))
        db.add(m.Fixture(id='fx',competition_id=comp.id,home_name='FC Bayern München',away_name='RB Leipzig',kickoff_at=datetime(2025,8,22,18,30,tzinfo=timezone.utc)))
    with factory.begin() as db:
        report=hi.import_file(db,'D1',2025,[row('22/08/2025','19:30','Bayern Munich','RB Leipzig',Div='D1')],'https://football-data.co.uk/mmz4281/2526/D1.csv',AT)
        assert report['matches']==1 and db.scalar(select(func.count()).select_from(m.Odds).where(m.Odds.fixture_id=='fx'))==10


def test_overview_markets_and_sources_report_only_recorded_facts(factory):
    with factory.begin() as db:
        hi.import_file(db,'E0',2025,[row('16/08/2025','15:00','Arsenal','Chelsea')],'https://football-data.co.uk/mmz4281/2526/E0.csv',AT)
    with factory.begin() as db:
        o=mi.overview(db,AT)
        assert o['price_observations']==10 and o['fixtures_priced']==1 and o['markets_represented']==3 and o['fresh_prices']==0
        assert o['model_coverage']==0.0 and o['qualified']==0
        steps={s['key']:s['status'] for s in o['pipeline']}
        assert steps['collect']=='DONE' and steps['map']=='DONE' and steps['qualify']=='WAITING'
        page=mi.markets(db,limit=5,at=AT)
        assert page['total']>=430 and [x['status'] for x in page['markets'][:3]]==['OBSERVED']*3 and page['markets'][3]['status']=='REGISTERED'
        ft=next(x for x in page['markets'] if x['name']=='Full Time Result (1X2)')
        assert ft['observations']==6 and ft['sample']['fixture']=='Arsenal vs Chelsea' and max(q['decimal_odds'] for q in ft['sample']['best'])==4.2
        cats={c['key']:c for c in mi.categories(db,AT)}
        assert cats['match_result']['observed']==1 and cats['handicap']['observed']==1 and cats['corners']['observed']==0
        cov=mi.sports_coverage(db)[0]
        assert cov['competition']=='Premier League' and cov['fixtures_priced']==1 and cov['verified_results']==0 and not cov['research_ready']
        assert any(s['source']=='SportyBet' and s['status']=='NO_PERMITTED_FEED' for s in mi.sources(db))
        assert mi.sync_history(db)[0]['action']=='markets.archive_import'
        assert mi.benchmark(db,AT)['status']=='NO_MODEL'


def test_endpoints(factory,monkeypatch):
    monkeypatch.setattr(intelligence_routes,'SessionLocal',factory);monkeypatch.setenv('SPORTS_ADMIN_TOKEN','t')
    app=FastAPI();app.include_router(intelligence_routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/market-intelligence/overview').status_code==200
    assert client.get('/api/v1/sports/market-intelligence/markets?limit=3&offset=3').json()['offset']==3
    assert len(client.get('/api/v1/sports/market-intelligence/categories').json())==16
    assert client.post('/api/v1/sports/market-intelligence/sync').status_code==403
