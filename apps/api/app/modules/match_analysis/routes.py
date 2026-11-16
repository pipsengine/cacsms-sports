from datetime import datetime
from fastapi import APIRouter,HTTPException,Query
from app.db.base import SessionLocal
from app.modules.match_analysis.service import workspace,summary

router=APIRouter(prefix='/api/v1/sports/match-analysis',tags=['Match Analysis'])


@router.get('/summary')
def get_summary():
    with SessionLocal() as db:return summary(db)


@router.get('/fixtures/{fixture_id}')
def get_fixture_analysis(fixture_id:str,as_of:datetime|None=Query(default=None)):
    try:
        with SessionLocal() as db:return workspace(db,fixture_id,as_of)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
