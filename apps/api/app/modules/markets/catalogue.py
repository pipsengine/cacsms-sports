"""Bookmaker market catalogue, availability discovery and AI market scanning.

Three strictly separate layers:
1. REGISTERED definitions (catalogue_data) - what the platform understands. Never shown as offered.
2. Per-fixture availability - only from source-backed odds snapshots (markets.odds_snapshots + odds_evidence).
3. Scan results - every available outcome evaluated through the existing gates
   (market_scanner.service.evaluate -> markets.service.evaluate_market); probabilities only where an
   ACTIVE model has a recorded capability for that exact market/outcome/line.

Scans run inside the existing Evaluate stage (pipeline/operations.evaluate); no separate orchestrator.
"""
import re
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.markets.catalogue_data import (REGISTRY_VERSION,CATEGORIES,SPORTS,DISCOVERY_ONLY,WHERE_OFFERED,FOOTBALL_GOAL_LINES,MAPPINGS)
from app.modules.research.league import utc

FRESH=timedelta(minutes=15)
SCAN_MIN_INTERVAL=timedelta(minutes=5)
SPORT_ALIASES={'football':'football','soccer':'football','basketball':'basketball','tennis':'tennis','ice hockey':'ice_hockey','hockey':'ice_hockey',
 'baseball':'baseball','volleyball':'volleyball','handball':'handball','cricket':'cricket','table tennis':'table_tennis','badminton':'badminton',
 'rugby':'rugby','american football':'american_football','darts':'darts','snooker':'snooker','boxing':'combat','mma':'combat','esports':'esports'}


def slug(text):return re.sub(r'[^a-z0-9]+','_',str(text).lower()).strip('_')[:80]
def sport_key(name):return SPORT_ALIASES.get(str(name or '').strip().lower(),slug(name))
def definition_id(sport,name):return f'{sport}.{slug(name)}'


# Classification (deterministic, from the registered market name) ---------------------------------

def classify(name):
 n=name.lower()
 kind='LIVE' if '(live)' in n or n.startswith('live ') else 'PLAYER_PROP' if n.startswith(('player','pitcher','goalie','anytime','first goalscorer','last goalscorer','first try','first touchdown','top ')) or 'scorer' in n else \
      'OUTRIGHT' if any(k in n for k in ('to lift trophy','outright','tournament winner')) else 'SCHEDULED'
 if kind=='PLAYER_PROP':category='player'
 elif kind=='LIVE':category='live'
 elif kind=='OUTRIGHT' or 'to qualify' in n or 'to advance' in n:category='outrights'
 elif 'corner' in n:category='corners'
 elif any(k in n for k in ('card','booked','carded')):category='cards'
 elif 'double chance' in n:category='double_chance'
 elif 'both teams to score' in n:category='btts'
 elif any(k in n for k in ('correct','exact score','exact winning round')):category='correct_score'
 elif any(k in n for k in ('handicap','spread','puck line','run line')):category='handicap'
 elif any(k in n for k in ('over/under','total','totals')):category='over_under'
 elif any(k in n for k in ('half','quarter','period','set ','set','inning','frame','map','leg ','leg winner','game winner','round winner')) and not n.startswith('match'):category='segments'
 elif n.startswith(('team ','home team','away team')) or 'clean sheet' in n or 'win to nil' in n:category='team'
 elif any(k in n for k in ('winner','result','moneyline','draw no bet','home or away','win either','win both')):category='match_result'
 elif any(k in n for k in ('goal','points','runs','multigoals','margin','score')):category='goals'
 elif any(k in n for k in ('180','break','checkout','century','method','ko/','submission','decision','knockdown','distance','dragon','baron','tower','blood','kills','wickets','sixes','fours','tries','sacks','aces')):category='sport_specific'
 else:category='specials'
 period='FIRST_HALF' if 'first half' in n else 'SECOND_HALF' if 'second half' in n else 'QUARTER' if 'quarter' in n else 'PERIOD' if 'period' in n else \
        'SET' if re.search(r'\bset\b',n) else 'INNINGS' if 'inning' in n else 'LIVE' if kind=='LIVE' else 'FULL_TIME'
 return kind,category,period


def outcomes_for(name,sport):
 """Normalised outcome semantics; parametric markets carry a single placeholder outcome type."""
 n=name.lower();three_way=sport in ('football','handball','rugby','ice_hockey')
 if 'half-time/full-time' in n:
  return 'enumerated',[(f'{a}/{b}',f'{a}/{b}') for a in ('HOME','DRAW','AWAY') for b in ('HOME','DRAW','AWAY')]
 if 'double chance' in n:return 'enumerated',[('1X','1X'),('X2','X2'),('12','12')]
 if 'odd/even' in n:return 'enumerated',[('ODD','Odd'),('EVEN','Even')]
 if 'yes/no' in n or 'both teams to score' in n or n.startswith(('team to score','team not to score','goal in both','penalty awarded','penalty scored','own goal','overtime','extra innings','century break','nine-dart','tie-break yes','fight goes distance','knockdown yes','super over','match to go to deciding')):
  return 'binary',[('YES','Yes'),('NO','No')]
 if any(k in n for k in ('over/under','total goals','total points','total runs','total sets','total games','total maps','total rounds','total legs','total frames','total kills','total corners','total cards')) and 'exact' not in n:
  return 'line_over_under',[('OVER','Over'),('UNDER','Under')]
 if any(k in n for k in ('handicap','spread','puck line','run line')):
  return ('line_three_way',[('HOME','Home'),('DRAW','Draw'),('AWAY','Away')]) if '3-way' in n or 'european' in n else ('line_handicap',[('HOME','Home'),('AWAY','Away')])
 if any(k in n for k in ('correct','exact score','exact total','exact number','exact winning round','exact corners')):return 'score',[('SCORE','Score selection')]
 if n.startswith(('player','pitcher','goalie','anytime','first goalscorer','last goalscorer','first try','first touchdown','top ')):return 'participant',[('PARTICIPANT','Participant selection')]
 if three_way and any(k in n for k in ('(1x2)','three-way','match result','first half result','second half result','result after')):
  return 'enumerated',[('HOME','Home'),('DRAW','Draw'),('AWAY','Away')]
 if any(k in n for k in ('winner','moneyline','draw no bet','home or away')):return 'enumerated',[('HOME','Home'),('AWAY','Away')]
 if any(k in n for k in ('first team to score','last team to score','first corner','last corner','most corners','most cards','first team carded')):
  return 'enumerated',[('HOME','Home'),('AWAY','Away'),('NONE','Neither')]
 return 'selection',[('SELECTION','Selection')]


def parameter_for(name,outcome_type,sport):
 if outcome_type in ('line_over_under','line_handicap','line_three_way'):
  if sport=='football' and name=='Total Goals Over/Under':return {'type':'line','values':FOOTBALL_GOAL_LINES,'offered_lines':'discovered'}
  return {'type':'line','values':[],'offered_lines':'discovered'}
 if 'specified' in name.lower():return {'type':'specified','offered_lines':'discovered'}
 return None


def registry_rows():
 for sport,(sport_name,text) in SPORTS.items():
  for name in [x.strip() for x in text.replace('\n','|').split('|') if x.strip()]:
   kind,category,period=classify(name);outcome_type,outcomes=outcomes_for(name,sport)
   yield dict(id=definition_id(sport,name),sport_key=sport,sport_name=sport_name,category_key=category,name=name,kind=kind,period=period,
              outcome_type=outcome_type,parameter=parameter_for(name,outcome_type,sport),where_offered=name in WHERE_OFFERED),outcomes


def seed(db):
 """Idempotent upsert of the registry; cheap no-op when the recorded version is current."""
 state=db.get(m.ProviderSyncState,'markets:catalogue')
 if state and (state.payload or {}).get('version')==REGISTRY_VERSION and db.scalar(select(func.count()).select_from(m.MarketDefinition)):return False
 for i,(key,name) in enumerate(CATEGORIES):
  row=db.get(m.MarketCategory,key)
  if row is None:db.add(m.MarketCategory(key=key,name=name,position=i))
  else:row.name,row.position=name,i
 db.flush()
 defs={d.id:d for d in db.scalars(select(m.MarketDefinition))}
 known=set(db.execute(select(m.MarketOutcome.definition_id,m.MarketOutcome.key)).all())
 for values,outcomes in registry_rows():
  row=defs.get(values['id'])
  if row is None:row=m.MarketDefinition(**values,origin='REGISTERED',registry_version=REGISTRY_VERSION);db.add(row)
  else:
   for k,v in values.items():setattr(row,k,v)
   row.registry_version=REGISTRY_VERSION
  for pos,(key,label) in enumerate(outcomes):
   if (values['id'],key) not in known:db.add(m.MarketOutcome(definition_id=values['id'],key=key,label=label,position=pos))
 db.flush()
 for key,sport,name,line in MAPPINGS:
  if db.scalar(select(m.BookmakerMarketMapping).where(m.BookmakerMarketMapping.source=='*',m.BookmakerMarketMapping.source_market_key==key)) is None:
   db.add(m.BookmakerMarketMapping(source='*',source_market_key=key,definition_id=definition_id(sport,name),line_from_key=line))
 if state is None:
  from app.modules.autonomy.open_intelligence import FD_SOURCE_ID
  source=db.get(m.Source,FD_SOURCE_ID) or db.scalar(select(m.Source).limit(1))
  if source is None:db.flush();return True
  state=m.ProviderSyncState(id='markets:catalogue',source_id=source.id,payload={},failures=0);db.add(state)
 state.payload={'version':REGISTRY_VERSION,'definitions':db.scalar(select(func.count()).select_from(m.MarketDefinition))};state.last_full_at=datetime.now(timezone.utc)
 db.flush()
 return True


# Normalisation of source market keys --------------------------------------------------------------

def normalize(db,bookmaker,market_key,sport='football'):
 """Map a source market key to (definition_id, line). Unknown keys become DISCOVERED definitions (never REGISTERED)."""
 key=str(market_key).strip()
 for source in (bookmaker,'*'):
  exact=db.scalar(select(m.BookmakerMarketMapping).where(m.BookmakerMarketMapping.source==source,m.BookmakerMarketMapping.source_market_key==key,m.BookmakerMarketMapping.line_from_key.is_(False)))
  if exact:return exact.definition_id,''
 match=re.fullmatch(r'([A-Za-z_/]+?)_(-?\d+(?:\.\d+)?)',key)
 if match:
  for source in (bookmaker,'*'):
   mapped=db.scalar(select(m.BookmakerMarketMapping).where(m.BookmakerMarketMapping.source==source,m.BookmakerMarketMapping.source_market_key==match.group(1),m.BookmakerMarketMapping.line_from_key.is_(True)))
   if mapped:return mapped.definition_id,format(float(match.group(2)),'g')
 ident=definition_id(sport,'discovered '+key)
 if db.get(m.MarketDefinition,ident) is None:
  name='Discovered: '+key.replace('_',' ')
  db.add(m.MarketDefinition(id=ident,sport_key=sport,sport_name=sport.replace('_',' ').title(),category_key='sport_specific',name=name,kind='SCHEDULED',
                            period='FULL_TIME',outcome_type='selection',parameter=None,origin='DISCOVERED',where_offered=True,registry_version=None))
  db.add(m.BookmakerMarketMapping(source=bookmaker,source_market_key=key,definition_id=ident,line_from_key=False));db.flush()
 return ident,''


def latest_quotes(db,fixture_id,at):
 """Latest authorized, evidence-backed quote per bookmaker/market/outcome at or before `at`."""
 rows=db.execute(select(m.Odds,m.MarketEvidence,m.Source).join(m.MarketEvidence,m.MarketEvidence.odds_id==m.Odds.id).join(m.Source,m.Source.id==m.MarketEvidence.source_id)
                 .where(m.Odds.fixture_id==fixture_id,m.Odds.observed_at<=at).order_by(m.Odds.observed_at.desc(),m.Odds.id)).all()
 out={}
 for odds,evidence,source in rows:
  if source.enabled and source.permission=='AUTHORIZED':out.setdefault((odds.bookmaker,odds.market_key,odds.outcome_key),(odds,evidence))
 return out


def sync_availability(db,fixture,at):
 """Discover/Acquire: record offered markets per bookmaker; markets missing from a bookmaker's newest batch become REMOVED."""
 sport=sport_key(db.get(m.Sport,db.get(m.Competition,fixture.competition_id).sport_id).name)
 quotes=latest_quotes(db,fixture.id,at)
 newest=defaultdict(lambda:None)
 for (book,_,_),(odds,_) in quotes.items():
  stamp=utc(odds.observed_at);newest[book]=max(filter(None,[newest[book],stamp]))
 seen=set();changes={'new':0,'removed':0,'refreshed':0}
 for (book,market_key,_),(odds,evidence) in quotes.items():
  ident,line=normalize(db,book,market_key,sport);stamp=utc(odds.observed_at)
  key=(book,ident,line)
  if key in seen:continue
  seen.add(key)
  row=db.scalar(select(m.BookmakerMarketAvailability).where(m.BookmakerMarketAvailability.fixture_id==fixture.id,m.BookmakerMarketAvailability.bookmaker==book,
                m.BookmakerMarketAvailability.definition_id==ident,m.BookmakerMarketAvailability.line==line))
  current=stamp>=newest[book]
  if row is None:
   db.add(m.BookmakerMarketAvailability(fixture_id=fixture.id,bookmaker=book,definition_id=ident,line=line,source_market_key=market_key,
          status='AVAILABLE' if current else 'REMOVED',source_id=evidence.source_id,first_seen_at=stamp,last_seen_at=stamp,last_odds_at=stamp));changes['new']+=1
  else:
   status='AVAILABLE' if current else 'REMOVED'
   if row.status!=status:changes['removed' if status=='REMOVED' else 'refreshed']+=1
   row.status=status;row.last_odds_at=stamp;row.last_seen_at=max(utc(row.last_seen_at),stamp) if current else row.last_seen_at
 db.flush()
 return changes


# Model capabilities ------------------------------------------------------------------------------

def sync_capabilities(db):
 """Record what each ACTIVE, approved model can actually price (from its feature/market contract and its forecasts)."""
 from app.modules.prediction.prospective import REQUIRED_APPROVALS
 from app.modules.prediction.service import FEATURE_NAMES
 active=db.scalars(select(m.ModelVersion).where(m.ModelVersion.status=='ACTIVE')).all()
 wanted={}  # (model, definition, outcome, line) -> basis; one row per capability even if several bases apply
 from app.modules.prediction.market_model import model_type,MODEL_TYPE
 for model in active:
  v=model.validation if isinstance(model.validation,dict) else {}
  if any(v.get(k) is not True for k in REQUIRED_APPROVALS):continue
  sport=sport_key(db.get(m.Sport,model.sport_id).name)
  if model_type(model)==MODEL_TYPE:
   # Only outcomes that individually passed out-of-sample validation become capabilities.
   for key,result in (v.get('markets') or {}).items():
    if not result.get('approved'):continue
    market,outcome=key.split('|',1);ident,line=normalize(db,'*',market,sport)
    wanted.setdefault((model.id,ident,outcome,line),f"Poisson market model; holdout Brier {result['holdout']['brier']} vs base rate {result['baseline']['brier']}, calibration error {result['calibration_error']}")
  elif list(v.get('feature_names') or [])==list(FEATURE_NAMES):
   wanted.setdefault((model.id,definition_id(sport,'Full Time Result (1X2)'),'HOME',''),'Binary home-win contract (prospective 1X2/HOME inference)')
  for market,outcome in db.execute(select(m.Prediction.market_key,m.Prediction.outcome_key).where(m.Prediction.model_id==model.id).distinct()).all():
   ident,line=normalize(db,'*',market,sport)
   wanted.setdefault((model.id,ident,outcome,line),'Published forecasts for this market/outcome')
 existing={(c.model_id,c.definition_id,c.outcome_key,c.line):c for c in db.scalars(select(m.MarketModelCapability))}
 for key,cap in existing.items():
  if key not in wanted:db.delete(cap)
 for (model_id,ident,outcome,line),basis in wanted.items():
  if (model_id,ident,outcome,line) not in existing and db.get(m.MarketDefinition,ident):
   db.add(m.MarketModelCapability(model_id=model_id,definition_id=ident,outcome_key=outcome,line=line,basis=basis))
 db.flush()
 return {(c.definition_id,c.outcome_key,c.line) for c in db.scalars(select(m.MarketModelCapability))}


# Scanning ----------------------------------------------------------------------------------------

def scan(db,fixture_id,at=None,trigger='PIPELINE_EVALUATE',force=False):
 """Evaluate every observed outcome for a fixture and persist ranked, gated results."""
 from app.modules.market_scanner.service import forecasts,evaluate,rank_key
 at=at or datetime.now(timezone.utc)
 fixture=db.get(m.Fixture,fixture_id)
 if fixture is None:raise LookupError('Fixture not found')
 seed(db)
 watermark=db.scalar(select(func.max(m.Odds.observed_at)).where(m.Odds.fixture_id==fixture_id,m.Odds.observed_at<=at))
 last=db.scalar(select(m.MarketScanRun).where(m.MarketScanRun.fixture_id==fixture_id).order_by(m.MarketScanRun.started_at.desc()).limit(1))
 supported=sync_capabilities(db)
 # Rescan when odds OR model capabilities change (e.g. a newly validated market model), otherwise throttle.
 import hashlib
 signature=f"{len(supported)}:{hashlib.sha1(repr(sorted(supported)).encode()).hexdigest()[:12]}"
 if not force and last and utc(last.started_at)>at-SCAN_MIN_INTERVAL and last.odds_watermark==watermark and (last.summary or {}).get('capability_signature')==signature:return last
 changes=sync_availability(db,fixture,at)
 cutoff=min(at,utc(fixture.kickoff_at))
 predicted=forecasts(db,fixture_id,cutoff)
 run=m.MarketScanRun(fixture_id=fixture_id,trigger=trigger,status='RUNNING',started_at=at,odds_watermark=watermark,summary={});db.add(run);db.flush()
 sport=sport_key(db.get(m.Sport,db.get(m.Competition,fixture.competition_id).sport_id).name)
 quotes=latest_quotes(db,fixture_id,at)
 books=defaultdict(dict)
 for (book,market,outcome),(odds,_) in quotes.items():books[(book,market)][outcome]=float(odds.decimal_odds)
 rows=[]
 for (book,market,outcome),(odds,evidence) in quotes.items():
  ident,line=normalize(db,book,market,sport)
  age=(at-utc(odds.observed_at)).total_seconds()
  statuses=['AVAILABLE','FRESH' if age<=FRESH.total_seconds() else 'STALE']
  prices=books[(book,market)];overround=sum(1/p for p in prices.values()) if len(prices)>1 else None
  implied=1/float(odds.decimal_odds)
  metrics={'implied_probability':round(implied*100,2),'fair_probability':round(implied/overround*100,2) if overround else None,
           'bookmaker_margin':round((overround-1)*100,2) if overround else None,'odds_age_minutes':round(age/60,1)}
  pair=predicted.get((market,outcome))
  if (ident,outcome,line) not in supported or pair is None:
   statuses.append('UNSUPPORTED')
   reason='NO_APPROVED_MODEL_FOR_MARKET' if (ident,outcome,line) not in supported else 'NO_FORECAST_BEFORE_CUTOFF'
   rows.append(dict(definition_id=ident,bookmaker=book,line=line,outcome_key=outcome,odds_id=odds.id,prediction_id=None,decimal_odds=float(odds.decimal_odds),
                    odds_observed_at=odds.observed_at,statuses=statuses,metrics=metrics,decision='UNSUPPORTED',reasons=[reason],sort=(2,0,0)))
   continue
  prediction,model=pair
  verdict=evaluate(db,prediction,model,odds,at)
  statuses+=['MODEL_SUPPORTED','EVALUATED']+(['QUALIFIED'] if verdict['decision']=='QUALIFIED' else [])
  metrics.update(probability=verdict['probability'],lower=verdict['lower'],upper=verdict['upper'],expected_value=verdict['ev'],conservative_ev=verdict['conservative_ev'],model=verdict['model'])
  rows.append(dict(definition_id=ident,bookmaker=book,line=line,outcome_key=outcome,odds_id=odds.id,prediction_id=prediction.id,decimal_odds=float(odds.decimal_odds),
                   odds_observed_at=odds.observed_at,statuses=statuses,metrics=metrics,decision=verdict['decision'],reasons=verdict['reasons'],
                   sort=(0 if verdict['decision']=='QUALIFIED' else 1,)+rank_key(verdict)[2:]))
 rows.sort(key=lambda r:r['sort'])
 qualified_groups=defaultdict(int)
 for r in rows:
  if r['decision']=='QUALIFIED':qualified_groups[db.get(m.MarketDefinition,r['definition_id']).category_key]+=1
 for rank,r in enumerate(rows,1):
  category=db.get(m.MarketDefinition,r['definition_id']).category_key
  r.pop('sort')
  # Outcomes of the same fixture are correlated; flag when more than one qualifies in the same family.
  group=f'{fixture_id}:{category}' if r['decision']=='QUALIFIED' and (qualified_groups[category]>1 or sum(qualified_groups.values())>1) else None
  db.add(m.MarketScanResult(scan_id=run.id,fixture_id=fixture_id,rank=rank,correlation_group=group,**r))
 summary={'outcomes':len(rows),'evaluated':sum(r['decision'] not in ('UNSUPPORTED',) for r in rows),'qualified':sum(r['decision']=='QUALIFIED' for r in rows),
          'unsupported':sum(r['decision']=='UNSUPPORTED' for r in rows),'fresh':sum('FRESH' in r['statuses'] for r in rows),'availability_changes':changes,
          'capability_signature':signature,'model_supported_outcomes':len(supported)}
 run.status='COMPLETED';run.completed_at=datetime.now(timezone.utc);run.summary=summary
 db.flush()
 return run


# Read models ------------------------------------------------------------------------------------

def definition_dict(d,outcomes):
 return {'id':d.id,'sport':d.sport_name,'sport_key':d.sport_key,'category':d.category_key,'name':d.name,'kind':d.kind,'period':d.period,
         'outcome_type':d.outcome_type,'parameter':d.parameter,'origin':d.origin,'where_offered':d.where_offered,'outcomes':outcomes}


def outcomes_by_definition(db,ids=None):
 query=select(m.MarketOutcome).order_by(m.MarketOutcome.position)
 if ids is not None:query=query.where(m.MarketOutcome.definition_id.in_(list(ids)))
 out=defaultdict(list)
 for o in db.scalars(query):out[o.definition_id].append({'key':o.key,'label':o.label})
 return out


def catalogue(db,sport=None):
 seed(db)
 query=select(m.MarketDefinition).order_by(m.MarketDefinition.sport_key,m.MarketDefinition.category_key,m.MarketDefinition.name)
 if sport:query=query.where(m.MarketDefinition.sport_key==sport_key(sport))
 defs=db.scalars(query).all();outs=outcomes_by_definition(db,{d.id for d in defs})
 sports=defaultdict(int)
 for d in db.scalars(select(m.MarketDefinition)):sports[(d.sport_key,d.sport_name)]+=1
 return {'registry_version':REGISTRY_VERSION,'notice':'Registered market definitions only - not a list of markets currently offered by any bookmaker.',
         'sports':[{'key':k,'name':n,'definitions':c} for (k,n),c in sorted(sports.items())]+[{'key':slug(n),'name':n,'definitions':0,'discovery_only':True} for n in DISCOVERY_ONLY],
         'definitions':[definition_dict(d,outs[d.id]) for d in defs]}


def categories(db,sport=None):
 seed(db)
 counts=defaultdict(int)
 query=select(m.MarketDefinition.category_key,func.count()).group_by(m.MarketDefinition.category_key)
 if sport:query=query.where(m.MarketDefinition.sport_key==sport_key(sport))
 for key,n in db.execute(query):counts[key]=n
 return [{'key':c.key,'name':c.name,'registered':counts.get(c.key,0)} for c in db.scalars(select(m.MarketCategory).order_by(m.MarketCategory.position))]


def latest_scan(db,fixture_id):
 return db.scalar(select(m.MarketScanRun).where(m.MarketScanRun.fixture_id==fixture_id,m.MarketScanRun.status=='COMPLETED').order_by(m.MarketScanRun.started_at.desc()).limit(1))


def result_dict(r,d):
 return {'definition_id':r.definition_id,'market':d.name if d else r.definition_id,'category':d.category_key if d else None,'bookmaker':r.bookmaker,'line':r.line,
         'outcome':r.outcome_key,'decimal_odds':float(r.decimal_odds) if r.decimal_odds is not None else None,'odds_observed_at':r.odds_observed_at,
         'statuses':r.statuses,'metrics':r.metrics,'decision':r.decision,'reasons':r.reasons,'rank':r.rank,'correlation_group':r.correlation_group}


def fixture_view(db,fixture_id,at=None):
 """Registered catalogue for the fixture's sport merged with observed availability and the latest scan."""
 at=at or datetime.now(timezone.utc)
 fixture=db.get(m.Fixture,fixture_id)
 if fixture is None:raise LookupError('Fixture not found')
 seed(db)
 sport=sport_key(db.get(m.Sport,db.get(m.Competition,fixture.competition_id).sport_id).name)
 defs={d.id:d for d in db.scalars(select(m.MarketDefinition).where(m.MarketDefinition.sport_key==sport))}
 avail=db.scalars(select(m.BookmakerMarketAvailability).where(m.BookmakerMarketAvailability.fixture_id==fixture_id)).all()
 for a in avail:
  if a.definition_id not in defs and db.get(m.MarketDefinition,a.definition_id):defs[a.definition_id]=db.get(m.MarketDefinition,a.definition_id)
 outs=outcomes_by_definition(db,set(defs))
 run=latest_scan(db,fixture_id)
 results=db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id).order_by(m.MarketScanResult.rank)).all() if run else []
 by_def=defaultdict(list)
 for r in results:by_def[r.definition_id].append(r)
 caps={(c.definition_id) for c in db.scalars(select(m.MarketModelCapability))}
 research=db.scalar(select(m.Research.status).where(m.Research.fixture_id==fixture_id).order_by(m.Research.version.desc()).limit(1))
 # Model forecasts exist independently of prices: show them on registered markets and rank suitability for analysis.
 from app.modules.market_scanner.service import forecasts,interval
 cutoff=min(at,utc(fixture.kickoff_at));modelled=defaultdict(list);ranking=[]
 for (market_key,outcome),(prediction,model) in forecasts(db,fixture_id,cutoff).items():
  ident,line=normalize(db,'*',market_key,sport);lower,upper=interval(prediction.details);d=prediction.details if isinstance(prediction.details,dict) else {}
  entry={'definition_id':ident,'market':defs[ident].name if ident in defs else ident,'outcome':outcome,'line':line,'probability':round(float(prediction.probability)*100,1),
         'lower':round(lower*100,1) if lower is not None else None,'upper':round(upper*100,1) if upper is not None else None,
         'skill':round(d['skill']*100,1) if isinstance(d.get('skill'),(int,float)) else None,'model':model.name+' '+model.version}
  modelled[ident].append(entry);ranking.append(entry)
 # Per market (and line): the market's validated skill decides its rank; its most likely outcome is shown.
 best={}
 for e in ranking:
  # Exact-score outcomes are separate events: each keeps its own skill instead of inheriting the market's.
  key=(e['definition_id'],e['line'],e['outcome'] if defs.get(e['definition_id']) is not None and defs[e['definition_id']].outcome_type=='score' else '');cur=best.get(key)
  skill=max(e['skill'] if e['skill'] is not None else -100,cur[0] if cur else -100)
  pick=e if cur is None or e['probability']>cur[1]['probability'] else cur[1]
  best[key]=(skill,pick)
 ranking=[{**pick,'market_skill':skill} for skill,pick in sorted(best.values(),key=lambda x:(-x[0],-(x[1]['lower'] or 0)))]
 markets=[]
 for ident,d in defs.items():
  offers=[a for a in avail if a.definition_id==ident]
  live=[a for a in offers if a.status=='AVAILABLE']
  rs=by_def.get(ident,[])
  latest=max((utc(a.last_odds_at) for a in live if a.last_odds_at),default=None)
  status=['DISCOVERED'] if d.origin=='DISCOVERED' else ['REGISTERED']
  if live:status.append('AVAILABLE');status.append('FRESH' if latest and at-latest<=FRESH else 'STALE')
  elif offers:status.append('UNAVAILABLE')
  if ident in caps:status.append('MODEL_SUPPORTED')
  if any(r.decision not in ('UNSUPPORTED',) for r in rs):status.append('EVALUATED')
  if any(r.decision=='QUALIFIED' for r in rs):status.append('QUALIFIED')
  if live and not any(r.decision not in ('UNSUPPORTED',) for r in rs):status.append('UNSUPPORTED')
  best=next((r for r in rs if r.decision!='UNSUPPORTED'),None)
  top=max(modelled.get(ident,[]),key=lambda e:(e['skill'] or -100,e['probability']),default=None)
  markets.append({**definition_dict(d,outs[ident]),'statuses':status,'offered':bool(live),'model_outcomes':modelled.get(ident,[]),
                  'top_outcome':top,
                  'bookmakers':sorted({a.bookmaker for a in live}),'lines':sorted({a.line for a in live if a.line},key=lambda x:float(x)),
                  'odds':[{'bookmaker':r.bookmaker,'line':r.line,'outcome':r.outcome_key,'decimal_odds':float(r.decimal_odds) if r.decimal_odds is not None else None} for r in rs][:24],
                  'odds_observed_at':latest,'model_supported':ident in caps,'research':research or 'NOT_STARTED',
                  'probability':best.metrics.get('probability') if best else (top['probability'] if top else None),'decision':best.decision if best else ('UNSUPPORTED' if live else None)})
 order={key:i for i,(key,_) in enumerate(CATEGORIES)}
 markets.sort(key=lambda x:(not x['offered'],order.get(x['category'],99),x['name']))
 return {'fixture_id':fixture_id,'sport':sport,'markets':markets,'coverage':coverage(db,fixture_id,markets,run),
         'analysis_ranking':ranking[:15],
         'ranking_basis':'Validated skill over the base rate on unseen matches (Brier skill score), then probability lower bound. Without prices this is suitability for analysis, not a betting qualification.',
         'best_fit':[result_dict(r,defs.get(r.definition_id)) for r in results if r.decision!='UNSUPPORTED'][:10],
         'scan':scan_dict(run) if run else None,'categories':categories(db,sport),
         'notice':'REGISTERED means the platform understands the market type; only AVAILABLE markets were observed in source-backed odds for this fixture. No market is presented as offered by SportyBet.'}


def coverage(db,fixture_id,markets,run):
 reasons=defaultdict(int)
 if run:
  for r in db.scalars(select(m.MarketScanResult).where(m.MarketScanResult.scan_id==run.id)):
   for reason in r.reasons or []:reasons[reason]+=1
 last_sync=db.scalar(select(func.max(m.BookmakerMarketAvailability.last_seen_at)).where(m.BookmakerMarketAvailability.fixture_id==fixture_id))
 offered=[x for x in markets if x['offered']]
 if not offered:reasons['NO_SOURCE_BACKED_ODDS_FOR_FIXTURE']+=1
 return {'registered':len([x for x in markets if x['origin']=='REGISTERED']),'discovered':len([x for x in markets if x['origin']=='DISCOVERED']),
         'offered':len(offered),'fresh':sum('FRESH' in x['statuses'] for x in markets),'stale':sum('STALE' in x['statuses'] for x in markets),
         'model_supported':sum(x['model_supported'] for x in markets),'evaluated':sum('EVALUATED' in x['statuses'] for x in markets),
         'qualified':sum('QUALIFIED' in x['statuses'] for x in markets),'unsupported':sum('UNSUPPORTED' in x['statuses'] for x in markets),
         'unavailable':sum('UNAVAILABLE' in x['statuses'] for x in markets),'missing_data_reasons':dict(reasons),'last_sync':last_sync}


def scan_dict(run):
 return {'id':run.id,'fixture_id':run.fixture_id,'trigger':run.trigger,'status':run.status,'started_at':run.started_at,'completed_at':run.completed_at,
         'odds_watermark':run.odds_watermark,'summary':run.summary}
