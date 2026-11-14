from app.core.config import EXECUTION_MODE
from app.main import app,TABLES
from app.db.base import Base
from fastapi.testclient import TestClient

def test_paper_only():assert EXECUTION_MODE=='PAPER'
def test_all_resources_declared():assert all(k in TABLES for k in ['fixtures','research','predictions','qualification/decisions','booking-codes','results'])
def test_domain_tables():assert len(Base.metadata.tables)>=15
def test_no_paid_wager_routes():
 assert not any('wager' in r.path or 'place-bet' in r.path for r in app.routes)
def test_health_route_exists():assert any(r.path=='/health' for r in app.routes)
