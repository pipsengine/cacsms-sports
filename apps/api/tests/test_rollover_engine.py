from datetime import datetime,timedelta,timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.strategies import programme_engine as pe, rollover_routes
from tests.test_accumulator_engine import store  # noqa: F401  (f1 HOME @1.60 p.70 is the only in-band selection)


def result(db,now,fx,state):
    db.add(m.Result(fixture_id=fx,version=1,verified_at=now+timedelta(days=1,hours=3),outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':state}}}))


def test_daily_period_is_0900_lagos_with_catch_up():
    assert pe.period_start('rollover',datetime(2026,11,16,12,1,tzinfo=timezone.utc))==datetime(2026,11,16,8,0,tzinfo=timezone.utc)
    assert pe.period_start('rollover',datetime(2026,11,16,7,59,tzinfo=timezone.utc))==datetime(2026,11,15,8,0,tzinfo=timezone.utc)


def test_first_step_starts_autonomous_plan_in_target_band(store):
    factory,now=store
    with factory.begin() as db:
        run=pe.run_once(db,'rollover',now)
        res=run.result;[t]=res['tickets']
        assert run.status=='COMPLETED' and t['legs'][0]['fixture_id']=='f1' and t['paper_stake']==1000 and t['potential_return']==1600
        assert res['plan']['day']==1 and res['plan']['bankroll']==1000 and res['excluded']['OUTSIDE_TARGET_BAND']==2
        assert '_at' not in t['legs'][0]
        assert pe.run_once(db,'rollover',now+timedelta(hours=5)).id==run.id, 'one run per daily period'


def test_never_compounds_on_unverified_step_then_advances_on_verified_win(store):
    factory,now=store
    with factory.begin() as db:pe.run_once(db,'rollover',now)
    with factory.begin() as db:
        blocked=pe.run_once(db,'rollover',now+timedelta(days=1))
        assert blocked.status=='BLOCKED' and 'AWAITING_SETTLEMENT' in blocked.result['reasons']
    with factory.begin() as db:result(db,now,'f1','WON')
    with factory() as db:
        st=pe.rollover_state(db,now+timedelta(days=2))
        assert (st['day'],st['bankroll'],st['previous'],st['status'])==(2,1600.0,'WON','ACTIVE')
        assert pe.overview(db,'rollover',now+timedelta(days=2))['leg_hit_rate']==100.0


def test_loss_stops_plan_and_void_keeps_day(store):
    factory,now=store
    with factory.begin() as db:pe.run_once(db,'rollover',now)
    with factory.begin() as db:result(db,now,'f1','LOST')
    with factory() as db:
        st=pe.rollover_state(db,now+timedelta(days=2))
        assert st['day']==1 and st['bankroll']==1000 and st['ended']=={'plan_id':'plan-20261116','status':'STOPPED','day':1}
        assert st['plan_id']=='plan-20261118', 'a fresh plan starts autonomously'


def test_no_verified_result_after_seven_days_counts_as_void(store):
    factory,now=store
    with factory.begin() as db:pe.run_once(db,'rollover',now)
    with factory() as db:
        assert pe.rollover_state(db,now+timedelta(days=3))['status']=='AWAITING_SETTLEMENT'
        st=pe.rollover_state(db,now+timedelta(days=9))
        assert (st['status'],st['previous'],st['day'],st['bankroll'])==('ACTIVE','VOID',1,1000)


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(rollover_routes,'SessionLocal',factory)
    with factory.begin() as db:pe.run_once(db,'rollover',now)
    app=FastAPI();app.include_router(rollover_routes.router);client=TestClient(app)
    cfg=client.get('/api/v1/sports/programmes/rollover/configuration').json()['policy']
    assert (cfg['min_legs'],cfg['max_legs'],cfg['daily_cap'],cfg['target_band'],cfg['plan_days'],cfg['schedule'])==(1,1,1,[1.5,1.75],30,'Daily, 09:00 WAT')
    assert client.get('/api/v1/sports/programmes/rollover/plan').json()['status'] in ('AWAITING_SETTLEMENT','ACTIVE')
    for path in ('overview','candidates','run-history','tickets','validation','analytics','health'):assert client.get('/api/v1/sports/programmes/rollover/'+path).status_code==200
