"""Daily Rollover Centre API (rollover package contract, served by the shared programme engine; read-only, paper only).

The package's POST /plans, /opportunities/ingest, /run and /steps/{id}/settle are intentionally not exposed: the plan is
maintained autonomously from run history, selections come only from QUALIFIED decisions, runs are scheduled by the
autonomy cycle and settlement comes only from verified results.
"""
from app.db.base import SessionLocal
from app.modules.strategies.programme_routes import make_router

KEY='rollover'
router=make_router(KEY,lambda:SessionLocal(),'Daily Rollover Centre')
