from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.qualification import autonomous as aq, routes_autonomous

APPROVED={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True,'holdout_metrics':{'brier':0.2}}


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    now=datetime.now(timezone.utc);at=now-timedelta(hours=1)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='Bundesliga',country='Germany'));db.flush()
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Fixture(id='fixture',competition_id='league',home_name='Home',away_name='Away',kickoff_at=now+timedelta(days=1)))
        db.add(m.Fixture(id='past',competition_id='league',home_name='Old',away_name='Away',kickoff_at=now-timedelta(days=2)));db.flush()
        db.add(m.Observation(id='obs',source_id='source',fixture_id='fixture',observed_at=at,source_url='https://p.example/e',content_hash='o'*64,payload={'section':'market_odds','data':{}}))
        for fx in ('fixture','past'):
            db.add(m.Research(id='r'+fx,fixture_id=fx,version=1,status='VERIFIED',sections={},evidence_ids=['obs'],created_at=at+timedelta(minutes=1)))
            db.add(m.Feature(id='f'+fx,research_id='r'+fx,cutoff_at=at+timedelta(minutes=2),features={}))
        db.add(m.ModelVersion(id='model',sport_id='sport',name='Market model',version='1',status='ACTIVE',validation=APPROVED));db.flush()
        forecasts=[('1X2','HOME',.824,.80,.84),('1X2','DRAW',.121,.10,.14),('1X2','AWAY',.055,.04,.07),('OU_2.5','OVER',.70,.66,.74),('BTTS','YES',.55,.5,.6)]
        for fx in ('fixture','past'):
            for market,outcome,p,lo,hi in forecasts:
                db.add(m.Prediction(id=f'{fx}-{market}-{outcome}',fixture_id=fx,feature_id='f'+fx,model_id='model',market_key=market,outcome_key=outcome,probability=p,
                                    predicted_at=at+timedelta(minutes=3) if fx=='fixture' else now-timedelta(days=3),details={'interval':{'lower':lo,'upper':hi},'skill':.1}))
        quotes=[('fixture','1X2','HOME',1.27),('fixture','1X2','DRAW',5.40),('fixture','1X2','AWAY',12.0),('fixture','OU_2.5','OVER',1.60),('past','1X2','HOME',1.2)]
        for i,(fx,market,outcome,price) in enumerate(quotes):
            db.add(m.Odds(id=f'q{i}',fixture_id=fx,bookmaker='Book',market_key=market,outcome_key=outcome,decimal_odds=price,observed_at=now-timedelta(minutes=5)));db.flush()
            db.add(m.MarketEvidence(odds_id=f'q{i}',observation_id='obs',source_id='source'))
        from odds_evidence_helpers import attach_price_evidence
        attach_price_evidence(db,exclude=('unsourced',))
    yield factory,now
    engine.dispose()


def decisions(factory):
    with factory() as db:
        return {(p.market_key,p.outcome_key):(q.decision,q.gates) for q,p in db.execute(select(m.Qualification,m.Prediction).join(m.Prediction,m.Prediction.id==m.Qualification.prediction_id))}


def test_cycle_applies_every_gate_and_records_reasons(store):
    factory,now=store
    report=aq.cycle(factory,at=now)
    assert report['evaluated']==4 and report['qualified']==1 and report['pending_no_price']==1, report
    d=decisions(factory)
    decision,gates=d[('1X2','HOME')]
    assert decision=='QUALIFIED' and all(gates[g]=='PASS' for g in aq.GATES) and gates['metrics']['overround']>1
    assert d[('1X2','DRAW')][0]=='REJECTED' and 'INSUFFICIENT_VALUE' in d[('1X2','DRAW')][1]['reason_codes']
    ou=d[('OU_2.5','OVER')]
    assert ou[0]=='REJECTED' and ou[1]['market_risk']=='FAIL' and 'INCOMPLETE_MARKET' in ou[1]['reason_codes'], 'one-sided market never qualifies'
    assert ('BTTS','YES') not in d, 'no price -> pending, no decision'
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.Qualification).join(m.Prediction).where(m.Prediction.fixture_id=='past'))==0, 'kicked-off fixtures are not evaluated'


def test_cycle_is_idempotent_and_new_prices_create_new_decisions(store):
    factory,now=store
    aq.cycle(factory,at=now)
    assert aq.cycle(factory,at=now)['evaluated']==0
    with factory.begin() as db:
        db.add(m.Odds(id='new',fixture_id='fixture',bookmaker='Book',market_key='1X2',outcome_key='HOME',decimal_odds=1.30,observed_at=now-timedelta(minutes=1)));db.flush()
        db.add(m.MarketEvidence(odds_id='new',observation_id='obs',source_id='source'))
    assert aq.cycle(factory,at=now)['evaluated']==1


def test_read_models(store):
    factory,now=store
    aq.cycle(factory,at=now)
    with factory() as db:
        s=aq.summary(db,now)
        assert (s['evaluated'],s['qualified'],s['rejected'],s['pending'])==(4,1,3,1) and s['qualification_rate']==25.0
        assert {x['key']:x['status'] for x in s['pipeline']}['qualify']=='DONE'
        gates={g['key']:g for g in s['gates']}
        assert gates['market_risk']['pass_rate']==75.0 and gates['research']['pass_rate']==100.0
        b=aq.breakdown(db)
        assert b['rejected']==3 and {c['key']:c['count'] for c in b['categories']}['negative_ev']==2 and {c['key']:c['count'] for c in b['categories']}['risk']==1
        rows=aq._rows(db,'QUALIFIED')
        item=aq.decision_dict(db,*rows[0])
        assert item['selection']=='Home (1)' and item['edge']==round(82.4-100/1.27,2) and item['confidence']=='High'
        comp=aq.comparison(db,at=now)
        assert comp[0]['status']=='PRICED' and any(r['status']=='AWAITING_PRICE' and r['selection']=='Yes' for r in comp)
        from app.modules.market_scanner.service import selection_name,market_name
        assert selection_name('OU_2.5','OVER')=='Over 2.5' and market_name('AWAY_OU_0.5')=='Away Over/Under 0.5'
        assert aq.history(db,at=now)[0]['qualified']==1


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes_autonomous,'SessionLocal',factory)
    aq.cycle(factory,at=now)
    app=FastAPI();app.include_router(routes_autonomous.router);client=TestClient(app)
    body=client.get('/api/v1/sports/qualification/decision-details?status=REJECTED&limit=2').json()
    assert body['total']==3 and len(body['items'])==2
    assert client.get('/api/v1/sports/qualification/decision-details?status=MAYBE').status_code==422
    assert client.get('/api/v1/sports/qualification/summary').json()['evaluated']==4
    assert client.get('/api/v1/sports/qualification/filters').json()['countries']==['Germany']
    with factory.begin() as db:
        db.add(m.Competition(id='br',sport_id='sport',name='Brazilian Serie A',country='Brazil'));db.flush()
        db.add(m.Fixture(id='br-fx',competition_id='br',home_name='Flamengo',away_name='Palmeiras',kickoff_at=now+timedelta(days=2),status='SCHEDULED'))
    filters=client.get('/api/v1/sports/qualification/filters').json()
    stats={c['country']:c for c in filters['country_stats']}
    assert filters['countries'][0]=='Germany' and 'Brazil' in filters['countries'], 'countries without forecasts are listed, forecasted first'
    assert stats['Brazil']['fixtures']==1 and stats['Brazil']['forecast_fixtures']==0
    assert next(c for c in filters['competitions'] if c['id']=='br')['verified_research']==0
    for path in ('rejections','gates','history','comparison'):assert client.get('/api/v1/sports/qualification/'+path).status_code==200


def test_grouped_decisions_page_by_fixture_without_splitting(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes_autonomous,'SessionLocal',factory)
    aq.cycle(factory,at=now)
    app=FastAPI();app.include_router(routes_autonomous.router);client=TestClient(app)
    flat=client.get('/api/v1/sports/qualification/decision-details?status=ALL&limit=200').json()
    body=client.get('/api/v1/sports/qualification/decision-details?status=ALL&group=fixture&limit=1').json()
    fixtures={i['fixture_id'] for i in flat['items']}
    assert body['total']==len(fixtures) and body['decisions']==flat['total'] and len(body['groups'])==1
    group=body['groups'][0]
    assert len(group['items'])==group['markets']==sum(i['fixture_id']==group['fixture_id'] for i in flat['items'])
    assert group['qualified']+group['rejected']+group['pending']==group['markets']
    assert group['best']['decision']=='QUALIFIED' if group['qualified'] else True
    assert client.get('/api/v1/sports/qualification/decision-details?group=market').status_code==422


def test_grouped_decisions_list_markets_the_model_does_not_forecast(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes_autonomous,'SessionLocal',factory)
    rejected=lambda skill:{'approved':False,'reasons':['DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE'],'skill':skill,'calibration_error':0.02}
    with factory.begin() as db:
        db.add(m.ModelVersion(id='poisson',sport_id='sport',name='Poisson market model',version='2',status='ACTIVE',
            validation={**APPROVED,'model_type':'poisson_market','markets':{'ODD_EVEN|ODD':rejected(-0.0004),'ODD_EVEN|EVEN':rejected(-0.0004),
                        'OU_0.5|OVER':rejected(-0.0007),'BTTS|YES':rejected(-0.01),'CS|0-0':rejected(-0.1),'1X2|HOME':{'approved':True,'reasons':[],'skill':0.11}}}))
    aq.cycle(factory,at=now)
    app=FastAPI();app.include_router(routes_autonomous.router);client=TestClient(app)
    group=client.get('/api/v1/sports/qualification/decision-details?status=ALL&group=fixture&limit=10').json()['groups'][0]
    listed={(x['market_key'],x['outcome_key']) for x in group['not_forecast']}
    # BTTS has a forecast for this fixture (from another model), correct scores and approved outcomes are not listed.
    assert listed=={('ODD_EVEN','ODD'),('ODD_EVEN','EVEN'),('OU_0.5','OVER')}
    item=next(x for x in group['not_forecast'] if x['market_key']=='OU_0.5')
    assert item['decision']=='NOT_FORECAST' and item['skill']==-0.07 and 'base-rate' in item['reasons'][0]
    assert group['markets']==len(group['items']), 'not-forecast rows are not counted as evaluated selections'


def test_pending_forecasts_are_rows_not_decisions_and_feed_price_independent_gates(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes_autonomous,'SessionLocal',factory)
    aq.cycle(factory,at=now)
    app=FastAPI();app.include_router(routes_autonomous.router);client=TestClient(app)
    pending=client.get('/api/v1/sports/qualification/decision-details?status=PENDING').json()
    assert pending['total']==1 and pending['items'][0]['decision']=='PENDING' and pending['items'][0]['selection']=='Yes'
    assert pending['items'][0]['odds'] is None and pending['items'][0]['edge'] is None and pending['items'][0]['confidence']=='High'
    everything=client.get('/api/v1/sports/qualification/decision-details?status=ALL&limit=3&offset=3').json()
    assert everything['total']==5 and [i['decision'] for i in everything['items']][-1]=='PENDING', 'decisions first, then pending'
    assert client.get('/api/v1/sports/qualification/decision-details?status=PENDING&search=btts').json()['total']==1
    assert client.get('/api/v1/sports/qualification/decision-details?status=PENDING&search=corners').json()['total']==0
    with factory() as db:
        s=aq.summary(db,now)
        assert s['evaluated']==4 and s['pending']==1, 'pending never counted as evaluated'
        gates={g['key']:g for g in s['gates']}
        assert (gates['research']['evaluated'],gates['research']['pass_rate'])==(5,100.0)
        assert gates['odds_freshness']['evaluated']==5 and gates['odds_freshness']['pass_rate']==80.0
        assert gates['value']['evaluated']==4, 'price-dependent gates use decisions only'
        assert s['trend']['evaluated'] is None, 'no prior window -> no fabricated trend'


def test_opportunities_and_evidence(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes_autonomous,'SessionLocal',factory)
    aq.cycle(factory,at=now)
    app=FastAPI();app.include_router(routes_autonomous.router);client=TestClient(app)
    q=client.get('/api/v1/sports/qualification/opportunities').json()
    assert q['total']==1 and q['items'][0]['decision']=='QUALIFIED' and q['items'][0]['selection']=='Home (1)'
    assert client.get('/api/v1/sports/qualification/opportunities?min_probability=90').json()['total']==0, 'policy filter'
    assert client.get('/api/v1/sports/qualification/opportunities?min_ev=50').json()['total']==0
    everything=client.get('/api/v1/sports/qualification/opportunities?only_qualified=false&limit=50').json()
    assert everything['total']==5 and {i['decision'] for i in everything['items']}=={'QUALIFIED','REJECTED','PENDING'}
    ev=client.get(f"/api/v1/sports/qualification/opportunities/{q['items'][0]['id']}/evidence").json()
    assert ev['rationale']['status']=='QUALIFIED' and ev['rationale']['text'].startswith('Passes all quality gates')
    assert ev['model']['name']=='Market model 1' and ev['research']['evidence_items']==1
    pending=next(i for i in everything['items'] if i['decision']=='PENDING')
    pe=client.get(f"/api/v1/sports/qualification/opportunities/{pending['id']}/evidence").json()
    assert pe['rationale']['status']=='PENDING' and 'cannot qualify yet' in pe['rationale']['text']
    rejected=next(i for i in everything['items'] if i['decision']=='REJECTED')
    assert client.get(f"/api/v1/sports/qualification/opportunities/{rejected['id']}/evidence").json()['rationale']['text'].startswith('Failed:')
    assert client.get('/api/v1/sports/qualification/opportunities/missing/evidence').status_code==404
