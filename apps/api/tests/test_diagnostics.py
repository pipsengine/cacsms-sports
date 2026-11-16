from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from app.db import models as m
from app.modules import diagnostics
from test_browser_intelligence import factory


def test_diagnostics_uses_actual_incidents_and_worker_leases(monkeypatch):
    session = factory()
    monkeypatch.setattr(diagnostics, 'SessionLocal', session)
    with session.begin() as db:
        db.add_all([
            m.Incident(id='open', severity='HIGH', message='Capture failed', status='OPEN'),
            m.Incident(id='resolved', severity='LOW', message='Recovered', status='RESOLVED'),
            m.AutonomousRuntime(id='fresh', status='RUNNING', lease_until=datetime.now(timezone.utc)+timedelta(minutes=2), cycles=3, consecutive_errors=0),
            m.AutonomousRuntime(id='expired', status='RUNNING', lease_until=datetime.now(timezone.utc)-timedelta(minutes=2), cycles=2, consecutive_errors=0),
            m.AutonomousRuntime(id='errors', status='RUNNING', lease_until=datetime.now(timezone.utc)+timedelta(minutes=2), cycles=1, consecutive_errors=2),
        ])
    result = diagnostics.overview()
    assert result['mode'] == 'PAPER' and result['live_wagers'] is False
    assert result['open_incidents'] == 1
    assert {r['name']: r['state'] for r in result['workers']} == {'fresh': 'OPERATIONAL', 'expired': 'OFFLINE', 'errors': 'DEGRADED'}
    assert result['configuration']['health_history'] == 'NOT_RECORDED'
    assert result['database_latency_ms'] >= 0


def test_diagnostics_database_failure_is_not_healthy(monkeypatch):
    def broken():
        raise OperationalError('connect', {}, Exception('offline'))
    monkeypatch.setattr(diagnostics, 'SessionLocal', broken)
    with pytest.raises(HTTPException) as exc:
        diagnostics.overview()
    assert exc.value.status_code == 503
