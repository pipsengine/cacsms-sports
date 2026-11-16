"""Jackpot Engine API (jackpot package contract, served by the shared programme engine; read-only, paper only).

The package's PUT /settings, POST /run and POST /internal/opportunities are intentionally not exposed: policy comes from
optimizer.PROGRAMMES, runs are scheduled by the autonomy cycle, and opportunities come only from QUALIFIED decisions.
"""
from app.db.base import SessionLocal
from app.modules.strategies.programme_routes import make_router

KEY='jackpot'
router=make_router(KEY,lambda:SessionLocal(),'Jackpot Engine')
