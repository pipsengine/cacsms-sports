from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import create_engine,select,func,event,DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.strategies import accumulator as acc, accumulator_routes

APPROVED={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True}
PASS={g:'PASS' for g in acc.REQUIRED_GATES+acc.OPTIONAL_GATES}


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    def aware(target,*_):
        for col in target.__table__.columns:
            v=target.__dict__.get(col.key)
            if isinstance(col.type,DateTime) and isinstance(v,datetime) and v.tzinfo is None:target.__dict__[col.key]=v.replace(tzinfo=timezone.utc)
    event.listen(Base,'load',aware,propagate=True)
    factory=sessionmaker(bind=engine)
    now=datetime(2026,11,16,12,1,tzinfo=timezone.utc)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='Bundesliga',country='Germany'))
        db.add(m.Source(id='src',name='Authorized',enabled=True,permission='AUTHORIZED'))
        db.add(m.ModelVersion(id='model',sport_id='sport',name='M',version='1',status='ACTIVE',validation=APPROVED))
        db.add(m.ModelVersion(id='old',sport_id='sport',name='Old',version='0',status='RETIRED',validation=APPROVED));db.flush()
        db.add(m.Observation(id='obs',source_id='src',observed_at=now,source_url='https://p.example',content_hash='o'*64,payload={}))
        rows=[('f1','HOME',.70,1.60,PASS,'model',3),('f2','HOME',.60,1.90,PASS,'model',4),('f3','AWAY',.55,2.10,PASS,'model',2),
              ('f4','HOME',.70,1.60,PASS,'model',40),('f5','HOME',.70,1.60,{**PASS,'market_risk':'FAIL'},'model',2),('f6','HOME',.70,1.60,PASS,'old',2),('f7','HOME',.50,1.50,PASS,'model',2)]
        for fx,outcome,p,odds,gates,model,age in rows:
            db.add(m.Fixture(id=fx,competition_id='league',home_name=fx+'H',away_name=fx+'A',kickoff_at=now+timedelta(days=1)));db.flush()
            db.add(m.Research(id='r'+fx,fixture_id=fx,version=1,status='VERIFIED',sections={},evidence_ids=[],created_at=now))
            db.add(m.Feature(id='ft'+fx,research_id='r'+fx,cutoff_at=now,features={}))
            db.add(m.Prediction(id='p'+fx,fixture_id=fx,feature_id='ft'+fx,model_id=model,market_key='1X2',outcome_key=outcome,probability=p,predicted_at=now-timedelta(hours=1)))
            db.add(m.Odds(id='o'+fx,fixture_id=fx,bookmaker='Book',market_key='1X2',outcome_key=outcome,decimal_odds=odds,observed_at=now-timedelta(minutes=age)));db.flush()
            db.add(m.MarketEvidence(odds_id='o'+fx,observation_id='obs',source_id='src'))
            db.add(m.Qualification(id='q'+fx,prediction_id='p'+fx,odds_id='o'+fx,decision='QUALIFIED',decided_at=now,gates={**gates,'reason_codes':[],'metrics':{}}))
    yield factory,now
    event.remove(Base,'load',aware);engine.dispose()


def test_eligibility_excludes_with_reasons(store):
    factory,now=store
    with factory() as db:
        rows,excluded=acc.eligible(db,now)
    assert [r['fixture_id'] for r in rows]==['f3','f2','f1'], 'ranked by EV'
    assert excluded=={'ODDS_NOT_FRESH':1,'QUALITY_GATE_NOT_PASSED':1,'MODEL_NOT_ACTIVE_APPROVED':1,'NO_POSITIVE_EV':1}


def test_run_composes_bounded_paper_accumulator_idempotently(store):
    factory,now=store
    with factory.begin() as db:
        run=acc.run_once(db,now)
        assert run.status=='COMPLETED' and run.result['selections']==3 and len({l['fixture_id'] for l in run.result['legs']})==3
        assert run.result['combined_odds']==pytest.approx(1.6*1.9*2.1,rel=1e-6)
        assert run.result['probability_upper_bound']==pytest.approx(.55) and run.result['probability_lower_bound']==pytest.approx(0.0), 'bounds, never a product'
        assert acc.run_once(db,now+timedelta(minutes=5)).id==run.id, 'same 15-minute bucket'
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.StrategyRun))==1


def test_blocked_with_reasons_and_daily_cap(store):
    factory,now=store
    with factory.begin() as db:
        for fx in ('f1','f2'):db.get(m.Qualification,'q'+fx).decision='REJECTED'
    with factory.begin() as db:
        run=acc.run_once(db,now)
        assert run.status=='BLOCKED' and run.result['reasons']==['INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES']
    with factory.begin() as db:
        for fx in ('f1','f2'):db.get(m.Qualification,'q'+fx).decision='QUALIFIED'
        for i in range(acc.policy()['daily_cap']):db.add(m.StrategyRun(programme_key='accumulator',idempotency_key=f'x{i}',status='COMPLETED',created_at=now-timedelta(minutes=30),result={}))
    with factory.begin() as db:
        assert 'DAILY_CAP_REACHED' in acc.run_once(db,now+timedelta(minutes=15)).result['reasons']


def test_settlement_and_analytics_only_from_verified_results(store):
    factory,now=store
    with factory.begin() as db:run_id=acc.run_once(db,now).id
    with factory() as db:
        a=acc.analytics(db,now)
        assert a['completion_rate']==100.0 and a['settled']==0 and a['paper_roi'] is None
    with factory.begin() as db:
        for fx,state in (('f1','WON'),('f2','WON'),('f3','WON')):
            db.add(m.Result(fixture_id=fx,version=1,verified_at=now+timedelta(days=2),outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':state,'AWAY':state,'DRAW':'LOST'}}}))
    with factory() as db:
        assert acc.settle(db,db.get(m.StrategyRun,run_id))=='WON'
        a=acc.analytics(db,now+timedelta(days=3))
        assert a['settled']==1 and a['paper_hit_rate']==100.0 and a['paper_roi']==pytest.approx((1.6*1.9*2.1-1)*100,rel=1e-3)


def test_overview_and_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(accumulator_routes,'SessionLocal',factory)
    with factory.begin() as db:acc.run_once(db,now)
    with factory() as db:
        o=acc.overview(db,now)
        assert (o['recorded_runs'],o['completed'],o['blocked'],o['avg_selections'])==(1,1,0,3.0) and o['readiness']=='READY_FOR_QUALIFIED_DATA'
        v={x['key']:x['pass_rate'] for x in o['validation']['items']}
        assert v['source_integrity']==100.0 and v['ticket_controls']<100.0
        assert {s['key']:s['status'] for s in o['pipeline']}['publish']=='DONE'
    app=FastAPI();app.include_router(accumulator_routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/programmes/accumulator/configuration').json()['policy']['max_legs']==12
    for path in ('overview','candidates','run-history','validation','analytics'):assert client.get('/api/v1/sports/programmes/accumulator/'+path).status_code==200
