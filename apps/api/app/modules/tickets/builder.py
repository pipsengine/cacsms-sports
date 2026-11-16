"""Autonomous Ticket Builder: registers programme-engine paper tickets in the canonical ticket register.

Integrates the Ticket Builder package without a second builder, table or scheduler:
* tickets are composed by the five programme engines (programme_engine); the builder never composes its own;
* every engine ticket is registered through tickets.service.prepare_paper_ticket, the single canonical writer of
  Ticket, TicketLeg, Betslip and TicketVerification. That writer re-validates each leg at registration time
  (QUALIFIED decision, named gates, market mapping, fixture not started, odds <= 15 min), one fixture per leg,
  a single bookmaker, the programme odds ceiling/floor and the shared daily exposure cap;
* a ticket with the same legs already registered (e.g. by the 12-stage pipeline's prepare stage) is linked, not duplicated;
* the outcome (REGISTERED with ticket/betslip ids, or REJECTED with the reason) is stored on the programme run
  (StrategyRun.result['registrations']); a rejection is final for that ticket;
* paper only: no wager, no booking code (booking codes are recorded only when verified elsewhere).
"""
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc
from app.modules.strategies import programme_engine as pe
from app.modules.tickets.service import prepare_paper_ticket,TicketRejected

PROGRAMMES=('accumulator','singles','jackpot','draws','rollover')
NAMES={'accumulator':'Accumulator','singles':'Automatic Singles','jackpot':'Jackpot','draws':'Weekly Draw','rollover':'Daily Rollover'}
LOOKBACK=timedelta(days=2)
SCHEDULE_KEY='open-intel:schedule:ticket-builder'
REGISTRATION_CHECKS=('QUALIFIED decision with every named gate passed','Forecast and price map to the same fixture, market and outcome',
                     'Fixture not started','Odds observed within 15 minutes of registration','One selection per fixture',
                     'Single bookmaker per ticket','Programme odds ceiling (and jackpot floor / rollover band)','Shared daily exposure cap per programme')


def signature(ids):return '|'.join(sorted(ids))


def _registered_signatures(db):
 out={}
 rows=db.execute(select(m.Programme.key,m.Ticket.id,m.TicketLeg.qualification_id).join(m.Ticket,m.Ticket.programme_id==m.Programme.id)
                 .join(m.TicketLeg,m.TicketLeg.ticket_id==m.Ticket.id)).all()
 legs=defaultdict(list);keys={}
 for key,tid,qid in rows:legs[tid].append(qid);keys[tid]=key
 for tid,ids in legs.items():out[(keys[tid],signature(ids))]=tid
 return out


def register(db,at=None):
 """Register every not-yet-processed ticket of recent COMPLETED programme runs (idempotent)."""
 at=at or datetime.now(timezone.utc)
 report={'registered':0,'linked':0,'rejected':0,'errors':[]}
 runs=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key.in_(PROGRAMMES),m.StrategyRun.status=='COMPLETED',
                                             m.StrategyRun.created_at>=at-LOOKBACK).order_by(m.StrategyRun.created_at)).all()
 known=None
 for run in runs:
  res=dict(run.result or {});regs=list(res.get('registrations') or []);done={r['index'] for r in regs};changed=False
  for i,t in enumerate(pe.run_tickets(run)):
   if i in done:continue
   known=known if known is not None else _registered_signatures(db)
   ids=[leg['qualification_id'] for leg in t['legs']];sig=signature(ids)
   entry={'index':i,'signature':sig,'legs':len(ids),'combined_odds':t.get('combined_odds'),'at':at.isoformat()}
   tid=known.get((run.programme_key,sig))
   if tid:
    entry.update(status='REGISTERED',ticket_id=tid,linked=True);report['linked']+=1
   else:
    try:
     with db.begin_nested():out=prepare_paper_ticket(db,run.programme_key,ids,at=at)
     entry.update(status='REGISTERED',ticket_id=out['id'],betslip_id=out['betslip_id'],linked=False);known[(run.programme_key,sig)]=out['id'];report['registered']+=1
    except TicketRejected as exc:
     entry.update(status='REJECTED',reason=str(exc));report['rejected']+=1
   regs.append(entry);changed=True
   db.add(m.AuditEvent(actor='ticket-builder',action='ticket_builder.'+entry['status'].lower(),correlation_id=run.id,
                       payload={'programme':run.programme_key,'index':i,'ticket_id':entry.get('ticket_id'),'reason':entry.get('reason'),'linked':entry.get('linked')}))
  if changed:res['registrations']=regs;run.result=res
 return report


def cycle(factory,at=None):
 with factory.begin() as db:return register(db,at)


# Read models -----------------------------------------------------------------------------------------------------

def items(db,limit=None):
 """Every registration outcome, newest first, with the ticket's legs (from the programme run)."""
 runs=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key.in_(PROGRAMMES),m.StrategyRun.status=='COMPLETED')
                 .order_by(m.StrategyRun.created_at.desc()).limit(2000)).all()
 out=[]
 for r in runs:
  tickets=pe.run_tickets(r)
  for g in (r.result or {}).get('registrations') or []:
   t=tickets[g['index']] if g['index']<len(tickets) else {}
   out.append({'programme':r.programme_key,'programme_name':NAMES[r.programme_key],'run_id':r.id,'built_at':r.created_at,'registered_at':g['at'],
               'legs':g['legs'],'combined_odds':g.get('combined_odds'),'status':g['status'],'reason':g.get('reason'),'ticket_id':g.get('ticket_id'),
               'betslip_id':g.get('betslip_id'),'linked':g.get('linked',False),'selections':t.get('legs',[]),
               'probability_lower_bound':t.get('probability_lower_bound'),'probability_upper_bound':t.get('probability_upper_bound'),
               'paper_stake':t.get('paper_stake'),'potential_return':t.get('potential_return')})
 out.sort(key=lambda x:x['registered_at'],reverse=True)
 for i,x in enumerate(out):x['number']=len(out)-i
 return out[:limit] if limit else out


def _window(rows,start,end):
 w=[x for x in rows if start<=utc(datetime.fromisoformat(x['registered_at']))<end];ok=[x for x in w if x['status']=='REGISTERED']
 return {'items':len(w),'built':len(ok),'rejected':len(w)-len(ok),'rate':len(ok)*100/len(w) if w else None,
         'avg_legs':sum(x['legs'] for x in ok)/len(ok) if ok else None}


def overview(db,at=None):
 at=at or datetime.now(timezone.utc)
 rows=items(db);ok=[x for x in rows if x['status']=='REGISTERED']
 now_w,prev_w=_window(rows,at-timedelta(days=1),at+timedelta(seconds=1)),_window(rows,at-timedelta(days=2),at-timedelta(days=1))
 change=lambda a,b:round((a-b)*100/b,1) if b else None
 diff=lambda a,b,d=1:round(a-b,d) if a is not None and b is not None else None
 state=db.get(m.ProviderSyncState,SCHEDULE_KEY)
 completed_runs=db.scalar(select(func.count()).select_from(m.StrategyRun).where(m.StrategyRun.programme_key.in_(PROGRAMMES),m.StrategyRun.status=='COMPLETED')) or 0
 qualified=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0
 counts={'tickets':db.scalar(select(func.count()).select_from(m.Ticket)) or 0,'betslips':db.scalar(select(func.count()).select_from(m.Betslip)) or 0,
         'booking_codes':db.scalar(select(func.count()).select_from(m.BookingCode).where(m.BookingCode.verified_at.is_not(None))) or 0}
 from app.modules.autonomy.service import runtime_status
 rt=runtime_status(db)
 latest=next((x for x in rows if x['status']=='REGISTERED'),None)
 reasons=Counter(x['reason'] for x in rows if x['status']=='REJECTED')
 by_programme=[{'programme':k,'name':NAMES[k],'registered':sum(1 for x in rows if x['programme']==k and x['status']=='REGISTERED'),
                'rejected':sum(1 for x in rows if x['programme']==k and x['status']=='REJECTED')} for k in PROGRAMMES]
 daily=defaultdict(lambda:[0,0])
 for x in rows:
  d=utc(datetime.fromisoformat(x['registered_at']))
  if d>=at-timedelta(days=30):daily[d.date().isoformat()][1]+=1;daily[d.date().isoformat()][0]+=x['status']=='REGISTERED'
 step=lambda k,name,sub,ok_,detail:{'key':k,'name':name,'sub':sub,'status':'DONE' if ok_ else 'WAITING','detail':detail}
 pipeline=[step('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),
           step('screen','Screen','Validate',qualified>0,'Programme engines re-check the named gates and freshness'),
           step('optimise','Optimise','Combinations',completed_runs>0,f'{completed_runs} completed programme runs'),
           step('build','Build','Ticket',bool(rows),f'{len(rows)} engine tickets received'),
           step('risk','Risk Check','Odds/Limits',bool(rows),'Re-validated at registration: freshness, bookmaker, odds limits, daily cap'),
           step('register','Register','Paper',bool(ok),f'{len(ok)} registered in the ticket register'),
           step('record','Record','Audit',bool(rows),'Every outcome recorded with reasons')]
 last_check=state.next_check_at-timedelta(minutes=1) if state and state.next_check_at else None
 fresh=lambda t,mins:bool(t) and at-utc(t)<=timedelta(minutes=mins)
 q=db.get(m.ProviderSyncState,'qualification:autonomous');q_at=(q.payload or {}).get('at') if q else None
 system=[{'name':'Qualified feed','status':'HEALTHY' if q_at and fresh(datetime.fromisoformat(q_at),10) else 'WAITING','detail':f'Last qualification cycle {q_at or "never"}'},
         {'name':'Validation engine','status':'HEALTHY','detail':'tickets.service.validate_leg on every leg at registration'},
         {'name':'Ticket builder','status':'HEALTHY' if fresh(last_check,5) else 'WAITING','detail':f'Last cycle {utc(last_check).isoformat() if last_check else "never"}'},
         {'name':'Risk controls','status':'HEALTHY','detail':'Programme odds limits and shared daily exposure caps'},
         {'name':'Scheduler (auto build)','status':'ACTIVE' if rt.get('worker_online') else 'OFFLINE','detail':'Autonomy cycle, every minute'}]
 return {'mode':'PAPER','programme':'TICKET_BUILDER','readiness':'READY_FOR_QUALIFIED_DATA' if qualified else 'WAITING_FOR_QUALIFIED_DATA',
         'recorded_items':len(rows),'built':len(ok),'rejected':len(rows)-len(ok),'build_rate':round(len(ok)*100/len(rows),1) if rows else None,
         'avg_legs':round(sum(x['legs'] for x in ok)/len(ok),1) if ok else None,
         'trend':{'items':change(now_w['items'],prev_w['items']),'built':change(now_w['built'],prev_w['built']),'rejected':change(now_w['rejected'],prev_w['rejected']),
                  'build_rate_pp':diff(now_w['rate'],prev_w['rate']),'avg_legs':diff(now_w['avg_legs'],prev_w['avg_legs'])},
         'next_run_at':utc(state.next_check_at).isoformat() if state and state.next_check_at else None,'runtime':{'worker_online':rt.get('worker_online')},
         'pipeline':pipeline,'recent':rows[:5],'latest':latest,'rules':[{**pe.policy(k),'name':NAMES[k]} for k in PROGRAMMES],
         'lifecycle':counts,'system':system,'checks':list(REGISTRATION_CHECKS),
         'analytics':{'by_programme':by_programme,'rejection_reasons':dict(reasons),'linked':sum(1 for x in ok if x['linked']),
                      'daily':[{'date':d,'build_rate':round(c*100/t,1),'items':t} for d,(c,t) in sorted(daily.items())]},
         'notice':'Paper tickets only. Tickets are composed by the programme engines from QUALIFIED opportunities and registered only after re-validation; no wagers or booking codes are created.'}
