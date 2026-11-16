"""Dashboard adapter for the supplied betslip module, using canonical PAPER records."""
from datetime import datetime,timezone
from decimal import Decimal
from app.modules.tickets.service import validate_leg,TicketRejected
from fastapi import APIRouter,HTTPException
from sqlalchemy import select,func
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.autonomy.service import runtime_status
from app.modules.research.league import utc
from app.modules.strategies.optimizer import PROGRAMMES

router=APIRouter(prefix='/api/v1/sports/betslip-preparation',tags=['Paper Betslip Workspace'])
PREPARED={'PAPER_PREPARED','PAPER_VERIFIED'}


def serialize(db,slip):
    ticket=db.get(m.Ticket,slip.ticket_id)
    programme=db.get(m.Programme,ticket.programme_id) if ticket else None
    proofs=db.scalars(select(m.TicketVerification).where(m.TicketVerification.ticket_id==slip.ticket_id).order_by(m.TicketVerification.verified_at.desc())).all()
    return dict(id=slip.id,ticket_id=slip.ticket_id,programme=programme.key if programme else 'UNKNOWN',status=slip.status,
                bookmaker=slip.bookmaker,combined_odds=str(slip.combined_odds),leg_count=len(slip.selections),selections=slip.selections,
                created_at=slip.created_at,reasons=list(dict.fromkeys(reason for proof in proofs for reason in proof.reason_codes)),
                verification=[dict(status=p.status,verified_at=p.verified_at,scope=(p.evidence or {}).get('scope'),expires_at=(p.evidence or {}).get('expires_at')) for p in proofs])


def overview(db,at=None):
    at=at or datetime.now(timezone.utc)
    statuses=dict(db.execute(select(m.Betslip.status,func.count()).group_by(m.Betslip.status)).all())
    total=sum(statuses.values());prepared=sum(statuses.get(s,0) for s in PREPARED);failed=statuses.get('PAPER_REJECTED',0)
    selected=db.scalars(select(m.Betslip).order_by(m.Betslip.created_at.desc(),m.Betslip.id).limit(200)).all()
    rows=[serialize(db,s) for s in selected]
    # Average legs is an all-record metric, not the first screen's sample.
    sizes=db.scalars(select(m.Betslip.selections)).all()
    average=sum(len(s) for s in sizes)/len(sizes) if sizes else None
    ready=[]
    eligible_ids=None
    def currently_valid(row):
        nonlocal eligible_ids
        if eligible_ids is None:
            from app.modules.strategies.accumulator import eligible
            candidates,_=eligible(db,at)
            eligible_ids={item['qualification_id'] for item in candidates}
        canonical=list(db.scalars(select(m.TicketLeg.qualification_id).where(m.TicketLeg.ticket_id==row['ticket_id'])))
        stored=row['selections']
        if not canonical or len(canonical)!=len(stored) or {item.get('qualification_id') for item in stored}!=set(canonical):return False
        odds=Decimal('1')
        for leg in stored:
            if leg['qualification_id'] not in eligible_ids:return False
            try:item=validate_leg(db,leg['qualification_id'],at)
            except TicketRejected:return False
            if any(leg.get(k)!=item[k] for k in ('fixture_id','market','outcome','bookmaker')) or Decimal(str(leg.get('odds',0)))!=Decimal(item['odds']):return False
            odds*=Decimal(item['odds'])
        return abs(odds-Decimal(row['combined_odds']))<=Decimal('.00001')
    for row in rows:
        if row['status']!='PAPER_VERIFIED':continue
        for p in row['verification']:
            if p['scope']!='PAPER_BETSLIP' or p['status']!='PAPER_VERIFIED' or not p['expires_at']:continue
            try:expiry=datetime.fromisoformat(p['expires_at'].replace('Z','+00:00'))
            except ValueError:continue
            if expiry.tzinfo and utc(p['verified_at'])<=at<expiry and currently_valid(row):ready.append(row['id']);break
    sample=len(rows)
    preparation=sum(any(v['scope']=='PREPARATION' and v['status']=='PAPER_PREPARED' for v in row['verification']) for row in rows)
    market=sum(any(v['scope']=='PAPER_BETSLIP' and v['status']=='PAPER_VERIFIED' for v in row['verification']) for row in rows)
    checks=[dict(name=name,passed=passed,total=sample,rate=round(passed/sample*100,1) if sample else None) for name,passed in (
        ('Ticket Integrity',preparation),('Market & Odds Check',market),('Risk & Exposure Control',market))]
    runs=db.scalars(select(m.PipelineStageRun).where(m.PipelineStageRun.stage.in_(['prepare','verify'])).order_by(m.PipelineStageRun.started_at.desc()).limit(100)).all()
    history=[dict(id=r.id,run_id=r.pipeline_run_id,stage=r.stage,status=r.status,started_at=r.started_at,completed_at=r.completed_at,
                  failure_code=r.failure_code,reason=r.failure_reason,attempt=r.attempt) for r in runs]
    # Preparation can also come from the existing Ticket Builder, outside a fixture stage run.
    for audit in db.scalars(select(m.AuditEvent).where(m.AuditEvent.action=='paper_ticket.prepared').order_by(m.AuditEvent.created_at.desc()).limit(100)):
        history.append(dict(id='audit:'+audit.id,run_id=audit.correlation_id,stage='prepare',status='PAPER_PREPARED',started_at=audit.created_at,completed_at=audit.created_at,failure_code=None,reason=None,attempt=1))
    history.sort(key=lambda r:utc(r['started_at']),reverse=True)
    history=history[:100]
    latest={}
    for run in history:latest.setdefault(run['stage'],'VERIFIED' if run['status']=='PAPER_PREPARED' else run['status'])
    tickets=db.scalar(select(func.count()).select_from(m.Ticket)) or 0
    runtime=runtime_status(db,at)
    cfg={key:{**value,'max_odds':str(value['max_odds'])} for key,value in PROGRAMMES.items()}
    analytics=[]
    for key in PROGRAMMES:
        group=db.scalars(select(m.Betslip).join(m.Ticket,m.Ticket.id==m.Betslip.ticket_id).join(m.Programme,m.Programme.id==m.Ticket.programme_id).where(m.Programme.key==key)).all()
        count=len(group);ok=sum(s.status in PREPARED for s in group)
        analytics.append(dict(programme=key,recorded=count,prepared=ok,failed=sum(s.status=='PAPER_REJECTED' for s in group),preparation_rate=round(ok/count*100,1) if count else None))
    pipeline=[dict(name='Fetch',detail='Tickets',status='VERIFIED' if tickets else 'PENDING'),
              dict(name='Verify',detail='Markets',status=latest.get('verify','PENDING')),
              dict(name='Format',detail='Betslip',status='VERIFIED' if prepared else 'PENDING'),
              dict(name='Risk Check',detail='Odds / Limits',status=latest.get('verify','PENDING')),
              dict(name='Prepare',detail='Paper',status=latest.get('prepare','VERIFIED' if prepared else 'PENDING')),
              dict(name='Queue',detail='Booking',status='NOT_CONFIGURED')]
    return dict(mode='PAPER',summary=dict(recorded=total,prepared=prepared,failed=failed,preparation_rate=round(prepared/total*100,1) if total else None,average_legs=round(average,1) if average is not None else None),
                config=dict(mode='PAPER',format='Provider-neutral',ticket_source='REGISTERED_TICKETS',max_odds_age_seconds=900,programmes=cfg,paid_wagers_enabled=False),
                runtime=runtime,pipeline=pipeline,rows=rows,total=total,sample_limit=200,checks=checks,history=history,analytics=analytics,
                readiness=dict(status='PAPER_VERIFIED' if ready else 'AWAITING_VERIFICATION' if rows else 'AWAITING_QUALIFIED_TICKETS',ready_slip_ids=ready,
                               provider_booking='NOT_CONFIGURED',paid_submission=False),
                systems=[dict(name='Ticket Feed',status='RECORDS_AVAILABLE' if tickets else 'WAITING_FOR_DATA'),
                         dict(name='Market Data & Odds',status='RECORDED_VERIFICATION' if market else 'NOT_VERIFIED'),
                         dict(name='Betslip Formatter',status='RECORDS_AVAILABLE' if prepared else 'WAITING_FOR_DATA'),
                         dict(name='Risk Controls',status='RECORDED_VERIFICATION' if market else 'NOT_VERIFIED'),
                         dict(name='Scheduler (Auto Prepare)',status='WORKER_ONLINE' if runtime['worker_online'] else 'OFFLINE')],
                note='Read-only paper workspace. Check rates describe recorded receipts in the latest 200 betslips; they do not assert current odds freshness. Readiness requires an unexpired paper-verification receipt. No external booking or paid submission is configured.')


@router.get('/overview')
def get_overview():
    with SessionLocal() as db:return overview(db)


@router.get('/{slip_id}')
def detail(slip_id:str):
    with SessionLocal() as db:
        slip=db.get(m.Betslip,slip_id)
        if not slip:raise HTTPException(404,'Betslip not found')
        row=serialize(db,slip)
        audit=db.scalars(select(m.AuditEvent).where(m.AuditEvent.correlation_id==slip.ticket_id).order_by(m.AuditEvent.created_at.desc()).limit(100)).all()
        return {**row,'audit':[dict(event=a.action,detail=a.payload,created_at=a.created_at) for a in audit],'external_booking_code':None,'paid_submission':False}
