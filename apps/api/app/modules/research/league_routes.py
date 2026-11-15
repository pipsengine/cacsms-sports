from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.research.league import top_two_research

router = APIRouter(prefix='/api/v1/sports', tags=['Club research'])

@router.get('/competitions')
def competitions():
    with SessionLocal() as db:
        return [dict(id=c.id, name=c.name, country=c.country, sport=s.name)
                for c, s in db.execute(select(m.Competition, m.Sport).join(m.Sport, m.Sport.id == m.Competition.sport_id).order_by(m.Competition.name))]

@router.get('/competitions/{competition_id}/top-two/research')
def top_two(competition_id: str, as_of: datetime | None = None, recent: int = Query(5, ge=1, le=20), since: datetime | None = None):
    try:
        with SessionLocal() as db:
            return top_two_research(db, competition_id, as_of, recent, since)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
