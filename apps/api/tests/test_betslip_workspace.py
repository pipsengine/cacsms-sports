from datetime import timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.db import models as m
from app.modules.tickets import workspace_routes as ws
from app.modules.tickets.service import prepare_paper_ticket
from tests.test_accumulator_engine import store  # noqa: F401


@pytest.fixture
def slip(store):
    factory,now=store
    with factory.begin() as db:
        db.add(m.Programme(id='singles',key='singles',configuration={}))
        db.flush()
        prepared=prepare_paper_ticket(db,'singles',['qf1'],at=now)
    return factory,now,prepared


def test_empty_summary_does_not_invent_records_or_readiness(store):
    factory,now=store
    with factory() as db:
        overview=ws.overview(db,now)
        assert overview['summary']['recorded']==0 and overview['summary']['preparation_rate'] is None
        assert overview['summary']['average_legs'] is None
        assert overview['readiness']['status']=='AWAITING_QUALIFIED_TICKETS'
        assert overview['readiness']['provider_booking']=='NOT_CONFIGURED'
        assert overview['pipeline'][-1]['status']=='NOT_CONFIGURED'
        assert all(c['rate'] is None for c in overview['checks'])


def test_prepared_does_not_mean_verified_or_booked(slip):
    factory,now,prepared=slip
    with factory() as db:
        overview=ws.overview(db,now)
        assert overview['summary']==dict(recorded=1,prepared=1,failed=0,preparation_rate=100.0,average_legs=1.0)
        assert overview['readiness']['status']=='AWAITING_VERIFICATION'
        assert overview['rows'][0]['ticket_id']==prepared['id']
        assert overview['checks'][0]['rate']==100 and overview['checks'][1]['rate']==0
        assert db.scalar(select(func.count()).select_from(m.BookingCode))==0


def verified(factory,now,prepared):
    with factory.begin() as db:
        db.get(m.Betslip,prepared['betslip_id']).status='PAPER_VERIFIED'
        db.get(m.Ticket,prepared['id']).status='PAPER_VERIFIED'
        db.add(m.TicketVerification(ticket_id=prepared['id'],status='PAPER_VERIFIED',verified_at=now,reason_codes=[],evidence={'scope':'PAPER_BETSLIP','expires_at':(now+timedelta(minutes=5)).isoformat()}))


def test_current_readiness_expires_and_rechecks_canonical_legs(slip):
    factory,now,prepared=slip;verified(factory,now,prepared)
    with factory() as db:
        assert ws.overview(db,now)['readiness']['status']=='PAPER_VERIFIED'
        assert ws.overview(db,now+timedelta(minutes=6))['readiness']['status']=='AWAITING_VERIFICATION'
    with factory.begin() as db:db.get(m.Qualification,'qf1').decision='REJECTED'
    with factory() as db:assert ws.overview(db,now)['readiness']['status']=='AWAITING_VERIFICATION'


def test_tampered_slip_never_claims_current_verification(slip):
    factory,now,prepared=slip;verified(factory,now,prepared)
    with factory.begin() as db:
        record=db.get(m.Betslip,prepared['betslip_id']);record.combined_odds=999
    with factory() as db:assert ws.overview(db,now)['readiness']['status']=='AWAITING_VERIFICATION'


def test_read_endpoints_are_read_only_and_have_real_audit(slip,monkeypatch):
    factory,now,prepared=slip;monkeypatch.setattr(ws,'SessionLocal',factory)
    app=FastAPI();app.include_router(ws.router);client=TestClient(app)
    response=client.get('/api/v1/sports/betslip-preparation/overview')
    assert response.status_code==200 and response.json()['mode']=='PAPER'
    detail=client.get('/api/v1/sports/betslip-preparation/'+prepared['betslip_id']).json()
    assert detail['audit'][0]['event']=='paper_ticket.prepared'
    assert detail['external_booking_code'] is None and detail['paid_submission'] is False
    assert client.get('/api/v1/sports/betslip-preparation/missing').status_code==404
    assert client.post('/api/v1/sports/betslip-preparation/overview').status_code==405
    with factory() as db:assert db.scalar(select(func.count()).select_from(m.Ticket))==1
