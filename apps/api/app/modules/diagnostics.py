"""Read-only diagnostics over the platform's existing operational records."""
from datetime import datetime, timezone
from time import perf_counter
from fastapi import APIRouter
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from app.db.base import SessionLocal
from app.db import models as m

router = APIRouter(prefix='/api/v1/sports/diagnostics', tags=['Diagnostics'])


@router.get('/overview')
def overview():
    started = perf_counter()
    observed = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            db.execute(text('SELECT 1'))
            latency = round((perf_counter() - started) * 1000, 2)
            incidents = db.scalars(select(m.Incident).order_by(m.Incident.id)).all()
            runtimes = db.scalars(select(m.AutonomousRuntime).order_by(m.AutonomousRuntime.id)).all()
            events = db.scalars(select(m.AuditEvent).order_by(m.AuditEvent.created_at.desc()).limit(100)).all()
            services = [{'name': 'API services', 'state': 'OPERATIONAL', 'detail': 'Diagnostics request served'},
                        {'name': 'Database (PostgreSQL)', 'state': 'OPERATIONAL', 'detail': 'SELECT 1 succeeded'}]
            workers = []
            for r in runtimes:
                lease = r.lease_until
                if lease and lease.tzinfo is None:
                    lease = lease.replace(tzinfo=timezone.utc)
                online = bool(lease and lease > observed)
                state = 'OPERATIONAL' if online and not r.consecutive_errors else 'DEGRADED' if online else 'OFFLINE'
                services.append({'name': r.id, 'state': state, 'detail': r.status})
                workers.append({'name': r.id, 'state': state, 'cycles': r.cycles, 'errors': r.consecutive_errors,
                                'last_success_at': r.last_success_at, 'next_run_at': r.next_run_at})
            return {'mode': 'PAPER', 'live_wagers': False, 'observed_at': observed,
                    'database_latency_ms': latency, 'services': services, 'workers': workers,
                    'open_incidents': sum(i.status == 'OPEN' for i in incidents),
                    'incidents': [{'id': i.id, 'severity': i.severity, 'description': i.message, 'status': i.status} for i in incidents],
                    'audit': [{'id': e.id, 'at': e.created_at, 'actor': e.actor, 'event': e.action, 'detail': e.payload} for e in events],
                    'configuration': {'refresh_seconds': 30, 'execution_mode': 'PAPER', 'service_restarts': 'NOT_IMPLEMENTED',
                                      'escalation_delivery': 'NOT_CONFIGURED', 'health_history': 'NOT_RECORDED'}}
    except SQLAlchemyError:
        from fastapi import HTTPException
        raise HTTPException(503, 'Diagnostics database unavailable; no operational status inferred')
