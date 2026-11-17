"""Bounded per-process operational measurements; restart resets are explicit."""
import os
import time
from collections import defaultdict
from threading import Lock
from sqlalchemy import event
from app.db.base import engine

_lock = Lock()
_started = time.time()
_api = defaultdict(lambda: {'requests': 0, 'errors': 0, 'total_seconds': 0., 'max_seconds': 0.})
_database = {'queries': 0, 'errors': 0, 'total_seconds': 0., 'max_seconds': 0.}


def resident_memory():
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
                    ('peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool', 'peak_nonpaged_pool', 'nonpaged_pool', 'pagefile', 'peak_pagefile')]
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            query = ctypes.windll.psapi.GetProcessMemoryInfo
            query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if query(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb): return counters.working_set
        else:
            from pathlib import Path
            return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return None


def record_request(method, path, seconds, status):
    with _lock:
        item = _api[(method, path)]
        item['requests'] += 1
        item['errors'] += int(status >= 500)
        item['total_seconds'] += seconds
        item['max_seconds'] = max(item['max_seconds'], seconds)


@event.listens_for(engine, 'before_cursor_execute')
def before_query(connection, cursor, statement, parameters, context, executemany):
    context._odds_telemetry_start = time.perf_counter()


def record_query(context, failed=False):
    start = getattr(context, '_odds_telemetry_start', None)
    if start is None: return
    elapsed = time.perf_counter() - start
    with _lock:
        _database['queries'] += 1
        _database['errors'] += int(failed)
        _database['total_seconds'] += elapsed
        _database['max_seconds'] = max(_database['max_seconds'], elapsed)


@event.listens_for(engine, 'after_cursor_execute')
def after_query(connection, cursor, statement, parameters, context, executemany):
    record_query(context)


@event.listens_for(engine, 'handle_error')
def query_error(context):
    record_query(context.execution_context, True)


def snapshot():
    cpu = os.times()
    memory = resident_memory()
    with _lock:
        return {'scope': 'THIS_API_PROCESS_SINCE_START', 'pid': os.getpid(),
                'uptime_seconds': time.time() - _started, 'cpu_user_seconds': cpu.user,
                'cpu_system_seconds': cpu.system, 'resident_memory_bytes': memory,
                'memory_status': 'MEASURED' if memory is not None else 'UNAVAILABLE',
                'api': [{'method': method, 'route': path, **values} for (method, path), values in _api.items()],
                'database': dict(_database), 'latency_basis': 'REQUEST_TO_RESPONSE_HEADERS', 'mode': 'PAPER'}
