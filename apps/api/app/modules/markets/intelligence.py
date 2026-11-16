"""Market Intelligence read models (adapted from the cacsms-market-intelligence patch onto canonical records).

Every number is a count or comparison over stored rows. Statuses distinguish REGISTERED definitions,
OBSERVED closing-price archives and AVAILABLE upcoming prices; nothing is presented as offered by SportyBet.
"""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func,distinct
from app.db import models as m
from app.modules.markets import catalogue as cat
from app.modules.markets.catalogue_data import CATEGORIES
from app.modules.research.league import utc

UNAVAILABLE_SOURCES=[{'source':'SportyBet','status':'NO_PERMITTED_FEED','permission':'NOT_AUTHORIZED','restriction':'No authorized SportyBet data feed is configured; nothing is collected from SportyBet.'}]


def _now():return datetime.now(timezone.utc)


def normalizer(db):
 """Per-request memo of source-key normalisation (avoids hundreds of identical mapping lookups)."""
 memo={}
 def norm(key):
  if key not in memo:memo[key]=cat.normalize(db,'*',key,'football')
  return memo[key]
 return norm


def market_groups(db,norm=None):
 """Observed market keys -> canonical definitions with observation counts (football)."""
 norm=norm or normalizer(db)
 rows=db.execute(select(m.Odds.market_key,func.count(),func.count(distinct(m.Odds.fixture_id)),func.max(m.Odds.observed_at)).group_by(m.Odds.market_key)).all()
 out=defaultdict(lambda:{'observations':0,'fixtures':0,'latest':None,'lines':set(),'keys':set()})
 for key,n,fixtures,latest in rows:
  ident,line=norm(key)
  g=out[ident];g['observations']+=n;g['fixtures']=max(g['fixtures'],fixtures);g['keys'].add(key)
  if line:g['lines'].add(line)
  g['latest']=max(filter(None,[g['latest'],utc(latest) if latest else None]),default=None)
 return out


def upcoming_offered(db,at):
 return {a.definition_id for a in db.scalars(select(m.BookmakerMarketAvailability).join(m.Fixture,m.Fixture.id==m.BookmakerMarketAvailability.fixture_id)
         .where(m.BookmakerMarketAvailability.status=='AVAILABLE',m.Fixture.kickoff_at>at))}


def capability_keys(db):
 return {(c.definition_id,c.outcome_key,c.line) for c in db.scalars(select(m.MarketModelCapability))}


def overview(db,at=None):
 at=at or _now();cat.seed(db)
 prices=db.scalar(select(func.count()).select_from(m.Odds)) or 0
 priced=db.scalar(select(func.count(distinct(m.Odds.fixture_id)))) or 0
 norm=normalizer(db);groups=market_groups(db,norm)
 observed_outcomes=db.execute(select(m.Odds.market_key,m.Odds.outcome_key).distinct()).all()
 caps=capability_keys(db);covered=0
 for key,outcome in observed_outcomes:
  ident,line=norm(key)
  covered+=(ident,outcome,line) in caps
 fresh=db.scalar(select(func.count()).select_from(m.Odds).join(m.Fixture,m.Fixture.id==m.Odds.fixture_id).where(m.Fixture.kickoff_at>at,m.Odds.observed_at>=at-cat.FRESH)) or 0
 qualified=db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision=='QUALIFIED')) or 0
 from app.modules.autonomy.service import runtime_status
 rt=runtime_status(db)
 return {'runtime':{'worker_online':rt.get('worker_online'),'next_run_at':rt.get('next_run_at'),'status':rt.get('status')},'price_observations':prices,'fixtures_priced':priced,'markets_represented':len(groups),'registered_definitions':db.scalar(select(func.count()).select_from(m.MarketDefinition)) or 0,
         'model_coverage':round(covered*100/len(observed_outcomes),1) if observed_outcomes else None,'observed_outcomes':len(observed_outcomes),'model_covered_outcomes':covered,
         'fresh_prices':fresh,'qualified':qualified,'pipeline':pipeline(db,at,groups,fresh,qualified),'benchmark':benchmark_cached(db),
         'notice':'Archive prices are historical CLOSING odds (Football-Data.co.uk), not executable prices. No market is presented as offered by SportyBet.'}


def pipeline(db,at,groups,fresh,qualified):
 from app.modules.acquisition.source_policy import registry
 sources=[r for r in registry(db,at) if r['status']=='ACTIVE']
 archive=db.scalars(select(m.ProviderSyncState).where(m.ProviderSyncState.id.like('markets:archive:%'))).all()
 last_archive=max((utc(s.last_full_at) for s in archive if s.last_full_at),default=None)
 unmapped=[g for ident,g in groups.items() if ident.startswith('football.discovered_')]
 rejected=sum(((s.payload or {}).get('last_report') or {}).get('rejected_prices',0) for s in archive)
 from app.modules.prediction.market_model import active_model
 sport=db.scalar(select(m.Sport).where(m.Sport.name=='Football'))
 model=active_model(db,sport.id) if sport else None
 step=lambda key,name,status,detail:{'key':key,'name':name,'status':status,'detail':detail}
 return [step('discover','Discover','DONE' if sources else 'WAITING',f'{len(sources)} authorized sources'),
         step('collect','Collect','DONE' if last_archive else 'WAITING',f'{len(archive)} archive files; last {last_archive.isoformat() if last_archive else "never"}'),
         step('map','Map','DONE' if groups and not unmapped else 'PARTIAL' if groups else 'WAITING',f'{len(groups)-len(unmapped)} mapped, {len(unmapped)} discovered-only'),
         step('validate','Validate','DONE' if archive else 'WAITING',f'{rejected} invalid prices rejected'),
         step('analyse','Analyse','DONE' if model else 'WAITING','Market model active' if model else 'No validated market model'),
         step('qualify','Qualify','DONE' if qualified else 'WAITING',f'{qualified} qualified' if qualified else ('No fresh executable prices' if not fresh else 'No outcome passed every gate'))]


def categories(db,at=None):
 at=at or _now();groups=market_groups(db);offered=upcoming_offered(db,at)
 defs={d.id:d for d in db.scalars(select(m.MarketDefinition))}
 out=[]
 for key,name in CATEGORIES:
  ids=[i for i,d in defs.items() if d.category_key==key]
  out.append({'key':key,'name':name,'registered':len(ids),'observed':sum(i in groups for i in ids),'available':sum(i in offered for i in ids)})
 return out


def markets(db,category=None,search=None,sport=None,limit=10,offset=0,at=None):
 at=at or _now();cat.seed(db)
 groups=market_groups(db);offered=upcoming_offered(db,at);caps={c[0] for c in capability_keys(db)}
 query=select(m.MarketDefinition)
 if sport:query=query.where(m.MarketDefinition.sport_key==cat.sport_key(sport))
 if category:query=query.where(m.MarketDefinition.category_key==category)
 if search:query=query.where(func.lower(m.MarketDefinition.name).contains(search.lower()))
 defs=db.scalars(query).all();outs=cat.outcomes_by_definition(db,{d.id for d in defs})
 order={k:i for i,(k,_) in enumerate(CATEGORIES)}
 def status(d):return 'AVAILABLE' if d.id in offered else 'OBSERVED' if d.id in groups else 'DISCOVERED' if d.origin=='DISCOVERED' else 'REGISTERED'
 rank={'AVAILABLE':0,'OBSERVED':1,'DISCOVERED':2,'REGISTERED':3}
 defs.sort(key=lambda d:(rank[status(d)],-groups.get(d.id,{}).get('observations',0),order.get(d.category_key,99),d.sport_key,d.name))
 page=defs[offset:offset+limit];rows=[]
 for d in page:
  g=groups.get(d.id);sample=None
  if g:
   # Latest observed prices for this market on its most recently priced fixture (best price per outcome across bookmakers).
   latest=db.execute(select(m.Odds.fixture_id,func.max(m.Odds.observed_at)).where(m.Odds.market_key.in_(g['keys'])).group_by(m.Odds.fixture_id)
                     .order_by(func.max(m.Odds.observed_at).desc()).limit(1)).first()
   if latest:
    fx=db.get(m.Fixture,latest[0])
    quotes=db.execute(select(m.Odds.market_key,m.Odds.outcome_key,func.max(m.Odds.decimal_odds)).where(m.Odds.fixture_id==fx.id,m.Odds.market_key.in_(g['keys']))
                      .group_by(m.Odds.market_key,m.Odds.outcome_key)).all()
    sample={'fixture':f'{fx.home_name} vs {fx.away_name}','kickoff_at':fx.kickoff_at,'observed_at':latest[1],
            'best':[{'market_key':k,'outcome':o,'decimal_odds':float(p)} for k,o,p in sorted(quotes)][:6]}
  rows.append({**cat.definition_dict(d,outs[d.id]),'status':status(d),'observations':g['observations'] if g else 0,'fixtures':g['fixtures'] if g else 0,
               'lines':sorted(g['lines'],key=float) if g else [],'latest_observed_at':g['latest'] if g else None,'sample':sample,'model_supported':d.id in caps})
 return {'total':len(defs),'limit':limit,'offset':offset,'markets':rows}


def sports_coverage(db):
 rows=db.execute(select(m.Competition.id,m.Competition.name,m.Competition.country,func.count(distinct(m.Fixture.id))).join(m.Fixture,m.Fixture.competition_id==m.Competition.id)
                 .group_by(m.Competition.id,m.Competition.name,m.Competition.country)).all()
 out=[]
 for comp_id,name,country,fixtures in rows:
  priced,prices,latest=db.execute(select(func.count(distinct(m.Odds.fixture_id)),func.count(m.Odds.id),func.max(m.Odds.observed_at)).join(m.Fixture,m.Fixture.id==m.Odds.fixture_id)
                                  .where(m.Fixture.competition_id==comp_id)).one()
  verified=db.scalar(select(func.count(distinct(m.Result.fixture_id))).join(m.Fixture,m.Fixture.id==m.Result.fixture_id).where(m.Fixture.competition_id==comp_id)) or 0
  seasons=db.scalar(select(func.count()).select_from(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp_id)) or 0
  out.append({'sport':'Football','country':country,'competition':name,'seasons':seasons,'fixtures':fixtures,'fixtures_priced':priced or 0,'price_observations':prices or 0,
              'verified_results':verified,'latest_price_at':latest,'research_ready':verified>0})
 return sorted(out,key=lambda r:(-r['fixtures_priced'],r['country']))


def sync_history(db,limit=40):
 events=db.scalars(select(m.AuditEvent).where(m.AuditEvent.action.in_(['markets.archive_import','source.open_data_enabled','source.prohibited','model.market_validation','model.promoted']))
                   .order_by(m.AuditEvent.created_at.desc()).limit(limit)).all()
 return [{'at':e.created_at,'actor':e.actor,'action':e.action,'detail':{k:v for k,v in (e.payload or {}).items() if k in ('division','season','matches','prices','rejected_prices','skipped_no_time','skipped_unmatched','status','approved_outcomes','provider','domain','reason')}} for e in events]


def sources(db,at=None):
 from app.modules.acquisition.source_policy import registry
 return registry(db,at)+UNAVAILABLE_SOURCES


# Model vs closing market benchmark -----------------------------------------------------------------

def benchmark(db,at=None):
 """On the market model's own holdout (later 30%), compare its 1X2 Brier with the margin-free closing market average."""
 from app.modules.prediction import market_model as mm
 at=at or _now()
 sport=db.scalar(select(m.Sport).where(m.Sport.name=='Football'))
 model=mm.active_model(db,sport.id) if sport else None
 comp=db.scalar(select(m.Competition).where(m.Competition.name=='Bundesliga',m.Competition.country=='Germany'))
 if model is None or comp is None:return {'status':'NO_MODEL'}
 rows=mm.history(db,comp.id,at);split=int(len(rows)*.7);test=rows[split:]
 params=(model.validation or {}).get('parameters') or {}
 pairs=[]
 for f,hg,ag,fixture_id in test:
  quotes={o:float(p) for o,p in db.execute(select(m.Odds.outcome_key,m.Odds.decimal_odds).where(m.Odds.fixture_id==fixture_id,m.Odds.market_key=='1X2',
          m.Odds.bookmaker=='Market average (closing)')).all()}
  if set(quotes)!={'HOME','DRAW','AWAY'}:continue
  over=sum(1/v for v in quotes.values());market={k:(1/v)/over for k,v in quotes.items()}
  probs=mm.probabilities(f,params);actual='HOME' if hg>ag else 'AWAY' if hg<ag else 'DRAW'
  pairs.append(({k:probs[('1X2',k)] for k in market},market,actual,over))
 if len(pairs)<50:return {'status':'INSUFFICIENT_PRICED_HOLDOUT','priced_matches':len(pairs)}
 brier=lambda dist,actual:sum((dist[k]-(1 if k==actual else 0))**2 for k in dist)
 model_b=sum(brier(p,a) for p,_,a,_ in pairs)/len(pairs);market_b=sum(brier(q,a) for _,q,a,_ in pairs)/len(pairs)
 return {'status':'COMPUTED','matches':len(pairs),'model_brier':round(model_b,4),'market_brier':round(market_b,4),'average_margin':round((sum(o for *_,o in pairs)/len(pairs)-1)*100,2),
         'verdict':'MODEL_BETTER_THAN_CLOSING_MARKET' if model_b<market_b else 'CLOSING_MARKET_BETTER_THAN_MODEL',
         'basis':'Multi-class Brier on the market model holdout (Bundesliga), closing market average with margin removed'}


def benchmark_cached(db):
 state=db.get(m.ProviderSyncState,'markets:benchmark')
 return (state.payload or {}) if state else {'status':'NOT_COMPUTED'}


def refresh_benchmark(factory,at=None):
 at=at or _now()
 with factory.begin() as db:
  state=db.get(m.ProviderSyncState,'markets:benchmark')
  if state and state.next_check_at and utc(state.next_check_at)>at:return {'status':'NOT_DUE'}
  result=benchmark(db,at)
  from app.modules.autonomy.open_intelligence import cached
  state=cached(db,'markets:benchmark',None);state.payload={**result,'computed_at':at.isoformat()};state.last_full_at=at;state.next_check_at=at+timedelta(hours=6)
 return result
