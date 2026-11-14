"""Server-Sent Events stream that tells clients when persisted data changes.

Change detection uses PostgreSQL's per-table tuple counters (pg_stat_user_tables), so any
insert/update/delete from any writer (API, worker, scheduler, manual SQL) is noticed without
triggers or migrations. Clients re-fetch their own endpoints on a ``change`` event; the stream
itself never carries business data, so nothing is simulated or duplicated here.
"""
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import SessionLocal

router = APIRouter(prefix='/api/v1/sports/live', tags=['Live'])

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0
_VERSION_SQL = text('SELECT COALESCE(SUM(n_tup_ins + n_tup_upd + n_tup_del), 0)::bigint FROM pg_stat_user_tables')


def data_version() -> int | None:
    """Monotonic-ish counter of row changes across all tables; None when the database is unreachable."""
    try:
        with SessionLocal() as s:
            return int(s.execute(_VERSION_SQL).scalar() or 0)
    except SQLAlchemyError:
        return None


def _event(name: str, version: int | None) -> str:
    payload = {'version': version, 'database': 'CONNECTED' if version is not None else 'UNAVAILABLE',
               'at': datetime.now(timezone.utc).isoformat()}
    return f'event: {name}\ndata: {json.dumps(payload)}\n\n'


@router.get('/version')
def version():
    v = data_version()
    return {'version': v, 'database': 'CONNECTED' if v is not None else 'UNAVAILABLE'}


@router.get('/stream')
async def stream(request: Request):
    async def events():
        last = await asyncio.to_thread(data_version)
        yield 'retry: 3000\n\n'
        yield _event('hello', last)
        idle = 0.0
        while True:
            await asyncio.sleep(POLL_SECONDS)
            if await request.is_disconnected():
                break
            current = await asyncio.to_thread(data_version)
            if current != last:
                last = current
                idle = 0.0
                yield _event('change', current)
            else:
                idle += POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    idle = 0.0
                    yield ': ping\n\n'

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})
