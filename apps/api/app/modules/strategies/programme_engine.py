"""Autonomous, paper-only programme engine shared by Accumulator, Singles, Jackpot, Weekly Draw and Daily Rollover.

Integrates the accumulator and singles patches without separate workers or databases:
* each programme is a step of the existing autonomy cycle with idempotent time buckets;
* composition uses the existing optimizer.select_tickets and PROGRAMMES policy (one policy for every path);
  multi-leg probability is recorded as bounds only, never as an independent product;
* eligibility re-checks the named qualification gates explicitly, plus model approval, freshness and positive EV;
* singles: several tickets per run up to the remaining daily cap, one per fixture per UTC day, no reused decision,
  fixed paper stake; runs are always recorded, including BLOCKED ones with reasons;
* jackpot: one ticket per run (2-30 legs) whose combined odds reach optimizer's jackpot floor; a cheap reachability
  screen blocks the run with JACKPOT_ODDS_UNREACHABLE before any combination search when the floor cannot be met;
* draws: weekly run (Saturday 09:00 Africa/Lagos, caught up on the first cycle of the period), full-time 1X2 draw legs
  with an edge of at least 1.5 pp, one ticket per leg target (2, 5, 8, 10) without reusing a selection across tickets;
* rollover: daily run (09:00 Africa/Lagos, caught up), one single per day inside a 30-day paper plan whose state is derived
  from run history (no extra table). A step advances only on a VERIFIED win (bankroll x odds); a loss stops the plan and a
  fresh one starts; a void (or no verified result 7 days after kickoff) keeps day and bankroll; an unsettled step blocks
  the next one (AWAITING_SETTLEMENT), so a plan never compounds on predicted wins;
* paper settlement / ROI only from verified results of every leg.
"""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc
from math import prod
from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES,JACKPOT_MIN_COMBINED_ODDS

FRESHNESS=timedelta(minutes=15)
REQUIRED_GATES=('research','model','calibration','odds_freshness','market_mapping','value')
OPTIONAL_GATES=('uncertainty','market_risk')  # enforced when recorded (autonomous qualification records them)
APPROVALS=('approved','out_of_sample','calibrated','calibration_verified')
SETTINGS={'accumulator':{'bucket_minutes':15,'tickets_per_run':1,'stake':None,'cap_unit':'runs'},
          'singles':{'bucket_minutes':5,'tickets_per_run':None,'stake':100,'cap_unit':'tickets','one_per_fixture_per_day':True},
          'jackpot':{'bucket_minutes':15,'tickets_per_run':1,'stake':None,'cap_unit':'runs'},
          'draws':{'bucket_minutes':7*24*60,'weekly':True,'tickets_per_run':None,'stake':None,'cap_unit':'tickets','leg_targets':(2,5,8,10),'min_edge':0.015},
          'rollover':{'bucket_minutes':24*60,'daily':True,'tickets_per_run':1,'stake':None,'cap_unit':'runs','min_edge':0.015,
                      'target_odds':1.5,'band':0.25,'plan_days':30,'bankroll':1000,'max_days_ahead':2}}
WEEKLY_ANCHOR=(5,8)  # Saturday 08:00 UTC = 09:00 Africa/Lagos (no DST)
# Mirrors optimizer.select_tickets' jackpot rule (combined*100 >= 200,000,000), the single source of the floor.
MIN_COMBINED_ODDS={'jackpot':JACKPOT_MIN_COMBINED_ODDS}
POOL=20  # optimizer.select_tickets searches the 20 best-EV candidates


def policy(key):
 cfg=PROGRAMMES[key];s=SETTINGS[key]
 return {'programme':key,'min_legs':cfg['min_legs'],'max_legs':cfg['max_legs'],'max_odds':float(cfg['max_odds']),'daily_cap':cfg['daily_cap'],
         'freshness_minutes':int(FRESHNESS.total_seconds()//60),'unique_fixture_per_ticket':True,'mode':'PAPER','schedule_minutes':s['bucket_minutes'],
         'paper_stake':s['stake'],'cap_unit':s['cap_unit'],'one_per_fixture_per_day':bool(s.get('one_per_fixture_per_day')),
         'min_combined_odds':float(MIN_COMBINED_ODDS[key]) if key in MIN_COMBINED_ODDS else None,
         'leg_targets':list(s['leg_targets']) if s.get('leg_targets') else None,'min_edge':s.get('min_edge'),
         'schedule':'Weekly, Saturday 09:00 WAT' if s.get('weekly') else 'Daily, 09:00 WAT' if s.get('daily') else f"Every {s['bucket_minutes']} minutes",
         **({'target_odds':s['target_odds'],'target_band':[s['target_odds'],s['target_odds']+s['band']],'plan_days':s['plan_days'],'starting_bankroll':s['bankroll'],
             'max_days_ahead':s['max_days_ahead']} if key=='rollover' else {})}


def programme_rows(key,rows,excluded):
 """Programme-specific eligibility on top of the shared named-gate eligibility (draws: full-time draw, minimum edge)."""
 s=SETTINGS[key];excluded=dict(excluded)
 if key=='rollover':
  kept=[];lo,hi=s['target_odds'],s['target_odds']+s['band']
  for r in rows:
   reason='OUTSIDE_TARGET_BAND' if not lo<=r['odds']<=hi else 'INSUFFICIENT_EDGE' if r['probability']-1/r['odds']<s['min_edge'] else None
   if reason is None and r.get('_at') and utc(r['kickoff_at'])>r['_at']+timedelta(days=s['max_days_ahead']):reason='TOO_FAR_AHEAD'
   if reason:excluded[reason]=excluded.get(reason,0)+1
   else:kept.append(r)
  return kept,excluded
 if key!='draws':return rows,excluded
 kept=[]
 for r in rows:
  if r['market_key']!='1X2' or str(r['outcome_key']).upper() not in ('DRAW','X'):excluded['NOT_FULL_TIME_DRAW']=excluded.get('NOT_FULL_TIME_DRAW',0)+1;continue
  if r['probability']-1/r['odds']<s['min_edge']:excluded['INSUFFICIENT_EDGE']=excluded.get('INSUFFICIENT_EDGE',0)+1;continue
  kept.append(r)
 return kept,excluded


def reachable_odds(rows,key):
 """Highest combined odds the optimizer could build: best price per fixture, top-EV pool, capped at max legs/odds."""
 best={}
 for r in rows[:POOL]:best[r['fixture_id']]=max(best.get(r['fixture_id'],1.0),r['odds'])
 top=sorted(best.values(),reverse=True)[:PROGRAMMES[key]['max_legs']]
 return min(prod(top),float(PROGRAMMES[key]['max_odds'])) if len(top)>=PROGRAMMES[key]['min_legs'] else None


def gates_pass(gates):
 if not isinstance(gates,dict):return False
 return all(gates.get(g)=='PASS' for g in REQUIRED_GATES) and all(gates.get(g,'PASS')=='PASS' for g in OPTIONAL_GATES)


def eligible(db,at):
 """Fresh, fully qualified opportunities of upcoming fixtures from ACTIVE approved models, with reasons for every exclusion."""
 rows=db.execute(select(m.Qualification,m.Prediction,m.Odds,m.Fixture,m.ModelVersion).join(m.Prediction,m.Qualification.prediction_id==m.Prediction.id)
                 .join(m.Odds,m.Qualification.odds_id==m.Odds.id).join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id)
                 .join(m.ModelVersion,m.Prediction.model_id==m.ModelVersion.id).where(m.Qualification.decision=='QUALIFIED').order_by(m.Qualification.decided_at.desc()).limit(500)).all()
 out=[];excluded=defaultdict(int);seen=set()
 for q,p,o,f,model in rows:
  if utc(f.kickoff_at)<=at:excluded['FIXTURE_STARTED']+=1;continue
  if not gates_pass(q.gates):excluded['QUALITY_GATE_NOT_PASSED']+=1;continue
  if model.status!='ACTIVE' or not all((model.validation or {}).get(k) is True for k in APPROVALS):excluded['MODEL_NOT_ACTIVE_APPROVED']+=1;continue
  if p.fixture_id!=o.fixture_id or p.market_key!=o.market_key or p.outcome_key!=o.outcome_key:excluded['MARKET_MAPPING_MISMATCH']+=1;continue
  if not timedelta(0)<=at-utc(o.observed_at)<=FRESHNESS:excluded['ODDS_NOT_FRESH']+=1;continue
  prob,odds=float(p.probability),float(o.decimal_odds)
  if prob*odds<=1:excluded['NO_POSITIVE_EV']+=1;continue
  if (f.id,p.market_key,p.outcome_key) in seen:continue
  seen.add((f.id,p.market_key,p.outcome_key))
  out.append({'qualification_id':q.id,'fixture_id':f.id,'fixture':f'{f.home_name} vs {f.away_name}','kickoff_at':f.kickoff_at,'market_key':p.market_key,'outcome_key':p.outcome_key,
              'odds':odds,'probability':prob,'ev':round((prob*odds-1)*100,2),'bookmaker':o.bookmaker,'odds_observed_at':o.observed_at,'_at':at})
 out.sort(key=lambda r:-r['ev'])
 return out,dict(excluded)


def strip(rows):return [{k:v for k,v in r.items() if k!='_at'} for r in rows]


def step_state(db,ticket,at):
 """WON/LOST from a verified result, VOID when voided or still unverified 7 days after kickoff, else None (pending)."""
 st=settle_ticket(db,ticket)
 if st:return st
 leg=(ticket.get('legs') or [None])[0]
 if not leg:return None
 res=db.scalar(select(m.Result).where(m.Result.fixture_id==leg['fixture_id']).order_by(m.Result.version.desc()).limit(1))
 if res is not None and ((res.outcome or {}).get('outcomes') or {}).get(leg['market_key'],{}).get(leg['outcome_key'])=='VOID':return 'VOID'
 kickoff=leg.get('kickoff_at')
 if kickoff and at-utc(datetime.fromisoformat(kickoff) if isinstance(kickoff,str) else kickoff)>timedelta(days=7):return 'VOID'
 return None


def rollover_state(db,at):
 """Current paper plan derived from the latest completed rollover step (no plan table, no human input)."""
 s=SETTINGS['rollover']
 fresh={'plan_id':f"plan-{at.astimezone(timezone.utc):%Y%m%d}",'day':1,'bankroll':float(s['bankroll']),'started_at':at.isoformat(),'plan_days':s['plan_days'],
        'target_odds':s['target_odds'],'status':'ACTIVE','previous':None,'ended':None}
 last=db.scalar(select(m.StrategyRun).where(m.StrategyRun.programme_key=='rollover',m.StrategyRun.status=='COMPLETED').order_by(m.StrategyRun.created_at.desc()).limit(1))
 if last is None or not (last.result or {}).get('plan') or not run_tickets(last):return fresh
 plan={**last.result['plan'],'ended':None};t=run_tickets(last)[0];st=step_state(db,t,at)
 if st is None:return {**plan,'status':'AWAITING_SETTLEMENT','previous':None}
 if st=='VOID':return {**plan,'status':'ACTIVE','previous':'VOID'}
 if st=='LOST':return {**fresh,'previous':'LOST','ended':{'plan_id':plan['plan_id'],'status':'STOPPED','day':plan['day']}}
 if plan['day']>=plan['plan_days']:return {**fresh,'previous':'WON','ended':{'plan_id':plan['plan_id'],'status':'COMPLETED','day':plan['day'],
                                         'bankroll':round(plan['bankroll']*t['combined_odds'],2)}}
 return {**plan,'day':plan['day']+1,'bankroll':round(plan['bankroll']*t['combined_odds'],2),'status':'ACTIVE','previous':'WON'}


def period_start(key,at):
 s=SETTINGS[key]
 if s.get('daily'):
  at=at.astimezone(timezone.utc);start=at.replace(hour=WEEKLY_ANCHOR[1],minute=0,second=0,microsecond=0)
  return start-timedelta(days=1) if start>at else start
 if s.get('weekly'):
  at=at.astimezone(timezone.utc);day,hour=WEEKLY_ANCHOR
  start=(at-timedelta(days=(at.weekday()-day)%7)).replace(hour=hour,minute=0,second=0,microsecond=0)
  return start-timedelta(days=7) if start>at else start
 size=s['bucket_minutes'];return at.replace(minute=(at.minute//size)*size,second=0,microsecond=0)


def bucket(key,at):return period_start(key,at).strftime('%Y%m%d%H%M')


def _today_runs(db,key,at):
 day=at.replace(hour=0,minute=0,second=0,microsecond=0)
 return db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.status=='COMPLETED',m.StrategyRun.created_at>=day)).all()


def run_once(db,key,at=None,trigger='autonomous'):
 """Record one paper composition decision for the programme's current time bucket (idempotent)."""
 at=at or datetime.now(timezone.utc);ident=f'auto:{bucket(key,at)}';s=SETTINGS[key]
 prior=db.scalar(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.idempotency_key==ident))
 if prior:return prior
 rows,excluded=programme_rows(key,*eligible(db,at));rows=strip(rows);cfg=policy(key)
 today=_today_runs(db,key,at)
 plan=rollover_state(db,at) if key=='rollover' else None
 used_today=sum(len((r.result or {}).get('tickets') or []) or (1 if (r.result or {}).get('legs') else 0) for r in today) if s['cap_unit']=='tickets' else len(today)
 remaining=max(0,cfg['daily_cap']-used_today)
 if s.get('one_per_fixture_per_day'):
  taken_fixtures={leg['fixture_id'] for r in today for t in ((r.result or {}).get('tickets') or []) for leg in t['legs']}
  taken_decisions={leg['qualification_id'] for r in today for t in ((r.result or {}).get('tickets') or []) for leg in t['legs']}
  before=len(rows);rows=[r for r in rows if r['fixture_id'] not in taken_fixtures and r['qualification_id'] not in taken_decisions]
  if before-len(rows):excluded['ALREADY_SELECTED_TODAY']=before-len(rows)
 reasons=[]
 if remaining<=0:reasons.append('DAILY_CAP_REACHED')
 if plan and plan['status']=='AWAITING_SETTLEMENT':reasons.append('AWAITING_SETTLEMENT')
 if len(rows)<cfg['min_legs']:reasons.append('INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES')
 reach=reachable_odds(rows,key) if key in MIN_COMBINED_ODDS else None
 if key in MIN_COMBINED_ODDS and not reasons and (reach or 0)<float(MIN_COMBINED_ODDS[key]):reasons.append('JACKPOT_ODDS_UNREACHABLE')
 proposals=[]
 if not reasons:
  candidates=[Candidate(r['qualification_id'],r['fixture_id'],Decimal(str(r['odds'])),Decimal(str(r['probability'])),r['market_key'],r['outcome_key'],utc(r['kickoff_at']).isoformat()) for r in rows]
  limit=min(remaining,s['tickets_per_run'] or remaining)
  if s.get('leg_targets'):
   proposals,used=[],set()
   for target in s['leg_targets']:
    if len(proposals)>=limit:break
    got=select_tickets([c for c in candidates if c.qualification_id not in used],key,limit=1,draw_legs=target)
    if got:proposals.append(got[0]);used|=set(got[0]['qualification_ids'])
  else:proposals=select_tickets(candidates,key,limit=max(1,limit))
  if s.get('one_per_fixture_per_day'):
   kept,fixtures=[],set()
   for prop in proposals:
    fx={c for c in prop['qualification_ids']}
    fixture_ids={next(r['fixture_id'] for r in rows if r['qualification_id']==q) for q in fx}
    if fixture_ids&fixtures:continue
    fixtures|=fixture_ids;kept.append(prop)
   proposals=kept
  if not proposals:reasons.append('NO_VALID_DIVERSIFIED_COMBINATION' if key!='singles' else 'NO_VALID_SELECTION')
 by_id={r['qualification_id']:r for r in rows};stake=plan['bankroll'] if plan else s['stake']
 iso=lambda leg:{k:(utc(v).isoformat() if isinstance(v,datetime) else v) for k,v in leg.items()}
 tickets=[{'legs':[iso(by_id[i]) for i in prop['qualification_ids']],'combined_odds':float(prop['combined_odds']),'probability_lower_bound':float(prop['probability_lower_bound']),
           'probability_upper_bound':float(prop['probability_upper_bound']),'correlation_status':prop['correlation_status'],
           'paper_stake':stake,'potential_return':round(stake*float(prop['combined_odds']),2) if stake else None} for prop in proposals]
 first=tickets[0] if tickets else None
 result={'mode':'PAPER','trigger':trigger,'programme':key,'candidate_count':len(rows),'excluded':dict(excluded),'tickets':tickets,
         'legs':first['legs'] if first and key!='singles' else [leg for t in tickets for leg in t['legs']],
         'selections':len(first['legs']) if first and key!='singles' else len(tickets),
         'combined_odds':first['combined_odds'] if first and key!='singles' else (round(sum(t['combined_odds'] for t in tickets)/len(tickets),3) if tickets else None),
         'probability_lower_bound':first['probability_lower_bound'] if first else None,'probability_upper_bound':first['probability_upper_bound'] if first else None,
         'correlation_status':first['correlation_status'] if first else None,'remaining_daily_capacity':remaining-len(tickets) if key=='singles' else None,
         'reasons':reasons,'policy':cfg,'evaluated_at':at.isoformat(),'plan':plan,'reachable_odds':round(reach,2) if reach else None,
         'risk_note':'Paper composition only; no wager or booking code. Multi-leg joint probability is recorded as bounds, never as an independent product.'}
 run=m.StrategyRun(programme_key=key,idempotency_key=ident,status='COMPLETED' if tickets else 'BLOCKED',created_at=at,result=result)
 db.add(run);db.flush()
 db.add(m.AuditEvent(actor=f'{key}-engine',action=f'strategy.{key}_run',correlation_id=run.id,payload={'status':run.status,'tickets':len(tickets),'reasons':reasons}))
 return run


def cycle(factory,key,at=None):
 with factory.begin() as db:
  run=run_once(db,key,at)
  return {'run_id':run.id,'status':run.status,'tickets':len((run.result or {}).get('tickets') or []),'reasons':(run.result or {}).get('reasons',[])}


# Settlement and read models ------------------------------------------------------------------------------

def settle_ticket(db,ticket):
 states=[]
 for leg in ticket.get('legs') or []:
  result=db.scalar(select(m.Result).where(m.Result.fixture_id==leg['fixture_id']).order_by(m.Result.version.desc()).limit(1))
  if result is None:return None
  state=((result.outcome or {}).get('outcomes') or {}).get(leg['market_key'],{}).get(leg['outcome_key'])
  if state not in ('WON','LOST'):return None
  states.append(state)
 return ('WON' if all(s=='WON' for s in states) else 'LOST') if states else None


def run_tickets(run):
 res=run.result or {}
 if res.get('tickets'):return res['tickets']
 return [{'legs':res['legs'],'combined_odds':res.get('combined_odds')}] if res.get('legs') else []


def settle(db,run):
 """WON/LOST for a single-ticket run, or 'n/m WON' summary for multi-ticket runs; None until every ticket is settled."""
 if run.status!='COMPLETED':return None
 states=[settle_ticket(db,t) for t in run_tickets(run)]
 if not states or any(s is None for s in states):return None
 return states[0] if len(states)==1 else f"{sum(s=='WON' for s in states)}/{len(states)} WON"


def run_dict(db,r):
 res=r.result or {}
 return {'id':r.id,'number':None,'created_at':r.created_at,'status':r.status,'selections':res.get('selections',len(res.get('legs') or res.get('proposals') or [])),
         'combined_odds':res.get('combined_odds'),'reasons':res.get('reasons',[]),'trigger':res.get('trigger','admin'),'candidate_count':res.get('candidate_count'),
         'probability_lower_bound':res.get('probability_lower_bound'),'probability_upper_bound':res.get('probability_upper_bound'),'legs':res.get('legs',[]),
         'tickets':res.get('tickets',[]),'settlement':settle(db,r),'plan':res.get('plan')}


def runs(db,key,limit=50,offset=0):
 total=db.scalar(select(func.count()).select_from(m.StrategyRun).where(m.StrategyRun.programme_key==key)) or 0
 rows=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key).order_by(m.StrategyRun.created_at.desc()).limit(limit).offset(offset)).all()
 out=[]
 for i,r in enumerate(rows):
  d=run_dict(db,r);d['number']=total-offset-i;out.append(d)
 return {'total':total,'items':out}


def _settled_tickets(db,runs_):
 out=[]
 for r in runs_:
  if r.status!='COMPLETED':continue
  for t in run_tickets(r):
   s=settle_ticket(db,t)
   if s:out.append((t,s))
 return out


def _leg_states(db,runs_):
 """Verified WON/LOST state of every leg of every completed ticket (draw rate for the Weekly Draw Centre)."""
 out=[]
 for r in runs_:
  if r.status!='COMPLETED':continue
  for t in run_tickets(r):
   for leg in t.get('legs') or []:
    st=settle_ticket(db,{'legs':[leg]})
    if st:out.append(st)
 return out


def _leg_rate(states):return round(sum(x=='WON' for x in states)*100/len(states),1) if states else None


def _window(db,key,start,end):
 rows=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.created_at>=start,m.StrategyRun.created_at<end)).all()
 done=[r for r in rows if r.status=='COMPLETED'];tickets=[t for r in done for t in run_tickets(r)]
 settled=_settled_tickets(db,done)
 return {'runs':len(rows),'completed':len(done),'blocked':sum(r.status=='BLOCKED' for r in rows),
         'avg_selections':sum((r.result or {}).get('selections',0) for r in done)/len(done) if done else None,
         'avg_odds':sum(t.get('combined_odds') or 0 for t in tickets)/len(tickets) if tickets else None,
         'hit_rate':sum(s=='WON' for _,s in settled)*100/len(settled) if settled else None,'leg_hit_rate':_leg_rate(_leg_states(db,done))}


def overview(db,key,at=None):
 at=at or datetime.now(timezone.utc)
 all_runs=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key)).all()
 done=[r for r in all_runs if r.status=='COMPLETED'];tickets=[t for r in done for t in run_tickets(r)]
 now_w,prev_w=_window(db,key,at-timedelta(days=1),at+timedelta(seconds=1)),_window(db,key,at-timedelta(days=2),at-timedelta(days=1))
 change=lambda a,b:round((a-b)*100/b,1) if b else None
 diff=lambda a,b,d=1:round(a-b,d) if a is not None and b is not None else None
 rows,excluded=programme_rows(key,*eligible(db,at));rows=strip(rows);cfg=policy(key);s=SETTINGS[key]
 last=max(all_runs,key=lambda r:utc(r.created_at),default=None)
 settled=_settled_tickets(db,done)
 from app.modules.autonomy.service import runtime_status
 rt=runtime_status(db)
 next_run=datetime.strptime(bucket(key,at),'%Y%m%d%H%M').replace(tzinfo=timezone.utc)+timedelta(minutes=s['bucket_minutes'])
 return {'mode':'PAPER','programme':key,'policy':cfg,'readiness':'READY_FOR_QUALIFIED_DATA' if len(rows)>=cfg['min_legs'] else 'WAITING_FOR_QUALIFIED_DATA',
         'recorded_runs':len(all_runs),'completed':len(done),'blocked':sum(r.status=='BLOCKED' for r in all_runs),'tickets':len(tickets),
         'avg_selections':round(sum((r.result or {}).get('selections',0) for r in done)/len(done),1) if done else None,
         'avg_combined_odds':round(sum(t.get('combined_odds') or 0 for t in tickets)/len(tickets),2) if tickets else None,
         'success_rate':round(sum(st=='WON' for _,st in settled)*100/len(settled),1) if settled else None,'settled_tickets':len(settled),
         'leg_hit_rate':_leg_rate(_leg_states(db,done)),'plan':rollover_state(db,at) if key=='rollover' else None,
         'trend':{'runs':change(now_w['runs'],prev_w['runs']),'completed':change(now_w['completed'],prev_w['completed']),'blocked':change(now_w['blocked'],prev_w['blocked']),
                  'avg_selections':diff(now_w['avg_selections'],prev_w['avg_selections']),'avg_odds':diff(now_w['avg_odds'],prev_w['avg_odds'],2) if key=='singles' else (change(now_w['avg_odds'] or 0,prev_w['avg_odds']) if now_w['avg_odds'] is not None and prev_w['avg_odds'] else None),
                  'success_rate_pp':diff(now_w['hit_rate'],prev_w['hit_rate']),'leg_hit_rate_pp':diff(now_w['leg_hit_rate'],prev_w['leg_hit_rate'])},
         'eligible_candidates':len(rows),'excluded':excluded,'last_run':run_dict(db,last) if last else None,'next_run_at':next_run.isoformat(),
         'today':{'used':sum(len(run_tickets(r)) for r in _today_runs(db,key,at)),'cap':cfg['daily_cap']},
         'runtime':{'worker_online':rt.get('worker_online')},'pipeline':pipeline(db,key,at,rows,last),'validation':validation(db,at),'analytics':analytics(db,key,at),'system':system(db,key,at,last,rt),
         'notice':'Paper composition only. Tickets are built exclusively from QUALIFIED opportunities with fresh prices; when there are not enough, the run is BLOCKED with reasons.'}


def pipeline(db,key,at,rows,last):
 qualified=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0
 res=(last.result if last else None) or {};built=bool(last and last.status=='COMPLETED')
 s=lambda k,name,sub,ok,detail:{'key':k,'name':name,'sub':sub,'status':'DONE' if ok else 'WAITING','detail':detail}
 waiting=', '.join(res.get('reasons',[])) or 'No run yet'
 if key=='rollover':
  plan=rollover_state(db,at)
  return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),
          s('screen','Screen','Sequential',plan['status']!='AWAITING_SETTLEMENT',f"Plan {plan['plan_id']} day {plan['day']}/{plan['plan_days']}: "+('previous step awaiting verified result' if plan['status']=='AWAITING_SETTLEMENT' else 'ready for next step')),
          s('validate','Validate','Gates',bool(rows),f'{len(rows)} selections in the target odds band with edge ≥ 1.5 pp'),
          s('plan','Plan','Rollover',built,f"Paper bankroll {plan['bankroll']:,.2f}"),
          s('build','Build Ticket','Paper',built,'1 paper single' if built else waiting),s('publish','Publish','Record',bool(last),'Every run recorded, including blocked runs')]
 if key=='draws':
  return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),
          s('filter','Filter','Draw Markets',bool(rows),f'{len(rows)} full-time draw selections with edge ≥ 1.5 pp'),
          s('validate','Validate','Gates',bool(rows),'Named qualification gates re-checked'),
          s('select','Select','Combinations',built,'Leg targets 2, 5, 8, 10; no selection reused across tickets'),
          s('build','Build Ticket','Paper',built,f"{len(res.get('tickets') or [])} paper tickets" if built else waiting),s('publish','Publish','Record',bool(last),'Every run recorded, including blocked runs')]
 if key=='jackpot':
  floor=float(MIN_COMBINED_ODDS[key]);reach=reachable_odds(rows,key)
  return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),
          s('screen','Screen','High Odds',bool(reach and reach>=floor),f'Best reachable combined odds {reach:,.0f} vs floor {floor:,.0f}' if reach else f'Fewer than {PROGRAMMES[key]["min_legs"]} fresh eligible opportunities'),
          s('validate','Validate','Gates',bool(rows),'Named qualification gates re-checked'),
          s('optimise','Optimise','Combinations',built,'Bounded search, one fixture per leg, odds within policy'),
          s('build','Build Ticket','Jackpot',built,f"{res.get('selections',0)} legs" if built else waiting),s('publish','Publish','Paper',bool(last),'Every run recorded, including blocked runs')]
 if key=='singles':
  return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),s('validate','Validate','Evidence',bool(rows),'Named qualification gates re-checked'),
          s('select','Select','Single',len(rows)>=1,f'{len(rows)} fresh eligible opportunities'),s('risk','Check Risk','Exposure',built,'Daily cap and one per fixture per day'),
          s('build','Build Ticket','Paper',built,f"{len(res.get('tickets') or [])} paper singles" if built else waiting),s('publish','Publish','Record',bool(last),'Every run recorded, including blocked runs')]
 return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),s('select','Select','Optimise',len(rows)>=PROGRAMMES[key]['min_legs'],f'{len(rows)} fresh eligible opportunities'),
         s('validate','Validate','Gates',bool(rows),'Named qualification gates re-checked'),s('build','Build','Ticket',built,f"{res.get('selections',0)} selections" if built else 'No ticket built in the latest run'),
         s('risk','Risk Check','Exposure',built,'Caps, unique fixtures and odds limit applied'),s('publish','Publish','Paper',built,'Recorded as paper composition' if built else waiting)]


def validation(db,at):
 """Requirement pass rates over all QUALIFIED decisions of upcoming fixtures (None when there are none)."""
 rows=db.execute(select(m.Qualification,m.Odds,m.Fixture).join(m.Odds,m.Qualification.odds_id==m.Odds.id).join(m.Prediction,m.Qualification.prediction_id==m.Prediction.id)
                 .join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id).where(m.Qualification.decision=='QUALIFIED',m.Fixture.kickoff_at>at)).all()
 n=len(rows)
 def rate(fn):return round(sum(1 for r in rows if fn(*r))*100/n,1) if n else None
 integrity=lambda q,o,f:db.get(m.MarketEvidence,o.id) is not None
 model_market=lambda q,o,f:all((q.gates or {}).get(g)=='PASS' for g in ('model','calibration','market_mapping','value'))
 controls=lambda q,o,f:timedelta(0)<=at-utc(o.observed_at)<=FRESHNESS and (q.gates or {}).get('market_risk','PASS')=='PASS'
 return {'qualified_upcoming':n,'items':[{'key':'source_integrity','name':'Source integrity','pass_rate':rate(integrity),'detail':'Price backed by stored source evidence'},
         {'key':'model_market','name':'Model & market checks','pass_rate':rate(model_market),'detail':'Model, calibration, mapping and value gates'},
         {'key':'ticket_controls','name':'Ticket controls','pass_rate':rate(controls),'detail':'Fresh price (≤15 min) and market risk within policy'}]}


def analytics(db,key,at,count=30):
 recent=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key).order_by(m.StrategyRun.created_at.desc()).limit(count)).all()
 done=[r for r in recent if r.status=='COMPLETED'];tickets=[t for r in done for t in run_tickets(r)];settled=_settled_tickets(db,done)
 stake=lambda t:t.get('paper_stake') or 1
 roi=sum(((t.get('combined_odds') or 0)-1)*stake(t) if st=='WON' else -stake(t) for t,st in settled)/sum(stake(t) for t,_ in settled)*100 if settled else None
 by_day=defaultdict(lambda:[0,0])
 for r in db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.created_at>=at-timedelta(days=30))):
  d=utc(r.created_at).date().isoformat();by_day[d][1]+=1;by_day[d][0]+=r.status=='COMPLETED'
 return {'runs':len(recent),'completion_rate':round(len(done)*100/len(recent),1) if recent else None,'avg_legs':round(sum((r.result or {}).get('selections',0) for r in done)/len(done),1) if done else None,
         'avg_odds':round(sum(t.get('combined_odds') or 0 for t in tickets)/len(tickets),2) if tickets else None,'tickets':len(tickets),'settled':len(settled),
         'paper_hit_rate':round(sum(st=='WON' for _,st in settled)*100/len(settled),1) if settled else None,'leg_hit_rate':_leg_rate(_leg_states(db,done)),'paper_roi':round(roi,1) if roi is not None else None,
         'daily':[{'date':d,'completion_rate':round(c*100/t,1),'runs':t} for d,(c,t) in sorted(by_day.items())]}


def system(db,key,at,last,rt):
 q=db.get(m.ProviderSyncState,'qualification:autonomous')
 q_at=(q.payload or {}).get('at') if q else None
 fresh=lambda iso,mins:bool(iso) and at-utc(datetime.fromisoformat(iso) if isinstance(iso,str) else iso)<=timedelta(minutes=mins)
 last_at=last.created_at if last else None;size=SETTINGS[key]['bucket_minutes'];weekly=SETTINGS[key].get('weekly') or SETTINGS[key].get('daily')
 st=lambda name,ok,detail:{'name':name,'status':'HEALTHY' if ok else 'WAITING','detail':detail}
 return [st('Qualified opportunities feed',fresh(q_at,10),f'Last qualification cycle {q_at or "never"}'),
         st('Validation engine',True,'Named gates re-checked per opportunity'),st('Risk & exposure controls',True,f"Daily cap {PROGRAMMES[key]['daily_cap']}, max odds {PROGRAMMES[key]['max_odds']}"),
         st('Programme builder',bool(last_at) and utc(last_at)>=period_start(key,at) if weekly else fresh(last_at,size*2+5),f'Last run {utc(last_at).isoformat() if last_at else "never"}'),
         {'name':'Scheduler (auto run)','status':'ACTIVE' if rt.get('worker_online') else 'OFFLINE','detail':f"Autonomy cycle, {policy(key)['schedule'].lower()} (caught up on restart)" if weekly else f'Autonomy cycle, {size}-minute buckets'}]
