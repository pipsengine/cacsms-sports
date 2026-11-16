from datetime import timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.db import models as m
from app.modules.tickets import booking_workspace_routes as booking
from app.modules.tickets.service import prepare_paper_ticket
from tests.test_accumulator_engine import store  # noqa: F401


@pytest.fixture
def registered(store):
    factory,now=store
    with factory.begin() as db:
        db.add(m.Programme(id='singles',key='singles',configuration={}));db.flush()
        record=prepare_paper_ticket(db,'singles',['qf1'],at=now)
    return factory,now,record


def test_empty_and_unconfigured_state(store):
    factory,now=store
    with factory() as db:
        data=booking.overview(db,now)
        assert data['summary']==dict(total=0,prepared=0,booked=0,failed=0,success_rate=None)
        assert data['rows']==[] and data['analytics']['paper_roi'] is None
        assert data['config']['auto_booking'] is False
        assert data['readiness']['next_booking_at'] is None
        assert data['pipeline'][2]['status']=='NOT_CONFIGURED'


def test_prepared_ticket_does_not_get_invented_code(registered):
    factory,now,record=registered
    with factory() as db:
        data=booking.overview(db,now)
        assert data['summary']['prepared']==1 and data['summary']['booked']==0
        assert data['rows'][0]['status']=='PROVIDER_UNAVAILABLE'
        assert data['rows'][0]['code'] is None and data['rows'][0]['verified_at'] is None
        assert db.scalar(select(func.count()).select_from(m.BookingCode))==0


def test_display_requires_code_past_verification_and_https_evidence(registered):
    factory,now,record=registered
    with factory.begin() as db:
        db.add_all([
          m.BookingCode(id='valid',ticket_id=record['id'],bookmaker='Provider',code='EXTERNAL-TEST',verified_at=now,evidence_url='https://provider.example/evidence'),
          m.BookingCode(id='future',ticket_id=record['id'],bookmaker='Provider',code='HIDDEN-FUTURE',verified_at=now+timedelta(days=1),evidence_url='https://provider.example/evidence'),
          m.BookingCode(id='no-proof',ticket_id=record['id'],bookmaker='Provider',code='HIDDEN-UNSUPPORTED',verified_at=now,evidence_url=''),
          m.BookingCode(id='unsafe',ticket_id=record['id'],bookmaker='Provider',code='HIDDEN-URL',verified_at=now,evidence_url='javascript:alert(1)')])
    with factory() as db:
        data=booking.overview(db,now)
        assert data['rows'][0]['code']=='EXTERNAL-TEST'
        assert data['summary']['booked']==1 and data['analytics']['bookings']==1
        assert data['analytics']['average_legs']==1 and data['analytics']['average_odds']==1.6
        assert data['checks'][2]['rate']==25.0
        assert data['config']['provider']=='NOT_CONFIGURED'
        assert len(data['history'])==1


def test_recorded_failures_are_counted_without_fabricating_roi(registered):
    factory,now,record=registered
    with factory.begin() as db:
        db.add(m.AuditEvent(actor='test-provider',action='booking.verification_failed',correlation_id=record['id'],created_at=now,payload={'reason_code':'PROVIDER_REJECTED'}))
        db.add(m.AuditEvent(actor='test-provider',action='booking.verification_failed',correlation_id=record['id'],created_at=now+timedelta(days=1),payload={'reason_code':'FUTURE'}))
    with factory() as db:
        data=booking.overview(db,now)
        assert data['summary']['failed']==1 and data['summary']['success_rate']==0
        assert data['analytics']['trend'][0]['failed']==1
        assert data['analytics']['paper_roi'] is None


def test_detail_and_overview_are_read_only(registered,monkeypatch):
    factory,now,record=registered;monkeypatch.setattr(booking,'SessionLocal',factory)
    app=FastAPI();app.include_router(booking.router);client=TestClient(app)
    assert client.get('/api/v1/sports/booking-workspace/overview').status_code==200
    out=client.get('/api/v1/sports/booking-workspace/tickets/'+record['id']).json()
    assert out['codes']==[] and out['paid_submission'] is False
    assert out['audit'][0]['action']=='paper_ticket.prepared'
    assert client.get('/api/v1/sports/booking-workspace/tickets/missing').status_code==404
    assert client.post('/api/v1/sports/booking-workspace/overview').status_code==405
    with factory() as db:assert db.scalar(select(func.count()).select_from(m.BookingCode))==0
