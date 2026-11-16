from datetime import datetime
from fastapi import APIRouter,HTTPException,Query
from app.db.base import SessionLocal
from app.modules.market_scanner.service import workspace,catalog

router=APIRouter(prefix='/api/v1/sports/market-scanner',tags=['AI Predictions & Market Scanner'])


@router.get('/catalog')
def get_catalog(bookmaker:str|None=Query(default=None,max_length=60)):
    with SessionLocal() as db:return catalog(db,bookmaker)


@router.get('/fixtures/{fixture_id}')
def get_fixture(fixture_id:str,as_of:datetime|None=Query(default=None),bookmaker:str|None=Query(default=None,max_length=60)):
    try:
        with SessionLocal() as db:return workspace(db,fixture_id,as_of,bookmaker)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
