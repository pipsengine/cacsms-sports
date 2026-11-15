"""PAPER ticket preparation. Only independently qualified opportunities can become legs."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from sqlalchemy import select,func,text
from app.db import models as m
from app.modules.research.league import utc

MANDATORY=('research','model','calibration','odds_freshness','market_mapping','value')

class TicketRejected(ValueError):pass

def validate_leg(db,qualification_id,at=None):
    at=at or datetime.now(timezone.utc)
    q=db.get(m.Qualification,qualification_id)
    if q is None or q.decision!='QUALIFIED':raise TicketRejected('NOT_QUALIFIED')
    if not isinstance(q.gates,dict) or any(q.gates.get(g) not in ('PASS',True) for g in MANDATORY):
        raise TicketRejected('QUALIFICATION_GATES_INCOMPLETE')
    p=db.get(m.Prediction,q.prediction_id);o=db.get(m.Odds,q.odds_id)
    if not p or not o:raise TicketRejected('MISSING_FORECAST_OR_PRICE')
    if p.fixture_id!=o.fixture_id or p.market_key!=o.market_key or p.outcome_key!=o.outcome_key:
        raise TicketRejected('MARKET_MAPPING_MISMATCH')
    fixture=db.get(m.Fixture,p.fixture_id)
    if fixture is None or utc(fixture.kickoff_at)<=at:raise TicketRejected('FIXTURE_STARTED_OR_MISSING')
    observed=o.observed_at
    if observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
    if observed>at or (at-observed).total_seconds()>900:raise TicketRejected('ODDS_NOT_FRESH')
    return {'qualification_id':q.id,'fixture_id':fixture.id,'fixture':fixture.home_name+' v '+fixture.away_name,
            'market':p.market_key,'outcome':p.outcome_key,'odds':str(o.decimal_odds),
            'prediction_id':p.id,'odds_snapshot_id':o.id,'bookmaker':getattr(o,'bookmaker','UNSPECIFIED')}

def prepare_paper_ticket(db,programme_key,qualification_ids,at=None):
    if not qualification_ids:raise TicketRejected('NO_SELECTIONS')
    if len(set(qualification_ids))!=len(qualification_ids):raise TicketRejected('DUPLICATE_QUALIFICATION')
    programme=db.scalar(select(m.Programme).where(m.Programme.key==programme_key))
    if programme is None:raise TicketRejected('UNKNOWN_PROGRAMME')
    legs=[validate_leg(db,key,at) for key in qualification_ids]
    if len({leg['fixture_id'] for leg in legs})!=len(legs):raise TicketRejected('CORRELATED_SAME_FIXTURE')
    if programme_key=='singles' and len(legs)!=1:raise TicketRejected('SINGLES_REQUIRES_ONE_LEG')
    if programme_key=='draws' and len(legs) not in (2,5,8,10):raise TicketRejected('DRAW_LEG_COUNT_INVALID')
    bookmakers={leg['bookmaker'] for leg in legs}
    if len(bookmakers)!=1:raise TicketRejected('BOOKMAKER_MISMATCH')
    odds=Decimal('1')
    for leg in legs:odds*=Decimal(leg['odds'])
    from app.modules.strategies.optimizer import PROGRAMMES
    ceiling=PROGRAMMES.get(programme_key,{}).get('max_odds',Decimal('1000'))
    if odds>ceiling:raise TicketRejected('COMBINED_ODDS_OVER_PROGRAMME_LIMIT')
    if programme_key=='jackpot' and odds*Decimal('100')<Decimal('200000000'):raise TicketRejected('JACKPOT_TARGET_NOT_REACHED')
    if programme_key=='rollover' and not Decimal('1.45')<=odds<=Decimal('2.10'):raise TicketRejected('ROLLOVER_ODDS_OUTSIDE_RANGE')
    current=at or datetime.now(timezone.utc)
    if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'cacsms-sports:allocation:'+programme_key})
    start=current.replace(hour=0,minute=0,second=0,microsecond=0)
    count=db.scalar(select(func.count()).select_from(m.Ticket).where(m.Ticket.programme_id==programme.id,m.Ticket.created_at>=start,m.Ticket.created_at<start+timedelta(days=1))) or 0
    if count>=PROGRAMMES[programme_key]['daily_cap']:raise TicketRejected('DAILY_EXPOSURE_LIMIT_REACHED')
    ticket=m.Ticket(programme_id=programme.id,status='PAPER_PREPARED',created_at=current);db.add(ticket);db.flush()
    for leg in legs:db.add(m.TicketLeg(ticket_id=ticket.id,qualification_id=leg['qualification_id']))
    slip=m.Betslip(ticket_id=ticket.id,bookmaker=next(iter(bookmakers)),status='PAPER_PREPARED',selections=legs,combined_odds=odds,created_at=current)
    db.add(slip);db.flush()
    # Preparation is not verification: only the Verify stage may record PAPER_VERIFIED.
    db.add(m.TicketVerification(ticket_id=ticket.id,status='PAPER_PREPARED',verified_at=current,reason_codes=[],evidence={'scope':'PREPARATION','qualification_ids':qualification_ids,'source':'internal'}))
    db.add(m.AuditEvent(actor='ticket-service',action='paper_ticket.prepared',correlation_id=ticket.id,payload={'programme':programme_key,'legs':len(legs),'combined_odds':str(odds)}))
    return {'id':ticket.id,'betslip_id':slip.id,'status':ticket.status,'programme':programme_key,'combined_odds':str(odds),'selections':legs,'booking_code':None,'verified_external':False}
