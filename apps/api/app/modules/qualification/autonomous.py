"""Autonomous, paper-only market qualification (adapted from the v3.7 qualification patch).

Changes from the patch, by design:
* runs as a step of the existing autonomy cycle (no second worker process / scheduler);
* evaluates every ACTIVE-model forecast of an UPCOMING fixture against the latest evidence-backed price of
  every bookmaker for the same market/outcome (the patch took the 200 newest forecasts and one price);
* adds the gates the pipeline already applies elsewhere, so a decision means the same thing on every path:
  - market_scanner.evaluate -> markets.service.evaluate_market (research, model, calibration, freshness, mapping, value)
    plus the probability lower-bound value gate ('uncertainty'),
  - 'market_risk' exactly as the Evaluate stage: complete outcome set from one bookmaker, overround 0.90-1.25.
  The pipeline's Qualify stage reuses an existing decision for the same prediction/odds pair, so it stays consistent;
* one immutable decision per (prediction, odds snapshot); new prices create new snapshots and new decisions.
"""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc

OVERROUND=(.90,1.25)
GATES=('research','model','calibration','odds_freshness','market_mapping','value','uncertainty','market_risk')
GATE_NAMES={'research':'Evidence completeness','model':'Model validation','calibration':'Probability calibration','odds_freshness':'Odds freshness (≤15 min)',
            'market_mapping':'Market mapping','value':'Expected value (EV)','uncertainty':'Lower-bound value','market_risk':'Risk assessment'}
BREAKDOWN=[('negative_ev','Negative expected value',{'INSUFFICIENT_VALUE','NO_CONSERVATIVE_EDGE','NO_PROBABILITY_INTERVAL'}),
           ('stale_odds','Stale or missing odds',{'ODDS_STALE_OR_FUTURE','NO_MATCHING_BOOKMAKER_PRICE'}),
           ('research','Insufficient research evidence',{'RESEARCH_UNVERIFIED_OR_LEAKAGE','MISSING_FEATURE_OR_RESEARCH'}),
           ('model','Unsupported market / model',{'MODEL_NOT_INDEPENDENTLY_APPROVED','CALIBRATION_NOT_VERIFIED'}),
           ('risk','Market risk (incomplete market or margin)',{'INCOMPLETE_MARKET','BOOKMAKER_MARGIN_OUT_OF_RANGE'}),
           ('other','Other / quality gate failed',set())]


def _now():return datetime.now(timezone.utc)


def candidates(db,at,with_pending=False):
 """(prediction, model, odds) for upcoming fixtures: every bookmaker's latest evidence-backed price per forecast.
 Forecasts without any price are counted (and optionally returned) as PENDING."""
 from app.modules.market_scanner.service import forecasts
 from app.modules.markets.catalogue import latest_quotes
 fixtures=db.scalars(select(m.Fixture.id).join(m.Prediction,m.Prediction.fixture_id==m.Fixture.id).where(m.Fixture.kickoff_at>at).distinct()).all()
 out=[];pending=0;waiting=[]
 for fixture_id in fixtures:
  fixture=db.get(m.Fixture,fixture_id);cutoff=min(at,utc(fixture.kickoff_at))
  quotes=latest_quotes(db,fixture_id,at)
  by_market=defaultdict(dict)
  for (book,market,outcome),(odds,_) in quotes.items():by_market[(book,market)][outcome]=odds
  for (market,outcome),(prediction,model) in forecasts(db,fixture_id,cutoff).items():
   priced=[(book,group) for (book,mk),group in by_market.items() if mk==market and outcome in group]
   if not priced:
    pending+=1
    if with_pending:waiting.append((prediction,model,fixture))
    continue
   for book,group in priced:out.append((prediction,model,group[outcome],group))
 return (out,pending,waiting) if with_pending else (out,pending)


def market_risk(prediction,group):
 """Same check as the pipeline Evaluate stage: one bookmaker's complete outcome set with a sane overround."""
 from app.modules.prediction.market_model import groups as outcome_groups
 expected=outcome_groups().get(prediction.market_key) or ({'HOME','DRAW','AWAY'} if prediction.market_key=='1X2' else None)
 if expected and not set(expected)<=set(group):return 'FAIL','INCOMPLETE_MARKET',None
 if len(group)<2:return 'FAIL','INCOMPLETE_MARKET',None
 overround=sum(1/float(o.decimal_odds) for o in group.values())
 if not OVERROUND[0]<=overround<=OVERROUND[1]:return 'FAIL','BOOKMAKER_MARGIN_OUT_OF_RANGE',overround
 return 'PASS',None,overround


def decide(db,prediction,model,odds,group,at):
 from app.modules.market_scanner.service import evaluate
 row=evaluate(db,prediction,model,odds,at)
 risk,risk_reason,overround=market_risk(prediction,group)
 reasons=list(row['reasons'])+([risk_reason] if risk_reason else [])
 gates={k:v for k,v in (row.get('gates') or {}).items()}
 gates['uncertainty']='PASS' if row['conservative_ev'] is not None and row['conservative_ev']>0 else 'FAIL'
 gates['market_risk']=risk
 decision='QUALIFIED' if row['decision']=='QUALIFIED' and risk=='PASS' else 'REJECTED'
 metrics={'probability':row['probability'],'lower':row['lower'],'upper':row['upper'],'implied_probability':round(100/float(odds.decimal_odds),2),
          'edge':round(row['probability']-100/float(odds.decimal_odds),2),'expected_value':row['ev'],'conservative_ev':row['conservative_ev'],
          'overround':round(overround,4) if overround else None,'skill':row.get('skill'),'model':row['model']}
 record=m.Qualification(prediction_id=prediction.id,odds_id=odds.id,decision=decision,decided_at=at,
                        gates={**gates,'reason_codes':sorted(set(reasons)) if decision!='QUALIFIED' else [],'metrics':metrics,'origin':'autonomous-qualification'})
 db.add(record);db.flush()
 return record


def cycle(factory,at=None,limit=2000):
 """One autonomous qualification pass; idempotent per prediction/odds pair."""
 at=at or _now();report={'evaluated':0,'qualified':0,'rejected':0,'skipped_existing':0,'pending_no_price':0,'errors':[]}
 with factory.begin() as db:
  pairs,pending=candidates(db,at);report['pending_no_price']=pending
  for prediction,model,odds,group in pairs[:limit]:
   if db.scalar(select(m.Qualification.id).where(m.Qualification.prediction_id==prediction.id,m.Qualification.odds_id==odds.id).limit(1)):
    report['skipped_existing']+=1;continue
   try:
    with db.begin_nested():record=decide(db,prediction,model,odds,group,at)
    report['evaluated']+=1;report['qualified' if record.decision=='QUALIFIED' else 'rejected']+=1
   except Exception as exc:
    if len(report['errors'])<10:report['errors'].append({'prediction_id':prediction.id,'code':type(exc).__name__})
  from app.modules.autonomy.open_intelligence import cached
  state=cached(db,'qualification:autonomous',None);state.payload={**report,'at':at.isoformat()};state.last_full_at=at;state.next_check_at=at+timedelta(minutes=5)
 return report


# Read models ----------------------------------------------------------------------------------------

def _rows(db,status=None,search=None,sport=None,country=None,competition=None,category=None):
 from app.modules.markets.catalogue import normalize
 query=(select(m.Qualification,m.Prediction,m.Odds,m.Fixture,m.Competition,m.Sport)
        .join(m.Prediction,m.Qualification.prediction_id==m.Prediction.id).join(m.Odds,m.Qualification.odds_id==m.Odds.id)
        .join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id).join(m.Competition,m.Fixture.competition_id==m.Competition.id)
        .join(m.Sport,m.Sport.id==m.Competition.sport_id))
 if status and status!='ALL':query=query.where(m.Qualification.decision==status)
 if sport:query=query.where(m.Sport.name==sport)
 if country:query=query.where(m.Competition.country==country)
 if competition:query=query.where(m.Competition.id==competition)
 if search:
  term='%'+search.strip()[:100]+'%'
  query=query.where(m.Fixture.home_name.ilike(term)|m.Fixture.away_name.ilike(term)|m.Prediction.market_key.ilike(term)|m.Prediction.outcome_key.ilike(term))
 rows=db.execute(query.order_by(m.Qualification.decided_at.desc())).all()
 if category:
  rows=[r for r in rows if (d:=db.get(m.MarketDefinition,normalize(db,'*',r[1].market_key,'football')[0])) is not None and d.category_key==category]
 return rows


def decision_dict(db,q,p,o,f,c,s):
 from app.modules.market_scanner.service import market_name,selection_name,confidence
 metrics=(q.gates or {}).get('metrics') or {}
 prob=metrics.get('probability',round(float(p.probability)*100,1));implied=metrics.get('implied_probability',round(100/float(o.decimal_odds),2))
 return {'id':q.id,'fixture_id':f.id,'fixture':f'{f.home_name} vs {f.away_name}','sport':s.name,'competition':c.name,'country':c.country,'kickoff_at':f.kickoff_at,
         'market':market_name(p.market_key),'market_key':p.market_key,'selection':selection_name(p.market_key,p.outcome_key),'bookmaker':o.bookmaker,'odds':float(o.decimal_odds),
         'probability':prob,'lower':metrics.get('lower'),'upper':metrics.get('upper'),'implied_probability':implied,'edge':metrics.get('edge',round(prob-implied,2)),
         'expected_value':metrics.get('expected_value'),'conservative_ev':metrics.get('conservative_ev'),
         'confidence':confidence([(metrics.get('lower'),metrics.get('upper'))]) if metrics.get('lower') is not None else None,
         'decision':q.decision,'reason_codes':(q.gates or {}).get('reason_codes',[]),'gates':{k:v for k,v in (q.gates or {}).items() if k in GATES},
         'decided_at':q.decided_at,'odds_observed_at':o.observed_at,'origin':(q.gates or {}).get('origin','pipeline')}


def pending_count(db,at):
 return candidates(db,at)[1]


def pending_rows(db,at,search=None,sport=None,country=None,competition=None,category=None):
 """Forecasts of upcoming fixtures that have no source-backed price yet (decision PENDING, never simulated)."""
 from app.modules.market_scanner.service import market_name,selection_name,interval,confidence,market_sort_key
 from app.modules.markets.catalogue import normalize
 _,_,waiting=candidates(db,at,with_pending=True);rows=[]
 for prediction,model,fixture in waiting:
  comp=db.get(m.Competition,fixture.competition_id);sp=db.get(m.Sport,comp.sport_id)
  if sport and sp.name!=sport or country and comp.country!=country or competition and comp.id!=competition:continue
  if category:
   d=db.get(m.MarketDefinition,normalize(db,'*',prediction.market_key,'football')[0])
   if d is None or d.category_key!=category:continue
  text=' '.join([fixture.home_name,fixture.away_name,prediction.market_key,prediction.outcome_key,market_name(prediction.market_key)]).lower()
  if search and search.strip().lower() not in text:continue
  lower,upper=interval(prediction.details);p=round(float(prediction.probability)*100,1)
  lo,hi=(round(lower*100,1),round(upper*100,1)) if lower is not None and upper is not None else (None,None)
  rows.append({'id':'pending:'+prediction.id,'fixture_id':fixture.id,'fixture':f'{fixture.home_name} vs {fixture.away_name}','sport':sp.name,'competition':comp.name,'country':comp.country,
               'kickoff_at':fixture.kickoff_at,'market':market_name(prediction.market_key),'market_key':prediction.market_key,'selection':selection_name(prediction.market_key,prediction.outcome_key),
               'outcome_key':prediction.outcome_key,'bookmaker':None,'odds':None,'probability':p,'lower':lo,'upper':hi,'implied_probability':None,'edge':None,'expected_value':None,'conservative_ev':None,
               'confidence':confidence([(lo,hi)]) if lo is not None else None,'decision':'PENDING','reason_codes':['AWAITING_SOURCE_BACKED_PRICE'],
               'gates':{'research':'PASS','model':'PASS','calibration':'PASS','odds_freshness':'FAIL'},'decided_at':None,'odds_observed_at':None,'origin':'pending'})
 rows.sort(key=lambda r:(r['kickoff_at'],r['fixture'],market_sort_key(r['market_key'],r['outcome_key'])))
 return rows


def summary(db,at=None):
 at=at or _now()
 total=db.scalar(select(func.count()).select_from(m.Qualification)) or 0
 qualified=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0
 rejected=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='REJECTED')) or 0
 state=db.get(m.ProviderSyncState,'qualification:autonomous')
 from app.modules.autonomy.service import runtime_status
 rt=runtime_status(db)
 return {'evaluated':total,'qualified':qualified,'rejected':rejected,'pending':pending_count(db,at),'qualification_rate':round(qualified*100/total,1) if total else None,
         'last_decision_at':db.scalar(select(func.max(m.Qualification.decided_at))),'last_cycle':(state.payload if state else None),'next_cycle_at':state.next_check_at if state else None,
         'runtime':{'worker_online':rt.get('worker_online'),'next_run_at':rt.get('next_run_at')},'pipeline':pipeline(db,at,total,qualified),'gates':gate_summary(db,at),
         'last_cycle_at':(state.payload or {}).get('at') if state else None,'trend':trend(db,at),
         'mode':'PAPER','notice':'Decisions are paper-only. A forecast without a source-backed price stays Pending; no price or probability is simulated.'}


def pipeline(db,at,total,qualified):
 from app.modules.prediction.prospective import REQUIRED_APPROVALS
 active=[x for x in db.scalars(select(m.ModelVersion).where(m.ModelVersion.status=='ACTIVE')) if all((x.validation or {}).get(k) is True for k in REQUIRED_APPROVALS)]
 upcoming=select(m.Fixture.id).where(m.Fixture.kickoff_at>at)
 dossiers=db.scalar(select(func.count(func.distinct(m.Research.fixture_id))).where(m.Research.status=='VERIFIED',m.Research.fixture_id.in_(upcoming))) or 0
 fresh=db.scalar(select(func.count()).select_from(m.Odds).where(m.Odds.fixture_id.in_(upcoming),m.Odds.observed_at>=at-timedelta(minutes=15))) or 0
 forecasts=db.scalar(select(func.count()).select_from(m.Prediction).where(m.Prediction.fixture_id.in_(upcoming))) or 0
 s=lambda key,name,sub,ok,detail:{'key':key,'name':name,'sub':sub,'status':'DONE' if ok else 'WAITING','detail':detail}
 return [s('predict','Predict','Models',bool(active and forecasts),f'{len(active)} approved models, {forecasts} forecasts'),
         s('validate','Validate','Evidence',dossiers>0,f'{dossiers} upcoming fixtures with verified research'),
         s('verify','Verify','Odds',fresh>0,f'{fresh} fresh prices (≤15 min)' if fresh else 'No fresh source-backed prices'),
         s('calibrate','Calibrate','Probability',bool(active),'Calibration verified for active models' if active else 'No calibrated model'),
         s('evaluate','Evaluate','Edge/EV',total>0,f'{total} decisions recorded'),
         s('assess','Assess','Risk',total>0,'Margin and market completeness checked per decision'),
         s('qualify','Qualify','Decision',qualified>0,f'{qualified} qualified' if qualified else 'No qualified decisions')]


PRICE_INDEPENDENT=('research','model','calibration')


def gate_summary(db,at=None):
 """Pass rates from stored decisions. Pending forecasts (published only for verified research by approved, calibrated
 models) also count for the price-independent gates, and as not fresh for odds freshness. Price-dependent gates use decisions only."""
 at=at or _now()
 counts={g:[0,0] for g in GATES}
 for gates in db.scalars(select(m.Qualification.gates)):
  for g in GATES:
   if isinstance(gates,dict) and g in gates:counts[g][0]+=gates[g]=='PASS';counts[g][1]+=1
 from app.modules.prediction.prospective import REQUIRED_APPROVALS
 for prediction,model,fixture in candidates(db,at,with_pending=True)[2]:
  research=db.scalar(select(m.Research.id).where(m.Research.fixture_id==fixture.id,m.Research.status=='VERIFIED').limit(1)) is not None
  approved=model.status=='ACTIVE' and all((model.validation or {}).get(k) is True for k in REQUIRED_APPROVALS)
  for g,ok in (('research',research),('model',approved),('calibration',approved and (model.validation or {}).get('calibration_verified') is True),('odds_freshness',False)):
   counts[g][0]+=ok;counts[g][1]+=1
 return [{'key':g,'name':GATE_NAMES[g],'passed':p,'evaluated':t,'pass_rate':round(p*100/t,1) if t else None} for g,(p,t) in counts.items()]


def breakdown(db):
 rejected=db.scalars(select(m.Qualification.gates).where(m.Qualification.decision=='REJECTED')).all()
 out={k:0 for k,_,_ in BREAKDOWN};total=len(rejected);codes=defaultdict(int)
 for gates in rejected:
  reasons=set((gates or {}).get('reason_codes') or [])
  for r in reasons:codes[r]+=1
  hit=next((k for k,_,members in BREAKDOWN if reasons&members),'other')
  out[hit]+=1
 return {'rejected':total,'categories':[{'key':k,'name':name,'count':out[k],'share':round(out[k]*100/total,1) if total else None} for k,name,_ in BREAKDOWN],
         'reason_codes':dict(sorted(codes.items(),key=lambda kv:-kv[1])),'note':'Each rejection is assigned to its primary category; one decision may carry several reason codes.'}


def history(db,days=30,at=None):
 at=at or _now()
 rows=db.execute(select(func.date(m.Qualification.decided_at),m.Qualification.decision,func.count()).where(m.Qualification.decided_at>=at-timedelta(days=days))
                 .group_by(func.date(m.Qualification.decided_at),m.Qualification.decision)).all()
 out=defaultdict(lambda:{'qualified':0,'rejected':0})
 for day,decision,n in rows:out[str(day)]['qualified' if decision=='QUALIFIED' else 'rejected']+=n
 return [{'date':k,**v} for k,v in sorted(out.items(),reverse=True)]


def comparison(db,at=None,limit=100):
 """Model probability vs the best available price for every forecast of an upcoming fixture (priced or not)."""
 from app.modules.market_scanner.service import forecasts,market_name,selection_name as outcome_label
 from app.modules.markets.catalogue import latest_quotes
 at=at or _now();out=[]
 for fixture in db.scalars(select(m.Fixture).join(m.Prediction,m.Prediction.fixture_id==m.Fixture.id).where(m.Fixture.kickoff_at>at).distinct().order_by(m.Fixture.kickoff_at)):
  quotes=latest_quotes(db,fixture.id,at)
  for (market,outcome),(prediction,model) in forecasts(db,fixture.id,min(at,utc(fixture.kickoff_at))).items():
   prices=[(float(o.decimal_odds),book,o.observed_at) for (book,mk,oc),(o,_) in quotes.items() if mk==market and oc==outcome]
   best=max(prices,default=None);p=round(float(prediction.probability)*100,1)
   out.append({'fixture':f'{fixture.home_name} vs {fixture.away_name}','kickoff_at':fixture.kickoff_at,'market':market_name(market),'selection':outcome_label(market,outcome),
               'probability':p,'fair_odds':round(100/p,2) if p else None,'best_odds':best[0] if best else None,'bookmaker':best[1] if best else None,
               'odds_observed_at':best[2] if best else None,'implied_probability':round(100/best[0],1) if best else None,
               'edge':round(p-100/best[0],1) if best else None,'status':'PRICED' if best else 'AWAITING_PRICE'})
 out.sort(key=lambda r:(r['status']!='PRICED',-(r['edge'] if r['edge'] is not None else -999),r['kickoff_at']))
 return out[:limit]


def trend(db,at=None):
 """Change in the last 24 h vs the 24 h before, from stored decisions (None when there is no prior window)."""
 at=at or _now()
 def window(start,end):
  rows=db.execute(select(m.Qualification.decision,func.count()).where(m.Qualification.decided_at>=start,m.Qualification.decided_at<end).group_by(m.Qualification.decision)).all()
  d=dict(rows);q=d.get('QUALIFIED',0);r=d.get('REJECTED',0);return {'evaluated':q+r,'qualified':q,'rejected':r,'rate':q*100/(q+r) if q+r else None}
 now,prev=window(at-timedelta(days=1),at),window(at-timedelta(days=2),at-timedelta(days=1))
 change=lambda a,b:round((a-b)*100/b,1) if b else None
 return {'evaluated':change(now['evaluated'],prev['evaluated']),'qualified':change(now['qualified'],prev['qualified']),'rejected':change(now['rejected'],prev['rejected']),
         'rate_pp':round(now['rate']-prev['rate'],1) if now['rate'] is not None and prev['rate'] is not None else None}
