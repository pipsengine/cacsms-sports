from datetime import timedelta
import pytest
from sqlalchemy import select,func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.strategies import programme_engine as pe, singles_routes
from tests.test_accumulator_engine import store  # noqa: F401  (same qualified/stale/rejected fixture set)


def test_singles_run_builds_one_ticket_per_fixture_with_paper_stake(store):
    factory,now=store
    with factory.begin() as db:
        run=pe.run_once(db,'singles',now)
        tickets=run.result['tickets']
        assert run.status=='COMPLETED' and len(tickets)==3 and run.result['selections']==3
        assert all(len(t['legs'])==1 and t['paper_stake']==100 and t['potential_return']==round(100*t['combined_odds'],2) for t in tickets)
        assert len({t['legs'][0]['fixture_id'] for t in tickets})==3 and run.result['remaining_daily_capacity']==22
        assert run.result['excluded']['ODDS_NOT_FRESH']==1, 'same named-gate eligibility as the accumulator'


def test_no_repeat_fixture_same_day_and_cap_counts_tickets(store):
    factory,now=store
    with factory.begin() as db:pe.run_once(db,'singles',now)
    with factory.begin() as db:
        later=pe.run_once(db,'singles',now+timedelta(minutes=5))
        assert later.status=='BLOCKED' and later.result['excluded']['ALREADY_SELECTED_TODAY']==3
        assert later.result['reasons']==['INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES']
    with factory.begin() as db:
        db.add(m.StrategyRun(programme_key='singles',idempotency_key='bulk',status='COMPLETED',created_at=now,
                             result={'tickets':[{'legs':[{'fixture_id':f'x{i}','qualification_id':f'y{i}'}],'combined_odds':2.0} for i in range(22)]}))
    with factory.begin() as db:
        assert 'DAILY_CAP_REACHED' in pe.run_once(db,'singles',now+timedelta(minutes=10)).result['reasons']
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.StrategyRun).where(m.StrategyRun.programme_key=='singles',m.StrategyRun.status=='BLOCKED'))==2, 'blocked runs are always recorded'


def test_settlement_hit_rate_and_staked_roi(store):
    factory,now=store
    with factory.begin() as db:pe.run_once(db,'singles',now)
    with factory.begin() as db:
        for fx,home,away in (('f1','WON','LOST'),('f2','LOST','WON'),('f3','LOST','WON')):  # f3 selection is AWAY -> WON
            db.add(m.Result(fixture_id=fx,version=1,verified_at=now+timedelta(days=2),outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':home,'AWAY':away,'DRAW':'LOST'}}}))
    with factory() as db:
        o=pe.overview(db,'singles',now+timedelta(days=3))
        assert o['settled_tickets']==3 and o['success_rate']==pytest.approx(66.7,abs=.1)
        a=pe.analytics(db,'singles',now+timedelta(days=3))
        assert a['paper_roi']==pytest.approx(((1.6-1)*100+(2.1-1)*100-100)/300*100,abs=.1)


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(singles_routes,'SessionLocal',factory)
    with factory.begin() as db:pe.run_once(db,'singles',now)
    app=FastAPI();app.include_router(singles_routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/programmes/singles/configuration').json()['policy']['daily_cap']==25
    tickets=client.get('/api/v1/sports/programmes/singles/tickets').json()
    assert tickets['total']==3 and tickets['items'][0]['paper_stake']==100
    for path in ('overview','candidates','run-history','validation','analytics'):assert client.get('/api/v1/sports/programmes/singles/'+path).status_code==200
