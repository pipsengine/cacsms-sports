"""Ticket Builder API (ticket-builder package contract mapped onto the canonical ticket register; read-only, paper only).

The package's POST /api/internal/qualified-feed is intentionally not exposed: opportunities come only from QUALIFIED
decisions via the programme engines, and registration is scheduled by the autonomy cycle.
"""
from datetime import datetime,timezone
from fastapi import APIRouter,Query
from app.db.base import SessionLocal
from app.modules.tickets import builder

router=APIRouter(prefix='/api/v1/sports/tickets/builder',tags=['Ticket Builder'])


@router.get('/overview')
def get_overview():
 with SessionLocal() as db:return builder.overview(db,datetime.now(timezone.utc))


@router.get('/register')
def get_register(limit:int=Query(default=20,ge=1,le=200),offset:int=Query(default=0,ge=0),status:str|None=Query(default=None,pattern='^(REGISTERED|REJECTED)$'),
                 programme:str|None=Query(default=None,pattern='^(accumulator|singles|jackpot|draws|rollover)$')):
 with SessionLocal() as db:
  rows=[x for x in builder.items(db) if (not status or x['status']==status) and (not programme or x['programme']==programme)]
  return {'total':len(rows),'items':rows[offset:offset+limit]}


@router.get('/programmes')
def get_programmes():
 from app.modules.strategies import programme_engine as pe
 return {'items':[{**pe.policy(k),'name':builder.NAMES[k]} for k in builder.PROGRAMMES],'checks':list(builder.REGISTRATION_CHECKS)}
