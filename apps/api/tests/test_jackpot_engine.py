from datetime import timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.modules.strategies import programme_engine as pe, optimizer, jackpot_routes
from app.modules.strategies.optimizer import Candidate,select_tickets
from tests.test_accumulator_engine import store  # noqa: F401  (same qualified/stale/rejected fixture set)


def test_low_priced_pool_is_blocked_before_search_with_reachable_odds(store):
    factory,now=store
    with factory.begin() as db:
        run=pe.run_once(db,'jackpot',now)
        assert run.status=='BLOCKED' and run.result['reasons']==['JACKPOT_ODDS_UNREACHABLE']
        assert 1<run.result['reachable_odds']<2_000_000 and run.result['tickets']==[]
        assert pe.run_once(db,'jackpot',now+timedelta(minutes=5)).id==run.id, '15-minute idempotent bucket'


def test_completed_jackpot_ticket_uses_named_gates_and_bounds(store,monkeypatch):
    factory,now=store
    monkeypatch.setattr(optimizer,'JACKPOT_MIN_COMBINED_ODDS',Decimal('2'))
    monkeypatch.setattr(pe,'MIN_COMBINED_ODDS',{'jackpot':Decimal('2')})
    with factory.begin() as db:
        run=pe.run_once(db,'jackpot',now)
        assert run.status=='COMPLETED' and len(run.result['tickets'])==1
        legs=run.result['legs'];assert run.result['selections']==len(legs)==3 and len({l['fixture_id'] for l in legs})==3
        assert {l['fixture_id'] for l in legs}=={'f1','f2','f3'}, 'stale, market-risk, retired-model and non-positive-EV rows excluded'
        assert run.result['probability_lower_bound']<=run.result['probability_upper_bound'] and run.result['correlation_status']=='UNVERIFIED'


def test_optimizer_builds_a_real_high_odds_ticket_within_policy():
    cands=[Candidate(f'q{i}',f'f{i}',Decimal('3.0'),Decimal('0.4'),'1X2','AWAY',f'2026-11-2{i%9}T15:00:00+00:00') for i in range(25)]
    [ticket]=select_tickets(cands,'jackpot',limit=1)
    odds=Decimal(ticket['combined_odds'])
    assert Decimal('2000000')<=odds<=Decimal('100000000') and len(ticket['qualification_ids'])==16
    assert select_tickets([Candidate(f'q{i}',f'f{i}',Decimal('2.0'),Decimal('0.6'),'1X2','HOME','2026-11-20T15:00:00+00:00') for i in range(25)],'jackpot')==[], \
        'never pads a ticket: 2.0^20 < 2,000,000 within the 20-candidate pool'


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(jackpot_routes,'SessionLocal',factory)
    with factory.begin() as db:pe.run_once(db,'jackpot',now)
    app=FastAPI();app.include_router(jackpot_routes.router);client=TestClient(app)
    cfg=client.get('/api/v1/sports/programmes/jackpot/configuration').json()['policy']
    assert (cfg['min_legs'],cfg['max_legs'],cfg['max_odds'],cfg['daily_cap'],cfg['min_combined_odds'])==(2,30,100_000_000,5,2_000_000)
    assert client.get('/api/v1/sports/programmes/jackpot/run-history').json()['items'][0]['status']=='BLOCKED'
    for path in ('overview','candidates','tickets','validation','analytics','health'):assert client.get('/api/v1/sports/programmes/jackpot/'+path).status_code==200
