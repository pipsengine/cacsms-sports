from fastapi import APIRouter,Header,Query
from app.db.base import SessionLocal
from app.modules.markets import intelligence as mi
from app.modules.markets.catalogue_routes import admin

router=APIRouter(prefix='/api/v1/sports/market-intelligence',tags=['Market Intelligence'])


@router.get('/overview')
def get_overview():
 with SessionLocal.begin() as db:return mi.overview(db)


@router.get('/categories')
def get_categories():
 with SessionLocal.begin() as db:return mi.categories(db)


@router.get('/markets')
def get_markets(category:str|None=Query(default=None,max_length=40),search:str|None=Query(default=None,max_length=80),sport:str|None=Query(default=None,max_length=60),
                limit:int=Query(default=10,ge=1,le=100),offset:int=Query(default=0,ge=0)):
 with SessionLocal.begin() as db:return mi.markets(db,category,search,sport,limit,offset)


@router.get('/sports-coverage')
def get_sports_coverage():
 with SessionLocal() as db:return mi.sports_coverage(db)


@router.get('/sync-history')
def get_sync_history(limit:int=Query(default=40,ge=1,le=200)):
 with SessionLocal() as db:return mi.sync_history(db,limit)


@router.get('/sources')
def get_sources():
 with SessionLocal() as db:return mi.sources(db)


@router.post('/sync')
def post_sync(x_admin_token:str|None=Header(default=None)):
 """Run the archive import step now (same code path as the autonomous cycle)."""
 admin(x_admin_token)
 from app.modules.markets.history_import import collect
 return collect(SessionLocal)
