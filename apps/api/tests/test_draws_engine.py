from datetime import datetime,timedelta,timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.strategies import programme_engine as pe, draws_routes
from tests.test_accumulator_engine import store  # noqa: F401  (f1-f7 home/away set; none are draws)


def add(db,now,fx,p,odds,market='1X2',outcome='DRAW'):
    db.add(m.Fixture(id=fx,competition_id='league',home_name=fx+'H',away_name=fx+'A',kickoff_at=now+timedelta(days=2)));db.flush()
    db.add(m.Research(id='r'+fx,fixture_id=fx,version=1,status='VERIFIED',sections={},evidence_ids=[],created_at=now))
    db.add(m.Feature(id='ft'+fx,research_id='r'+fx,cutoff_at=now,features={}))
    db.add(m.Prediction(id='p'+fx,fixture_id=fx,feature_id='ft'+fx,model_id='model',market_key=market,outcome_key=outcome,probability=p,predicted_at=now-timedelta(hours=1)))
    db.add(m.Odds(id='o'+fx,fixture_id=fx,bookmaker='Book',market_key=market,outcome_key=outcome,decimal_odds=odds,observed_at=now-timedelta(minutes=3)));db.flush()
    db.add(m.MarketEvidence(odds_id='o'+fx,observation_id='obs',source_id='src'))
    gates={g:'PASS' for g in pe.REQUIRED_GATES+pe.OPTIONAL_GATES}
    db.add(m.Qualification(id='q'+fx,prediction_id='p'+fx,odds_id='o'+fx,decision='QUALIFIED',decided_at=now,gates={**gates,'reason_codes':[],'metrics':{}}))


@pytest.fixture
def draws(store):
    factory,now=store
    with factory.begin() as db:
        for i in range(12):add(db,now,f'd{i:02d}',.33+i*.001,3.4)        # edge ≈ 3.6 pp
        add(db,now,'low',.30,3.4)                                           # edge 0.6 pp < 1.5 pp
        add(db,now,'ht',.45,2.4,market='HT_1X2')                            # half-time draw, not full-time
        from odds_evidence_helpers import attach_price_evidence
        attach_price_evidence(db,source_id='src',exclude=tuple('of'+str(i) for i in range(1,8)))
    return factory,now


def test_weekly_bucket_is_saturday_0900_lagos_and_catches_up():
    monday=datetime(2026,11,16,12,1,tzinfo=timezone.utc)
    assert pe.period_start('draws',monday)==datetime(2026,11,14,8,0,tzinfo=timezone.utc)
    assert pe.period_start('draws',datetime(2026,11,21,7,59,tzinfo=timezone.utc))==datetime(2026,11,14,8,0,tzinfo=timezone.utc)
    assert pe.period_start('draws',datetime(2026,11,21,8,0,tzinfo=timezone.utc))==datetime(2026,11,21,8,0,tzinfo=timezone.utc)


def test_draw_tickets_per_leg_target_without_reuse_and_within_max_odds(draws):
    factory,now=draws
    with factory.begin() as db:
        run=pe.run_once(db,'draws',now)
        res=run.result;tickets=res['tickets']
        assert run.status=='COMPLETED' and [len(t['legs']) for t in tickets]==[2,5], '8 and 10 legs of ~3.4 exceed max odds 1000'
        ids=[l['qualification_id'] for t in tickets for l in t['legs']];assert len(ids)==len(set(ids)), 'no selection reused across tickets'
        assert all(l['market_key']=='1X2' and l['outcome_key']=='DRAW' for t in tickets for l in t['legs'])
        assert all(t['combined_odds']<=1000 and t['probability_lower_bound']<=t['probability_upper_bound'] for t in tickets)
        assert res['excluded']['NOT_FULL_TIME_DRAW']==4 and res['excluded']['INSUFFICIENT_EDGE']==1, 'f1-f3 + half-time draw; low edge'
        assert pe.run_once(db,'draws',now+timedelta(days=2)).id==run.id, 'one run per weekly period'
    with factory() as db:
        assert pe.overview(db,'draws',now)['next_run_at']=='2026-11-21T08:00:00+00:00'


def test_blocked_without_draws_and_draw_rate_from_verified_results(store,draws):
    factory,now=draws
    with factory.begin() as db:
        assert pe.run_once(db,'draws',now).status=='COMPLETED'
    with factory() as db:
        legs=[l for t in db.query(m.StrategyRun).filter_by(programme_key='draws').one().result['tickets'] for l in t['legs']]
    with factory.begin() as db:
        for i,l in enumerate(legs[:4]):  # 1 of 4 settled legs ended in a draw
            state='WON' if i==0 else 'LOST'
            db.add(m.Result(fixture_id=l['fixture_id'],version=1,verified_at=now+timedelta(days=3),outcome={'status':'FINAL','outcomes':{'1X2':{'DRAW':state}}}))
    with factory() as db:
        o=pe.overview(db,'draws',now+timedelta(days=4))
        assert o['leg_hit_rate']==25.0 and o['analytics']['leg_hit_rate']==25.0


def test_blocked_run_records_reason(store):
    factory,now=store
    with factory.begin() as db:
        run=pe.run_once(db,'draws',now)
        assert run.status=='BLOCKED' and run.result['reasons']==['INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES'] and run.result['excluded']['NOT_FULL_TIME_DRAW']==3


def test_endpoints(draws,monkeypatch):
    factory,now=draws;monkeypatch.setattr(draws_routes,'SessionLocal',factory)
    with factory.begin() as db:pe.run_once(db,'draws',now)
    app=FastAPI();app.include_router(draws_routes.router);client=TestClient(app)
    cfg=client.get('/api/v1/sports/programmes/draws/configuration').json()['policy']
    assert (cfg['min_legs'],cfg['max_legs'],cfg['max_odds'],cfg['daily_cap'],cfg['leg_targets'],cfg['schedule'])==(2,10,1000,5,[2,5,8,10],'Weekly, Saturday 09:00 WAT')
    assert client.get('/api/v1/sports/programmes/draws/tickets').json()['total']==2
    for path in ('overview','candidates','run-history','validation','analytics','health'):assert client.get('/api/v1/sports/programmes/draws/'+path).status_code==200
