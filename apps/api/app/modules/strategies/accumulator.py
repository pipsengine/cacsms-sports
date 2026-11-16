"""Autonomous, paper-only Accumulator Engine (adapted from the accumulator integration patch).

Changes from the patch, by design:
* runs as a step of the existing autonomy cycle (15-minute idempotency buckets), no separate worker process;
* composes with the existing optimizer.select_tickets and PROGRAMMES['accumulator'] policy (one policy for
  every path), which never multiplies probabilities as if independent: it records lower/upper bounds only;
* eligibility checks the named qualification gates explicitly (the decision gates dict also stores reason codes
  and metrics, so "every value == PASS" would wrongly reject every decision);
* paper ROI and success are computed only from runs whose legs all have verified results.
"""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from math import prod
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc
from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES

KEY='accumulator'
FRESHNESS=timedelta(minutes=15)
BUCKET_MINUTES=15
REQUIRED_GATES=('research','model','calibration','odds_freshness','market_mapping','value')
OPTIONAL_GATES=('uncertainty','market_risk')  # enforced when recorded (autonomous qualification records them)
APPROVALS=('approved','out_of_sample','calibrated','calibration_verified')


def policy():
 cfg=PROGRAMMES[KEY]
 return {'min_legs':cfg['min_legs'],'max_legs':cfg['max_legs'],'max_odds':float(cfg['max_odds']),'daily_cap':cfg['daily_cap'],
         'freshness_minutes':int(FRESHNESS.total_seconds()//60),'unique_fixture_per_ticket':True,'mode':'PAPER','schedule_minutes':BUCKET_MINUTES}


def gates_pass(gates):
 if not isinstance(gates,dict):return False
 return all(gates.get(g)=='PASS' for g in REQUIRED_GATES) and all(gates.get(g,'PASS')=='PASS' for g in OPTIONAL_GATES)


def eligible(db,at):
 """Fresh, fully qualified opportunities of upcoming fixtures from ACTIVE approved models (with the reason each other one is excluded)."""
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
              'odds':odds,'probability':prob,'ev':round((prob*odds-1)*100,2),'bookmaker':o.bookmaker,'odds_observed_at':o.observed_at})
 out.sort(key=lambda r:-r['ev'])
 return out,dict(excluded)


def bucket(at):return at.strftime('%Y%m%d%H')+f'{(at.minute//BUCKET_MINUTES)*BUCKET_MINUTES:02d}'


def run_once(db,at=None,trigger='autonomous'):
 """Record one paper composition decision for the current 15-minute bucket (idempotent)."""
 at=at or datetime.now(timezone.utc);key=f'auto:{bucket(at)}'
 prior=db.scalar(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY,m.StrategyRun.idempotency_key==key))
 if prior:return prior
 rows,excluded=eligible(db,at);cfg=policy()
 day=at.replace(hour=0,minute=0,second=0,microsecond=0)
 today=db.scalar(select(func.count()).select_from(m.StrategyRun).where(m.StrategyRun.programme_key==KEY,m.StrategyRun.status=='COMPLETED',m.StrategyRun.created_at>=day)) or 0
 reasons=[]
 if today>=cfg['daily_cap']:reasons.append('DAILY_CAP_REACHED')
 if len(rows)<cfg['min_legs']:reasons.append('INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES')
 proposal=None
 if not reasons:
  candidates=[Candidate(r['qualification_id'],r['fixture_id'],Decimal(str(r['odds'])),Decimal(str(r['probability'])),r['market_key'],r['outcome_key'],utc(r['kickoff_at']).isoformat()) for r in rows]
  proposals=select_tickets(candidates,KEY,limit=1)
  proposal=proposals[0] if proposals else None
  if proposal is None:reasons.append('NO_VALID_DIVERSIFIED_COMBINATION')
 legs=[]
 if proposal:
  by_id={r['qualification_id']:r for r in rows}
  legs=[{k:(utc(v).isoformat() if isinstance(v,datetime) else v) for k,v in by_id[i].items()} for i in proposal['qualification_ids']]
 result={'mode':'PAPER','trigger':trigger,'candidate_count':len(rows),'excluded':excluded,'legs':legs,'selections':len(legs),
         'combined_odds':float(proposal['combined_odds']) if proposal else None,
         'probability_lower_bound':float(proposal['probability_lower_bound']) if proposal else None,'probability_upper_bound':float(proposal['probability_upper_bound']) if proposal else None,
         'correlation_status':proposal['correlation_status'] if proposal else None,'reasons':reasons,'policy':cfg,'evaluated_at':at.isoformat(),
         'risk_note':'Joint probability is not assumed independent: only bounds are recorded. Paper composition only; no wager or booking code.'}
 run=m.StrategyRun(programme_key=KEY,idempotency_key=key,status='COMPLETED' if proposal else 'BLOCKED',created_at=at,result=result)
 db.add(run);db.flush()
 db.add(m.AuditEvent(actor='accumulator-engine',action='strategy.accumulator_run',correlation_id=run.id,payload={'status':run.status,'selections':len(legs),'reasons':reasons}))
 return run


def cycle(factory,at=None):
 with factory.begin() as db:
  run=run_once(db,at)
  return {'run_id':run.id,'status':run.status,'reasons':(run.result or {}).get('reasons',[])}


# Read models ------------------------------------------------------------------------------------------

def settle(db,run):
 """WON/LOST/None for a completed run from verified results of every leg (None until all legs are settled)."""
 legs=(run.result or {}).get('legs') or []
 if run.status!='COMPLETED' or not legs:return None
 states=[]
 for leg in legs:
  result=db.scalar(select(m.Result).where(m.Result.fixture_id==leg['fixture_id']).order_by(m.Result.version.desc()).limit(1))
  if result is None:return None
  state=((result.outcome or {}).get('outcomes') or {}).get(leg['market_key'],{}).get(leg['outcome_key'])
  if state not in ('WON','LOST'):return None
  states.append(state)
 return 'WON' if all(s=='WON' for s in states) else 'LOST'


def run_dict(db,r):
 res=r.result or {}
 return {'id':r.id,'number':None,'created_at':r.created_at,'status':r.status,'selections':res.get('selections',len(res.get('legs') or res.get('proposals') or [])),
         'combined_odds':res.get('combined_odds'),'reasons':res.get('reasons',[]),'trigger':res.get('trigger','admin'),'candidate_count':res.get('candidate_count'),
         'probability_lower_bound':res.get('probability_lower_bound'),'probability_upper_bound':res.get('probability_upper_bound'),'legs':res.get('legs',[]),'settlement':settle(db,r)}


def runs(db,limit=50,offset=0):
 total=db.scalar(select(func.count()).select_from(m.StrategyRun).where(m.StrategyRun.programme_key==KEY)) or 0
 rows=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY).order_by(m.StrategyRun.created_at.desc()).limit(limit).offset(offset)).all()
 out=[]
 for i,r in enumerate(rows):
  d=run_dict(db,r);d['number']=total-offset-i;out.append(d)
 return {'total':total,'items':out}


def _window(db,start,end):
 rows=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY,m.StrategyRun.created_at>=start,m.StrategyRun.created_at<end)).all()
 done=[r for r in rows if r.status=='COMPLETED']
 return {'runs':len(rows),'completed':len(done),'blocked':sum(r.status=='BLOCKED' for r in rows),
         'avg_selections':sum((r.result or {}).get('selections',0) for r in done)/len(done) if done else None,
         'avg_odds':sum((r.result or {}).get('combined_odds') or 0 for r in done)/len(done) if done else None}


def overview(db,at=None):
 at=at or datetime.now(timezone.utc)
 all_runs=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY)).all()
 done=[r for r in all_runs if r.status=='COMPLETED']
 now_w,prev_w=_window(db,at-timedelta(days=1),at+timedelta(seconds=1)),_window(db,at-timedelta(days=2),at-timedelta(days=1))
 change=lambda a,b:round((a-b)*100/b,1) if b else None
 rows,excluded=eligible(db,at);cfg=policy()
 last=max(all_runs,key=lambda r:utc(r.created_at),default=None)
 from app.modules.autonomy.service import runtime_status
 rt=runtime_status(db)
 return {'mode':'PAPER','policy':cfg,'readiness':'READY_FOR_QUALIFIED_DATA' if len(rows)>=cfg['min_legs'] else 'WAITING_FOR_QUALIFIED_DATA',
         'recorded_runs':len(all_runs),'completed':len(done),'blocked':sum(r.status=='BLOCKED' for r in all_runs),
         'avg_selections':round(sum((r.result or {}).get('selections',0) for r in done)/len(done),1) if done else None,
         'avg_combined_odds':round(sum((r.result or {}).get('combined_odds') or 0 for r in done)/len(done),2) if done else None,
         'trend':{'runs':change(now_w['runs'],prev_w['runs']),'completed':change(now_w['completed'],prev_w['completed']),'blocked':change(now_w['blocked'],prev_w['blocked']),
                  'avg_selections':round(now_w['avg_selections']-prev_w['avg_selections'],1) if now_w['avg_selections'] is not None and prev_w['avg_selections'] is not None else None,
                  'avg_odds':change(now_w['avg_odds'] or 0,prev_w['avg_odds']) if now_w['avg_odds'] is not None and prev_w['avg_odds'] else None},
         'eligible_candidates':len(rows),'excluded':excluded,'last_run':run_dict(db,last) if last else None,
         'next_run_at':(datetime.strptime(bucket(at),'%Y%m%d%H%M').replace(tzinfo=timezone.utc)+timedelta(minutes=BUCKET_MINUTES)).isoformat(),
         'runtime':{'worker_online':rt.get('worker_online')},'pipeline':pipeline(db,at,rows,last),'validation':validation(db,at),'analytics':analytics(db,at),'system':system(db,at,last,rt),
         'notice':'Paper composition only. Accumulators are built exclusively from QUALIFIED opportunities with fresh prices; when there are not enough, the run is BLOCKED with reasons.'}


def pipeline(db,at,rows,last):
 qualified=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0
 res=(last.result if last else None) or {}
 s=lambda key,name,sub,ok,detail:{'key':key,'name':name,'sub':sub,'status':'DONE' if ok else 'WAITING','detail':detail}
 built=bool(last and last.status=='COMPLETED')
 return [s('fetch','Fetch','Qualified',qualified>0,f'{qualified} qualified decisions'),s('select','Select','Optimise',len(rows)>=PROGRAMMES[KEY]['min_legs'],f'{len(rows)} fresh eligible opportunities'),
         s('validate','Validate','Gates',bool(rows),'Named qualification gates re-checked'),s('build','Build','Ticket',built,f"{res.get('selections',0)} selections" if built else 'No ticket built in the latest run'),
         s('risk','Risk Check','Exposure',built,'Caps, unique fixtures and odds limit applied'),s('publish','Publish','Paper',built,'Recorded as paper composition' if built else ', '.join(res.get('reasons',[])) or 'No run yet')]


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


def analytics(db,at,count=30):
 recent=db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY).order_by(m.StrategyRun.created_at.desc()).limit(count)).all()
 done=[r for r in recent if r.status=='COMPLETED'];settled=[(r,settle(db,r)) for r in done];settled=[(r,s) for r,s in settled if s]
 roi=sum(((r.result or {}).get('combined_odds',0)-1) if s=='WON' else -1 for r,s in settled)/len(settled)*100 if settled else None
 by_day=defaultdict(lambda:[0,0])
 for r in db.scalars(select(m.StrategyRun).where(m.StrategyRun.programme_key==KEY,m.StrategyRun.created_at>=at-timedelta(days=30))):
  d=utc(r.created_at).date().isoformat();by_day[d][1]+=1;by_day[d][0]+=r.status=='COMPLETED'
 return {'runs':len(recent),'completion_rate':round(len(done)*100/len(recent),1) if recent else None,'avg_legs':round(sum((r.result or {}).get('selections',0) for r in done)/len(done),1) if done else None,
         'avg_odds':round(sum((r.result or {}).get('combined_odds') or 0 for r in done)/len(done),2) if done else None,'settled':len(settled),
         'paper_hit_rate':round(sum(s=='WON' for _,s in settled)*100/len(settled),1) if settled else None,'paper_roi':round(roi,1) if roi is not None else None,
         'daily':[{'date':d,'completion_rate':round(c*100/t,1),'runs':t} for d,(c,t) in sorted(by_day.items())]}


def system(db,at,last,rt):
 q=db.get(m.ProviderSyncState,'qualification:autonomous')
 q_at=(q.payload or {}).get('at') if q else None
 fresh=lambda iso,mins:bool(iso) and at-utc(datetime.fromisoformat(iso) if isinstance(iso,str) else iso)<=timedelta(minutes=mins)
 last_at=last.created_at if last else None
 st=lambda name,ok,detail:{'name':name,'status':'HEALTHY' if ok else 'WAITING','detail':detail}
 return [st('Qualified opportunities feed',fresh(q_at,10),f'Last qualification cycle {q_at or "never"}'),
         st('Validation engine',True,'Named gates re-checked per opportunity'),st('Risk & exposure controls',True,f"Daily cap {PROGRAMMES[KEY]['daily_cap']}, max odds {PROGRAMMES[KEY]['max_odds']}"),
         st('Programme builder',fresh(last_at,BUCKET_MINUTES*2+5),f'Last run {utc(last_at).isoformat() if last_at else "never"}'),
         {'name':'Scheduler (auto run)','status':'ACTIVE' if rt.get('worker_online') else 'OFFLINE','detail':'Autonomy cycle, 15-minute buckets'}]
