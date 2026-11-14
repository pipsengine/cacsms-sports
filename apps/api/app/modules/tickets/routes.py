from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.tickets.service import prepare_paper_ticket,TicketRejected
import os,secrets
router=APIRouter(prefix='/api/v1/sports',tags=['Paper Tickets'])
class PaperTicketRequest(BaseModel):
 programme_key:str=Field(pattern='^(accumulator|singles|jackpot|draws|rollover)$')
 qualification_ids:list[str]=Field(min_length=1,max_length=45)

def guard(token):
 expected=os.getenv('SPORTS_ADMIN_TOKEN','')
 if not expected or not token or not secrets.compare_digest(expected,token):raise HTTPException(403,'Administrative access unavailable')

@router.post('/admin/tickets/prepare',status_code=201)
def prepare(payload:PaperTicketRequest,x_admin_token:str|None=Header(default=None)):
 guard(x_admin_token)
 try:
  with SessionLocal.begin() as db:return prepare_paper_ticket(db,payload.programme_key,payload.qualification_ids)
 except TicketRejected as exc:raise HTTPException(422,{'code':str(exc)}) from exc

@router.get('/tickets/{ticket_id}/detail')
def detail(ticket_id:str):
 with SessionLocal() as db:
  ticket=db.get(m.Ticket,ticket_id)
  if not ticket:raise HTTPException(404,'Ticket not found')
  slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ticket_id))
  checks=db.scalars(select(m.TicketVerification).where(m.TicketVerification.ticket_id==ticket_id).order_by(m.TicketVerification.verified_at.desc())).all()
  return {'id':ticket.id,'status':ticket.status,'programme_id':ticket.programme_id,'created_at':ticket.created_at,
          'betslip':None if slip is None else {'id':slip.id,'bookmaker':slip.bookmaker,'status':slip.status,'combined_odds':str(slip.combined_odds),'selections':slip.selections},
          'verification':[{'status':v.status,'reason_codes':v.reason_codes,'verified_at':v.verified_at} for v in checks],
          'external_booking_code':None,'external_verification':'NOT_IMPLEMENTED'}

@router.get('/betslips')
def betslips():
 with SessionLocal() as db:
  return [{'id':b.id,'ticket_id':b.ticket_id,'bookmaker':b.bookmaker,'status':b.status,'combined_odds':str(b.combined_odds),'selections':b.selections,'created_at':b.created_at} for b in db.scalars(select(m.Betslip).order_by(m.Betslip.created_at.desc()).limit(100)).all()]

@router.get('/booking-codes/readiness')
def booking_readiness():
 return {'mode':'PAPER','external_integration':'NOT_CONFIGURED','booking_code_verification':'UNAVAILABLE','paid_wager_submission':'DISABLED','message':'No code is generated or asserted without independent external verification.'}
