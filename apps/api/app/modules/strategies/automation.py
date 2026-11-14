"""Conservative automated PAPER allocation from persisted qualification decisions."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select, text
from app.db import models as m
from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES
from app.modules.tickets.service import prepare_paper_ticket,TicketRejected


def allocate_paper(db, *, fixture_id=None, at=None, programme_keys=('singles','accumulator','draws','rollover','jackpot')):
    at=at or datetime.now(timezone.utc)
    report={'created':[],'rejected':[],'mode':'PAPER'}
    # Only prospective, freshly priced opportunities with all six gates passed.
    rows=db.scalars(select(m.Qualification).where(m.Qualification.decision=='QUALIFIED')).all()
    candidates=[]
    for q in rows:
        if not isinstance(q.gates,dict) or any(q.gates.get(k)!='PASS' for k in ('research','model','calibration','odds_freshness','market_mapping','value')):continue
        p=db.get(m.Prediction,q.prediction_id);o=db.get(m.Odds,q.odds_id)
        if not p or not o or p.fixture_id!=o.fixture_id:continue
        f=db.get(m.Fixture,p.fixture_id)
        if not f or f.kickoff_at<=at or not o.observed_at or not timedelta(0)<=at-o.observed_at<=timedelta(minutes=15):continue
        model=db.get(m.ModelVersion,p.model_id)
        if not model or model.status!='ACTIVE' or not all(model.validation.get(k) is True for k in ('approved','out_of_sample','calibrated','calibration_verified')):continue
        candidates.append(Candidate(q.id,f.id,Decimal(str(o.decimal_odds)),Decimal(str(p.probability)),p.market_key,p.outcome_key,f.kickoff_at.isoformat()))
    for key in programme_keys:
        if key not in PROGRAMMES:continue
        if db.bind.dialect.name == 'postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key':'cacsms-sports:allocation:'+key})
        programme=db.scalar(select(m.Programme).where(m.Programme.key==key))
        if not programme:report['rejected'].append({'programme':key,'reason':'PROGRAMME_NOT_CONFIGURED'});continue
        existing=db.scalars(select(m.Ticket).where(m.Ticket.programme_id==programme.id,m.Ticket.created_at>=at.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0),m.Ticket.created_at<at.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))).all()
        remaining=max(0,PROGRAMMES[key]['daily_cap']-len(existing))
        if not remaining:continue
        signatures=set()
        for ticket in db.scalars(select(m.Ticket).where(m.Ticket.programme_id==programme.id)).all():
            legs=db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket.id)).all()
            signatures.add('|'.join(sorted(l.qualification_id for l in legs)))
        sizes=(2,5,8,10) if key=='draws' else (None,)
        for size in sizes:
            if remaining<=0:break
            proposals=select_tickets(candidates,key,limit=remaining,draw_legs=size,existing_signatures=signatures)
            for proposal in proposals:
                if fixture_id and not any(c.fixture_id==fixture_id for c in candidates if c.qualification_id in proposal['qualification_ids']):continue
                try:
                    with db.begin_nested():
                        ticket=prepare_paper_ticket(db,key,proposal['qualification_ids'],at=at)
                    report['created'].append({'programme':key,'ticket_id':ticket['id'],'fixture_ids':sorted({c.fixture_id for c in candidates if c.qualification_id in proposal['qualification_ids']})})
                    signatures.add(proposal['signature']);remaining-=1
                except (TicketRejected,ValueError) as exc:
                    report['rejected'].append({'programme':key,'reason':str(exc)})
                if remaining<=0:break
    return report
