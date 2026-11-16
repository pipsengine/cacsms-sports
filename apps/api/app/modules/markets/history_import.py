"""Closing-odds archive from Football-Data.co.uk season CSVs (adapted from the cacsms-market-intelligence patch).

Differences from the patch, by design:
* canonical tables (sports.competitions, fixtures.fixtures, markets.odds_snapshots + odds_evidence), no second database;
* CLOSING prices only, stamped at kickoff (the time they are, by definition, valid for). The patch stamped opening
  prices at midnight of match day, a time Football-Data does not publish;
* one immutable file-level observation per downloaded CSV, referenced by every imported price;
* historical archive writes do not emit per-record pipeline events (kicked-off fixtures cannot affect open runs).
Football-Data is the only source for leagues other than the Bundesliga, so those fixtures are price archives only:
no results are verified from them (verification needs a second independent source).
"""
import hashlib,os,uuid
from datetime import datetime,timedelta,timezone,date
from zoneinfo import ZoneInfo
from sqlalchemy import select,insert,func
from app.db import models as m
from app.modules.research.league import utc
from app.modules.autonomy import open_intelligence as oi

DIVISIONS={'E0':('England','Premier League'),'D1':('Germany','Bundesliga'),'SP1':('Spain','La Liga'),'I1':('Italy','Serie A'),
           'F1':('France','Ligue 1'),'N1':('Netherlands','Eredivisie'),'P1':('Portugal','Primeira Liga')}
# Closing-price column prefixes -> bookmaker label (1X2 prefix, totals/AH prefix). 'Avg' is the provider's market average.
CLOSING=[('B365','B365','Bet365'),('PS','P','Pinnacle'),('BFE','BFE','Betfair Exchange'),('Avg','Avg','Market average (closing)')]
LONDON=ZoneInfo('Europe/London')
FILES_PER_RUN=6


def divisions():
 raw=os.getenv('SPORTS_MARKET_DIVISIONS','E0,D1,SP1,I1,F1,N1,P1')
 return [d.strip() for d in raw.split(',') if d.strip() in DIVISIONS]


def kickoff(row):
 raw=(row.get('Date') or '').strip()
 try:day=datetime.strptime(raw,'%d/%m/%Y') if len(raw)==10 else datetime.strptime(raw,'%d/%m/%y')
 except ValueError:return None
 try:hh,mm=[int(x) for x in (row.get('Time') or '').strip().split(':')[:2]]
 except ValueError:return None  # without a kickoff time the closing timestamp is unknown -> skip
 return day.replace(hour=hh,minute=mm,tzinfo=LONDON).astimezone(timezone.utc)


def closing_prices(row):
 """(bookmaker, market_key, outcome_key, price) for every closing price present; invalid prices are counted, not stored."""
 out=[];rejected=0
 def price(col):
  nonlocal rejected
  v=(row.get(col) or '').strip()
  if not v:return None
  p=oi._price(v)
  if p is None:rejected+=1
  return p
 for pre1,pre2,book in CLOSING:
  trio=[price(f'{pre1}C{s}') for s in ('H','D','A')]
  if all(trio):out+=[(book,'1X2',k,v) for k,v in zip(('HOME','DRAW','AWAY'),trio)]
  ou=[price(f'{pre2}C{s}') for s in ('>2.5','<2.5')]
  if all(ou):out+=[(book,'OU_2.5',k,v) for k,v in zip(('OVER','UNDER'),ou)]
  line=(row.get('AHCh') or '').strip();ah=[price(f'{pre2}CAH{s}') for s in ('H','A')]
  if line and all(ah):
   try:key='AH_'+format(float(line),'g')
   except ValueError:key=None
   if key:out+=[(book,key,k,v) for k,v in zip(('HOME','AWAY'),ah)]
 return out,rejected


def competition(db,division):
 country,name=DIVISIONS[division]
 sport=db.scalar(select(m.Sport).where(m.Sport.name=='Football'))
 if sport is None:sport=m.Sport(name='Football');db.add(sport);db.flush()
 comp=db.scalar(select(m.Competition).where(m.Competition.sport_id==sport.id,m.Competition.name==name,m.Competition.country==country))
 if comp is None:comp=m.Competition(sport_id=sport.id,name=name,country=country);db.add(comp);db.flush()
 return comp


def fixture_for(db,comp,division,season,home,away,ko,url):
 found=db.scalar(select(m.Fixture).where(m.Fixture.competition_id==comp.id,m.Fixture.home_name==home,m.Fixture.away_name==away,
                                         m.Fixture.kickoff_at>=ko-timedelta(days=1),m.Fixture.kickoff_at<=ko+timedelta(days=1)))
 if found or division=='D1':return found  # Bundesliga fixtures come from OpenLigaDB; never duplicate them from one source
 from app.modules.ingestion.service import ingest_fixture
 result=ingest_fixture(db,oi.FD_SOURCE,'Football',comp.name,home,away,ko,url,{'source_reference':f'football-data:{division}:{season}:{home}-{away}',
        'verification':'SINGLE_SOURCE_PRICE_ARCHIVE','note':'Fixture identity from one provider; results are not verified'})
 fixture=db.get(m.Fixture,result['fixture_id']);fixture.competition_id=comp.id
 label=oi.season_label(season)
 registered=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp.id,m.CompetitionSeason.label==label))
 if registered is None:
  registered=m.CompetitionSeason(competition_id=comp.id,label=label,start_date=date(season,7,1),end_date=date(season+1,6,30),is_current=False);db.add(registered);db.flush()
 fixture.season_id=fixture.season_id or registered.id
 if fixture.status=='SCHEDULED' and ko<datetime.now(timezone.utc)-timedelta(hours=3):fixture.status='COMPLETED_UNVERIFIED'
 return fixture


def import_file(db,division,season,rows,url,at):
 """Import one season CSV; previously imported matches (tracked per file) are skipped, so re-runs are idempotent."""
 from app.modules.pipeline.events import RUNNER_FLAG
 db.info[RUNNER_FLAG]=True  # archive rows for kicked-off fixtures must not flood the pipeline event queue
 try:
  key=f'markets:archive:{division}:{season}'
  state=oi.cached(db,key,oi.FD_SOURCE_ID);done=set((state.payload or {}).get('matches') or [])
  comp=competition(db,division)
  digest=hashlib.sha256(repr(sorted((r.get('Date'),r.get('HomeTeam'),r.get('AwayTeam')) for r in rows)).encode()).hexdigest()
  obs=db.scalar(select(m.Observation).where(m.Observation.source_id==oi.FD_SOURCE_ID,m.Observation.content_hash==digest))
  if obs is None:
   obs=m.Observation(source_id=oi.FD_SOURCE_ID,fixture_id=None,observed_at=at,source_url=url,content_hash=digest,
                     payload={'section':'market_odds_archive','data':{'division':division,'season':oi.season_label(season),'rows':len(rows),'price_type':'CLOSING'},
                              'source_reference':f'football-data:{division}:{season}','producer':'markets.history_import'})
   db.add(obs);db.flush()
  report={'matches':0,'prices':0,'rejected_prices':0,'skipped_no_time':0,'skipped_unmatched':0}
  odds_rows=[];evidence_rows=[]
  for row in rows:
   if row.get('Div') not in (None,'',division):continue
   home=oi.canonical(row.get('HomeTeam')) if division=='D1' else (row.get('HomeTeam') or '').strip()
   away=oi.canonical(row.get('AwayTeam')) if division=='D1' else (row.get('AwayTeam') or '').strip()
   ko=kickoff(row)
   if not home or not away or home==away:continue
   if ko is None:report['skipped_no_time']+=1;continue
   if ko>at:continue  # closing prices only exist after kickoff
   match_key=f'{ko.date()}:{home}:{away}'
   if match_key in done:continue
   prices,rejected=closing_prices(row);report['rejected_prices']+=rejected
   if not prices:done.add(match_key);continue
   fixture=fixture_for(db,comp,division,season,home,away,ko,url)
   if fixture is None:report['skipped_unmatched']+=1;continue
   for book,market,outcome,price in prices:
    ident=str(uuid.uuid4())
    odds_rows.append({'id':ident,'fixture_id':fixture.id,'bookmaker':book,'market_key':market,'outcome_key':outcome,'decimal_odds':price,'observed_at':ko})
    evidence_rows.append({'odds_id':ident,'observation_id':obs.id,'source_id':oi.FD_SOURCE_ID})
   done.add(match_key);report['matches']+=1;report['prices']+=len(prices)
  if odds_rows:
   db.execute(insert(m.Odds),odds_rows);db.execute(insert(m.MarketEvidence),evidence_rows)
  state.payload={'matches':sorted(done),'division':division,'season':season,'last_report':report}
  state.last_full_at=at;state.failures=0
  db.add(m.AuditEvent(actor='market-archive',action='markets.archive_import',correlation_id=comp.id,payload={'division':division,'season':oi.season_label(season),**report}))
  return report
 finally:
  db.info.pop(RUNNER_FLAG,None)


def collect(factory,fetch_fd=None,at=None,files=FILES_PER_RUN):
 """Import up to `files` season files per run: past seasons once, the current season when it changes."""
 at=at or datetime.now(timezone.utc);fetch_fd=fetch_fd or oi.fetch_csv
 current=oi.season_start(at);report={'files':[],'errors':[]}
 todo=[]
 with factory() as db:
  for division in divisions():
   for season in range(current-oi.history_seasons(),current+1):
    state=db.get(m.ProviderSyncState,f'markets:archive:{division}:{season}')
    fresh=state is not None and state.last_full_at and (season<current or utc(state.last_full_at)>at-timedelta(hours=12))
    if not fresh:todo.append((division,season))
 for division,season in todo[:files]:
  url=f'{oi.FD_BASE}{season%100:02d}{(season+1)%100:02d}/{division}.csv'
  try:
   rows,_=fetch_fd(url)
   with factory.begin() as db:r=import_file(db,division,season,rows,url,at)
   report['files'].append({'division':division,'season':season,**r})
  except Exception as exc:
   report['errors'].append({'division':division,'season':season,'code':type(exc).__name__,'detail':str(exc)[:120]})
   with factory.begin() as db:
    state=oi.cached(db,f'markets:archive:{division}:{season}',oi.FD_SOURCE_ID);state.failures=(state.failures or 0)+1
    if '404' in str(exc):state.last_full_at=at  # season file not published (yet): retry on the normal cadence
 report['remaining']=max(0,len(todo)-files)
 return report
