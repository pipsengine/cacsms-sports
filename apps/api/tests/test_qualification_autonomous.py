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
        assert item['selection']=='Home' and item['edge']==round(82.4-100/1.27,2) and item['confidence']=='High'
        comp=aq.comparison(db,at=now)
        assert comp[0]['status']=='PRICED' and any(r['status']=='AWAITING_PRICE' and r['selection']=='Yes' for r in comp)
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
    for path in ('rejections','gates','history','comparison'):assert client.get('/api/v1/sports/qualification/'+path).status_code==200
