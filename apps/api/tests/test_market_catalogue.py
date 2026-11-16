from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.markets import catalogue as cat, catalogue_routes
from app.modules.pipeline import operations

APPROVED={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True,'holdout_metrics':{'brier':0.2}}


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    now=datetime.now(timezone.utc);at=now-timedelta(hours=1)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='Bundesliga',country='Germany'));db.flush()
        db.add(m.CompetitionSeason(id='season',competition_id='league',label='2026/27',start_date=date(2026,7,1),end_date=date(2027,6,30)))
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Source(id='blocked',name='Unverified',enabled=True,permission='UNVERIFIED'))
        for ident,home in (('fixture','Home'),('empty','Other')):db.add(m.Fixture(id=ident,competition_id='league',season_id='season',home_name=home,away_name='Away',kickoff_at=now+timedelta(days=1)))
        db.flush()
        db.add(m.Observation(id='obs',source_id='source',fixture_id='fixture',observed_at=at,source_url='https://provider.example/e',content_hash='o'*64,payload={'section':'market_odds','data':{}}))
        db.add(m.Research(id='dossier',fixture_id='fixture',version=1,status='VERIFIED',sections={},evidence_ids=['obs'],created_at=at+timedelta(minutes=1)))
        db.add(m.Feature(id='feature',research_id='dossier',cutoff_at=at+timedelta(minutes=2),features={}))
        db.add(m.ModelVersion(id='active',sport_id='sport',name='Logit',version='1.0',status='ACTIVE',validation=APPROVED));db.flush()
        for outcome,p,lo,hi in [('HOME',0.824,0.80,0.84),('DRAW',0.121,0.10,0.14),('AWAY',0.055,0.04,0.07)]:
            db.add(m.Prediction(id='p'+outcome,fixture_id='fixture',feature_id='feature',model_id='active',market_key='1X2',outcome_key=outcome,probability=p,predicted_at=at+timedelta(minutes=3),details={'interval':{'lower':lo,'upper':hi}}))
        quotes=[('SportyBet','1X2','HOME',1.27),('SportyBet','1X2','DRAW',5.40),('SportyBet','1X2','AWAY',12.0),('SportyBet','OU_2.5','OVER',1.56),
                ('SportyBet','OU_2.5','UNDER',2.47),('SportyBet','BTTS','YES',2.08),('SportyBet','BTTS','NO',1.73),('SportyBet','CORNERS_TOTAL_X','OVER',1.9)]
        for i,(book,market,outcome,price) in enumerate(quotes):
            db.add(m.Odds(id=f'q{i}',fixture_id='fixture',bookmaker=book,market_key=market,outcome_key=outcome,decimal_odds=price,observed_at=now-timedelta(minutes=5)));db.flush()
            db.add(m.MarketEvidence(odds_id=f'q{i}',observation_id='obs',source_id='source'))
        db.add(m.Odds(id='unsourced',fixture_id='fixture',bookmaker='Rumour',market_key='1X2',outcome_key='HOME',decimal_odds=9.0,observed_at=now-timedelta(minutes=5)))
    yield factory,now
    engine.dispose()


def test_catalogue_is_populated_without_any_odds(store):
    factory,now=store
    with factory.begin() as db:
        data=cat.catalogue(db)
        assert len(data['definitions'])>=400 and 'not a list of markets currently offered' in data['notice']
        assert {s['name'] for s in data['sports']}>={'Football','Basketball','Tennis','Esports','Cycling'}
        football=cat.catalogue(db,'Football')['definitions']
        ft=next(d for d in football if d['name']=='Full Time Result (1X2)')
        assert [o['key'] for o in ft['outcomes']]==['HOME','DRAW','AWAY'] and ft['origin']=='REGISTERED'
        assert next(d for d in football if d['name']=='Total Goals Over/Under')['parameter']['values']==[0.5,1.5,2.5,3.5,4.5,5.5]
        assert next(d for d in football if d['name']=='Anytime Goalscorer')['kind']=='PLAYER_PROP'
        cats={c['key']:c['registered'] for c in cat.categories(db,'Football')}
        assert cats['corners']>=10 and cats['player']>=10 and len(cats)==16
        assert cat.seed(db) is False, 'seeding is idempotent'


def test_fixture_without_odds_shows_registered_but_nothing_offered(store):
    factory,now=store
    with factory.begin() as db:
        view=cat.fixture_view(db,'empty')
    assert view['markets'] and not any(x['offered'] for x in view['markets'])
    assert all('AVAILABLE' not in x['statuses'] and x['probability'] is None for x in view['markets'])
    assert view['coverage']['offered']==0 and view['coverage']['missing_data_reasons']=={'NO_SOURCE_BACKED_ODDS_FOR_FIXTURE':1}


def test_scan_normalises_evaluates_and_ranks_only_supported_markets(store):
    factory,now=store
    with factory.begin() as db:
        run=cat.scan(db,'fixture',at=now,trigger='API')
        from types import SimpleNamespace
        results={(r.definition_id,r.outcome_key,r.line):SimpleNamespace(decision=r.decision,rank=r.rank,statuses=list(r.statuses),metrics=dict(r.metrics),reasons=list(r.reasons),odds_id=r.odds_id)
                 for r in db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id))}
    home=results[('football.full_time_result_1x2','HOME','')]
    assert home.decision=='QUALIFIED' and home.rank==1 and {'FRESH','MODEL_SUPPORTED','EVALUATED','QUALIFIED'}<=set(home.statuses)
    assert home.metrics['probability']==82.4 and home.metrics['lower']==80.0 and home.metrics['implied_probability']==78.74 and home.metrics['bookmaker_margin'] is not None
    draw=results[('football.full_time_result_1x2','DRAW','')]
    assert draw.decision=='REJECTED' and 'INSUFFICIENT_VALUE' in draw.reasons
    over=results[('football.total_goals_over_under','OVER','2.5')]
    assert over.decision=='UNSUPPORTED' and over.reasons==['NO_APPROVED_MODEL_FOR_MARKET'] and 'probability' not in over.metrics
    assert ('football.both_teams_to_score','YES','') in results
    assert all(r.odds_id!='unsourced' for r in results.values()), 'odds without source evidence are ignored'
    with factory.begin() as db:
        discovered=db.get(m.MarketDefinition,'football.discovered_corners_total_x')
        assert discovered.origin=='DISCOVERED'
        view=cat.fixture_view(db,'fixture',at=now)
    by={x['id']:x for x in view['markets']}
    assert {'REGISTERED','AVAILABLE','FRESH','MODEL_SUPPORTED','EVALUATED','QUALIFIED'}<=set(by['football.full_time_result_1x2']['statuses'])
    assert 'UNSUPPORTED' in by['football.total_goals_over_under']['statuses'] and by['football.total_goals_over_under']['lines']==['2.5']
    assert by['football.total_goals_over_under']['probability'] is None
    assert 'DISCOVERED' in by['football.discovered_corners_total_x']['statuses']
    assert not by['football.exact_score']['offered'], 'registered but not observed is never offered'
    assert view['best_fit'][0]['outcome']=='HOME' and view['coverage']['qualified']==1 and view['coverage']['offered']==4


def test_markets_missing_from_a_newer_batch_become_unavailable(store):
    factory,now=store
    with factory.begin() as db:cat.scan(db,'fixture',at=now)
    with factory.begin() as db:
        for i,(market,outcome,price) in enumerate([('1X2','HOME',1.25),('1X2','DRAW',5.5),('1X2','AWAY',13.0)]):
            db.add(m.Odds(id=f'n{i}',fixture_id='fixture',bookmaker='SportyBet',market_key=market,outcome_key=outcome,decimal_odds=price,observed_at=now-timedelta(minutes=1)));db.flush()
            db.add(m.MarketEvidence(odds_id=f'n{i}',observation_id='obs',source_id='source'))
    with factory.begin() as db:
        cat.scan(db,'fixture',at=now)
        statuses={a.definition_id:a.status for a in db.scalars(select(m.BookmakerMarketAvailability))}
        assert statuses['football.full_time_result_1x2']=='AVAILABLE' and statuses['football.both_teams_to_score']=='REMOVED'
        view={x['id']:x for x in cat.fixture_view(db,'fixture',at=now)['markets']}
        assert 'UNAVAILABLE' in view['football.both_teams_to_score']['statuses'] and not view['football.both_teams_to_score']['offered']


def test_scans_are_throttled_unless_odds_change(store):
    factory,now=store
    with factory.begin() as db:
        first=cat.scan(db,'fixture',at=now)
        assert cat.scan(db,'fixture',at=now+timedelta(minutes=1)).id==first.id
        assert cat.scan(db,'fixture',at=now+timedelta(minutes=1),force=True).id!=first.id
        db.add(m.ModelVersion(id='second',sport_id='sport',name='Other',version='1',status='ACTIVE',validation=APPROVED));db.flush()
        db.add(m.Prediction(fixture_id='fixture',feature_id='feature',model_id='second',market_key='BTTS',outcome_key='YES',probability=.6,predicted_at=now-timedelta(minutes=30)));db.flush()
        assert cat.scan(db,'fixture',at=now+timedelta(minutes=2)).summary['model_supported_outcomes']==4, 'new capability forces a rescan'


def test_existing_evaluate_stage_runs_the_scan(store):
    factory,now=store
    with factory.begin() as db:
        db.add(m.PipelineRun(id='run',fixture_id='fixture',mode='PAPER',status='PENDING',idempotency_key='k',context={}))
    with factory.begin() as db:
        with pytest.raises(operations.Waiting):operations.evaluate(db,db.get(m.PipelineRun,'run'),now)
        assert db.scalar(select(m.MarketScanRun.trigger).where(m.MarketScanRun.fixture_id=='fixture'))=='PIPELINE_EVALUATE'


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(catalogue_routes,'SessionLocal',factory);monkeypatch.setenv('SPORTS_ADMIN_TOKEN','t')
    app=FastAPI();app.include_router(catalogue_routes.router);client=TestClient(app)
    assert len(client.get('/api/v1/sports/markets/catalogue').json()['definitions'])>=400
    assert len(client.get('/api/v1/sports/markets/categories?sport=Football').json())==16
    assert client.get('/api/v1/sports/markets/fixtures/missing').status_code==404
    assert client.post('/api/v1/sports/markets/scans',json={'fixture_id':'fixture'}).status_code==403
    scan=client.post('/api/v1/sports/markets/scans',json={'fixture_id':'fixture'},headers={'X-Admin-Token':'t'})
    assert scan.status_code==201 and scan.json()['summary']['qualified']==1
    best=client.get('/api/v1/sports/markets/fixtures/fixture/best-fit').json()
    assert best['results'][0]['decision']=='QUALIFIED' and all(r['decision']!='UNSUPPORTED' for r in best['results'])
    assert client.get('/api/v1/sports/markets/fixtures/fixture/coverage').json()['offered']==4
    assert client.get('/api/v1/sports/markets/fixtures/fixture/odds').json()
    assert client.get(f"/api/v1/sports/markets/scans/{scan.json()['id']}").json()['results']


def test_capability_recorded_once_when_contract_and_forecasts_overlap(store):
    """Regression (live data): a binary home-win model that also published 1X2/HOME must yield one capability row."""
    factory,now=store
    from app.modules.prediction.service import FEATURE_NAMES
    with factory.begin() as db:
        db.get(m.ModelVersion,'active').validation={**APPROVED,'feature_names':list(FEATURE_NAMES)}
    with factory.begin() as db:
        cat.scan(db,'fixture',at=now,force=True)
        cat.scan(db,'fixture',at=now,force=True)
        rows=db.execute(select(m.MarketModelCapability.definition_id,m.MarketModelCapability.outcome_key)).all()
    assert sorted(rows)==sorted({('football.full_time_result_1x2',o) for o in ('HOME','DRAW','AWAY')})
