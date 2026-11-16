"""Automatic Singles API (singles patch contract, served by the shared programme engine)."""
from app.db.base import SessionLocal
from app.modules.strategies.programme_routes import make_router

KEY='singles'
router=make_router(KEY,lambda:SessionLocal(),'Automatic Singles')
