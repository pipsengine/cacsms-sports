"""Read-only Booking Codes dashboard adapted from the supplied standalone module."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
from fastapi import APIRouter,HTTPException
from sqlalchemy import select,func
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.autonomy.service import runtime_status
from app.modules.research.league import utc
from app.modules.strategies.optimizer import PROGRAMMES

router=APIRouter(prefix='/api/v1/sports/booking-workspace',tags=['Booking Codes Workspace'])
FAIL_ACTIONS={'booking.verification_failed','booking.verification_rejected'}


def recorded_verified(code,at):
    if not code.code or not code.code.strip() or not code.verified_at or utc(code.verified_at)>at:return False
    try:
        url=urlparse(code.evidence_url or '')
        return url.scheme=='https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:return False


def overview(db,at=None):
    at=at or datetime.now(timezone.utc);since=at-timedelta(days=30)
    codes=db.scalars(select(m.BookingCode).order_by(m.BookingCode.verified_at.desc())).all()
    valid=[code for code in codes if recorded_verified(code,at)]
    by_ticket=defaultdict(list)
    for code in valid:by_ticket[code.ticket_id].append(code)
    records=db.scalars(select(m.Ticket).order_by(m.Ticket.created_at.desc(),m.Ticket.id).limit(200)).all()
    slips={s.ticket_id:s for s in db.scalars(select(m.Betslip).where(m.Betslip.ticket_id.in_([t.id for t in records])))}
    programmes={p.id:p.key for p in db.scalars(select(m.Programme))}
    events=db.scalars(select(m.AuditEvent).where(m.AuditEvent.action.in_(FAIL_ACTIONS|{'booking.verified','booking.code_recorded'}),m.AuditEvent.created_at<=at).order_by(m.AuditEvent.created_at.desc())).all()
    failures=[a for a in events if a.action in FAIL_ACTIONS]
    rows=[]
    for ticket in records:
        slip=slips.get(ticket.id);code=by_ticket.get(ticket.id,[None])[0]
        status='VERIFIED' if code else 'BLOCKED' if slip and slip.status=='PAPER_REJECTED' else 'PROVIDER_UNAVAILABLE' if slip else 'NOT_PREPARED'
        reason=None if code else 'BETSLIP_REJECTED' if status=='BLOCKED' else 'EXTERNAL_PROVIDER_NOT_CONFIGURED' if slip else 'PAPER_BETSLIP_REQUIRED'
        rows.append(dict(id=ticket.id,ticket_id=ticket.id,programme=programmes.get(ticket.programme_id,'UNKNOWN'),status=status,code=code.code if code else None,
                         provider=code.bookmaker if code else None,odds=str(slip.combined_odds) if slip else None,legs=len(slip.selections) if slip else 0,
                         created_at=ticket.created_at,verified_at=code.verified_at if code else None,evidence_url=code.evidence_url if code else None,reason=reason))
    total=db.scalar(select(func.count()).select_from(m.Ticket)) or 0
    prepared=db.scalar(select(func.count()).select_from(m.Betslip).where(m.Betslip.status.in_(['PAPER_PREPARED','PAPER_VERIFIED']))) or 0
    blocked=db.scalar(select(func.count()).select_from(m.Betslip).where(m.Betslip.status=='PAPER_REJECTED')) or 0
    attempts=len(valid)+len(failures);success=len(valid)*100/attempts if attempts else None
    recent_codes=[c for c in valid if utc(c.verified_at)>=since]
    recent_ids={c.ticket_id for c in recent_codes}
    recent_slips=list(db.scalars(select(m.Betslip).where(m.Betslip.ticket_id.in_(recent_ids))))
    window_failures=[a for a in failures if utc(a.created_at)>=since]
    daily=defaultdict(lambda:{'verified':0,'failed':0})
    for code in recent_codes:daily[utc(code.verified_at).date().isoformat()]['verified']+=1
    for event in window_failures:daily[utc(event.created_at).date().isoformat()]['failed']+=1
    trend=[dict(date=day,verified=values['verified'],failed=values['failed'],success_rate=round(values['verified']*100/(values['verified']+values['failed']),1)) for day,values in sorted(daily.items())]
    history=[dict(id='code:'+c.id,ticket_id=c.ticket_id,at=c.verified_at,action='EXTERNAL_CODE_RECORDED',status='VERIFIED',reason=None) for c in valid[:100]]
    history.extend(dict(id='audit:'+a.id,ticket_id=a.correlation_id,at=a.created_at,action=a.action,status='FAILED',reason=(a.payload or {}).get('reason_code','VERIFICATION_FAILED')) for a in failures)
    history.sort(key=lambda r:utc(r['at']),reverse=True)
    valid_tickets=set(by_ticket)
    all_tickets=list(db.scalars(select(m.Ticket)))
    distribution=[]
    for key in PROGRAMMES:
        ids={t.id for t in all_tickets if programmes.get(t.programme_id)==key}
        distribution.append(dict(programme=key,tickets=len(ids),verified=len(ids&valid_tickets),awaiting=len(ids-valid_tickets)))
    sampled=len(rows);preparation=0;market=0
    for ticket in records:
        proofs=list(db.scalars(select(m.TicketVerification).where(m.TicketVerification.ticket_id==ticket.id)))
        preparation+=int(any((p.evidence or {}).get('scope')=='PREPARATION' and p.status=='PAPER_PREPARED' for p in proofs))
        market+=int(any((p.evidence or {}).get('scope')=='PAPER_BETSLIP' and p.status=='PAPER_VERIFIED' for p in proofs))
    checks=[dict(name=name,passed=passed,total=count,rate=round(passed*100/count,1) if count else None) for name,passed,count in (
        ('Ticket Integrity',preparation,sampled),('Market & Odds Check',market,sampled),('Provider Validation',len(valid),len(codes)),('Risk & Exposure Control',market,sampled))]
    runtime=runtime_status(db,at)
    return dict(mode='PAPER',summary=dict(total=total,prepared=prepared,booked=len(valid_tickets),failed=blocked+len(failures),success_rate=round(success,1) if success is not None else None),
        config=dict(mode='PAPER',provider='NOT_CONFIGURED',auto_booking=False,max_retries=None,retry_interval_seconds=None,verification='RECORDED_EXTERNAL_EVIDENCE',daily_cap=None,code_format='EXTERNAL_ONLY'),
        runtime=runtime,rows=rows,total=total,sample_limit=200,checks=checks,history=history[:100],failed_items=[dict(id=a.id,ticket_id=a.correlation_id,at=a.created_at,reason=(a.payload or {}).get('reason_code','VERIFICATION_FAILED')) for a in failures[:100]],analytics=dict(window_days=30,bookings=len(recent_ids),
        success_rate=round(len(recent_codes)*100/(len(recent_codes)+len(window_failures)),1) if recent_codes or window_failures else None,
        average_odds=round(sum(float(s.combined_odds) for s in recent_slips)/len(recent_slips),3) if recent_slips else None,
        average_legs=round(sum(len(s.selections) for s in recent_slips)/len(recent_slips),1) if recent_slips else None,paper_roi=None,trend=trend,by_programme=distribution),
        pipeline=[dict(name='Fetch',detail='Prepared',status='VERIFIED' if prepared else 'PENDING'),dict(name='Validate',detail='Betslip',status='VERIFIED' if market else 'PENDING'),
                  dict(name='Submit',detail='Bookmaker',status='NOT_CONFIGURED'),dict(name='Verify',detail='Code',status='RECORDED' if valid else 'NOT_CONFIGURED'),
                  dict(name='Record',detail='Database',status='VERIFIED' if valid else 'PENDING'),dict(name='Notify',detail='Programmes',status='NOT_RECORDED')],
        readiness=dict(status='PROVIDER_NOT_CONFIGURED',blockers=['No authorized bookmaker submission or verification adapter is configured','No retry or booking queue is configured'],next_booking_at=None),
        systems=[dict(name='Ticket Feed',status='RECORDS_AVAILABLE' if total else 'WAITING_FOR_DATA'),dict(name='Betslip Formatter',status='RECORDS_AVAILABLE' if prepared else 'WAITING_FOR_DATA'),
                 dict(name='Bookmaker Integration',status='NOT_CONFIGURED'),dict(name='Code Verification',status='RECORDED_EVIDENCE' if valid else 'UNAVAILABLE'),
                 dict(name='Retry & Queue Manager',status='NOT_CONFIGURED'),dict(name='Platform Scheduler',status='WORKER_ONLINE' if runtime['worker_online'] else 'OFFLINE')],
        lifecycle=[dict(name='Qualified Ticket',detail='Registered',status='RECORDED' if total else 'WAITING'),dict(name='Betslip Preparation',detail='Paper format',status='RECORDED' if prepared else 'WAITING'),
                   dict(name='Booking Submission',detail='To bookmaker',status='NOT_CONFIGURED'),dict(name='Code Verification',detail='External evidence',status='RECORDED' if valid else 'UNAVAILABLE'),
                   dict(name='Booking Recorded',detail='Database ledger',status='RECORDED' if valid else 'WAITING')],
        notice='Verified codes are canonical records with non-empty code, past verification timestamp and HTTPS evidence URL. No external provider is contacted by this dashboard. Paper preparation is not a booking. Success rates use recorded codes and logged verification failures; missing measurements and paper ROI remain unavailable.')


@router.get('/overview')
def get_overview():
    with SessionLocal() as db:return overview(db)


@router.get('/tickets/{ticket_id}')
def detail(ticket_id:str):
    with SessionLocal() as db:
        ticket=db.get(m.Ticket,ticket_id)
        if not ticket:raise HTTPException(404,'Ticket not found')
        codes=db.scalars(select(m.BookingCode).where(m.BookingCode.ticket_id==ticket.id)).all()
        at=datetime.now(timezone.utc)
        verified=[dict(id=c.id,code=c.code,provider=c.bookmaker,verified_at=c.verified_at,evidence_url=c.evidence_url) for c in codes if recorded_verified(c,at)]
        audit=db.scalars(select(m.AuditEvent).where(m.AuditEvent.correlation_id==ticket.id).order_by(m.AuditEvent.created_at.desc()).limit(100)).all()
        return dict(ticket_id=ticket.id,status=ticket.status,codes=verified,audit=[dict(action=a.action,at=a.created_at,detail=a.payload) for a in audit],paid_submission=False)
