from datetime import timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.db import models as m
from app.modules.strategies import programme_engine as pe
from app.modules.tickets import builder,builder_routes
from app.modules.tickets.service import prepare_paper_ticket
from tests.test_accumulator_engine import store  # noqa: F401


@pytest.fixture
def reg(store):
    factory,now=store
    with factory.begin() as db:
        for k in builder.PROGRAMMES:db.add(m.Programme(key=k,configuration={}))
    return factory,now


def count(db,model):return db.scalar(select(func.count()).select_from(model))


def test_registers_engine_tickets_in_canonical_register_idempotently(reg):
    factory,now=reg
    with factory.begin() as db:
        pe.run_once(db,'singles',now);pe.run_once(db,'accumulator',now)
    with factory.begin() as db:
        rep=builder.register(db,now+timedelta(minutes=1))
        assert (rep['registered'],rep['rejected'],rep['linked'])==(4,0,0), '3 singles + 1 accumulator'
    with factory.begin() as db:
        assert builder.register(db,now+timedelta(minutes=2))=={'registered':0,'linked':0,'rejected':0,'errors':[]}, 'idempotent'
    with factory() as db:
        assert count(db,m.Ticket)==4 and count(db,m.Betslip)==4 and count(db,m.TicketLeg)==6
        o=builder.overview(db,now+timedelta(minutes=3))
        assert (o['recorded_items'],o['built'],o['rejected'],o['build_rate'])==(4,4,0,100.0) and o['avg_legs']==1.5
        assert o['lifecycle']=={'tickets':4,'betslips':4,'booking_codes':0} and o['latest']['ticket_id']


def test_late_registration_is_rejected_with_reason_not_fabricated(reg):
    factory,now=reg
    with factory.begin() as db:pe.run_once(db,'singles',now)
    with factory.begin() as db:
        rep=builder.register(db,now+timedelta(minutes=20))
        assert rep['registered']==0 and rep['rejected']==3
    with factory() as db:
        assert count(db,m.Ticket)==0
        o=builder.overview(db,now+timedelta(minutes=21))
        assert o['analytics']['rejection_reasons']=={'ODDS_NOT_FRESH':3} and o['build_rate']==0.0


def test_pipeline_prepared_ticket_is_linked_not_duplicated(reg):
    factory,now=reg
    with factory.begin() as db:
        run=pe.run_once(db,'singles',now)
        first=run.result['tickets'][0]['legs'][0]['qualification_id']
        prepared=prepare_paper_ticket(db,'singles',[first],at=now)
    with factory.begin() as db:
        rep=builder.register(db,now+timedelta(minutes=1))
        assert (rep['linked'],rep['registered'])==(1,2)
    with factory() as db:
        assert count(db,m.Ticket)==3
        assert any(x['ticket_id']==prepared['id'] and x['linked'] for x in builder.items(db))


def test_endpoints(reg,monkeypatch):
    factory,now=reg;monkeypatch.setattr(builder_routes,'SessionLocal',factory)
    with factory.begin() as db:pe.run_once(db,'singles',now);builder.register(db,now+timedelta(minutes=1))
    app=FastAPI();app.include_router(builder_routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/tickets/builder/overview').status_code==200
    assert client.get('/api/v1/sports/tickets/builder/register?status=REGISTERED&programme=singles').json()['total']==3
    assert [p['programme'] for p in client.get('/api/v1/sports/tickets/builder/programmes').json()['items']]==list(builder.PROGRAMMES)
