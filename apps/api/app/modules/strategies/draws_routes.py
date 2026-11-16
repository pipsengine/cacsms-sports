"""Weekly Draw Centre API (draw package contract, served by the shared programme engine; read-only, paper only).

The package's POST /api/draws/opportunities/ingest and POST /api/draws/run are intentionally not exposed: selections come
only from QUALIFIED decisions and the weekly run is scheduled by the autonomy cycle.
"""
from app.db.base import SessionLocal
from app.modules.strategies.programme_routes import make_router

KEY='draws'
router=make_router(KEY,lambda:SessionLocal(),'Weekly Draw Centre')
