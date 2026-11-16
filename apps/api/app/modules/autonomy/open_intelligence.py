"""Autonomous open-data intelligence for the Bundesliga: no human input, no scraping, paper only.

Two independent, openly licensed providers feed the existing evidence-gated pipeline:

* OpenLigaDB (community API, ODbL 1.0) and
* Football-Data.co.uk (published season CSVs and the upcoming-fixtures odds CSV).

Neither provider alone verifies anything. Each provider's own rows are normalised separately and
every research section / final score is computed *independently per provider*; the existing research
quorum and result reconciler only accept a value when both independence groups agree exactly.

Work is cached in ProviderSyncState and gated by next_check_at so the 5-second autonomy cycle stays cheap.
"""
import csv,hashlib,io,json,os,unicodedata
from datetime import datetime,timedelta,timezone,date
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc
from app.modules.autonomy import openligadb

FD_SOURCE_ID=str(uuid5(NAMESPACE_URL,'https://football-data.co.uk/'))
FD_SOURCE='Football-Data.co.uk (open data)'
FD_BASE='https://football-data.co.uk/mmz4281/'
FD_FIXTURES='https://football-data.co.uk/fixtures.csv'
FD_HOSTS={'football-data.co.uk','www.football-data.co.uk'}
FD_TERMS='https://www.football-data.co.uk/disclaimer.php'
OL_BASE=openligadb.BASE+'/getmatchdata/bl1/'
COMPETITION='Bundesliga'
GROUPS={openligadb.SOURCE_ID:'openligadb',FD_SOURCE_ID:'football-data'}
PRODUCED_SECTIONS=('standings','recent_form','head_to_head','match_statistics')
FORM_WINDOW=5;RATE_WINDOW=10;H2H_WINDOW=5;MIN_MATCHES=3
CURRENT_REFRESH=timedelta(hours=1);EVIDENCE_REFRESH=timedelta(minutes=10);ODDS_REFRESH=timedelta(minutes=30)
# Football-Data short names -> OpenLigaDB canonical names (the fixture identity used across the app).
FD_ALIASES={'Augsburg':'FC Augsburg','Bayern Munich':'FC Bayern München','Bochum':'VfL Bochum','Darmstadt':'SV Darmstadt 98',
 'Dortmund':'Borussia Dortmund','Ein Frankfurt':'Eintracht Frankfurt','Elversberg':'SV 07 Elversberg','FC Koln':'1. FC Köln',
 'Freiburg':'SC Freiburg','Hamburg':'Hamburger SV','Heidenheim':'1. FC Heidenheim 1846','Hertha':'Hertha BSC','Hoffenheim':'TSG Hoffenheim',
 'Holstein Kiel':'Holstein Kiel','Leverkusen':'Bayer 04 Leverkusen',"M'gladbach":'Borussia Mönchengladbach','Mainz':'1. FSV Mainz 05',
 'Paderborn':'SC Paderborn 07','RB Leipzig':'RB Leipzig','Schalke 04':'FC Schalke 04','St Pauli':'FC St. Pauli','Stuttgart':'VfB Stuttgart',
 'Union Berlin':'1. FC Union Berlin','Werder Bremen':'SV Werder Bremen','Wolfsburg':'VfL Wolfsburg'}
BOOKMAKERS={'B365':'Bet365','PS':'Pinnacle','BW':'bwin','BV':'BetVictor','BFD':'Betfred','PP':'Paddy Power','SKB':'Sky Bet','BFE':'Betfair Exchange','WH':'William Hill','IW':'Interwetten'}


def now():return datetime.now(timezone.utc)
def enabled():return openligadb.enabled() and os.getenv('SPORTS_FOOTBALL_DATA_ENABLED','1').lower() not in ('0','false','no')
def history_seasons():
 try:return max(1,min(8,int(os.getenv('SPORTS_HISTORY_SEASONS','4'))))
 except ValueError:return 4
def season_start(at):return at.year if at.month>=7 else at.year-1
def fold(text):return ''.join(c for c in unicodedata.normalize('NFKD',str(text)) if not unicodedata.combining(c)).casefold().strip()
_CANON={fold(v):v for v in FD_ALIASES.values()}
def canonical(name):
 """Map a provider team name onto the OpenLigaDB canonical name; unknown names stay as-is (and will not corroborate)."""
 name=str(name or '').strip()
 return FD_ALIASES.get(name) or _CANON.get(fold(name)) or name


# Fetching -------------------------------------------------------------------------------

def fetch_csv(url):
 """Football-Data CSV download, restricted to its published HTTPS host; returns (rows, last_modified)."""
 import httpx
 for _ in range(3):
  p=urlparse(url)
  if p.scheme!='https' or p.hostname not in FD_HOSTS or p.username or p.password or p.port not in (None,443):raise ValueError('Unexpected Football-Data URL')
  with httpx.Client(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':os.getenv('SPORTS_OPENLIGADB_USER_AGENT','CACSMS-Sports/1.0 (autonomous research)')}) as client:
   with client.stream('GET',url) as response:
    if response.status_code in (301,302,303,307,308):url=str(response.headers.get('location') or '');continue
    response.raise_for_status();body=bytearray()
    for chunk in response.iter_bytes():
     body.extend(chunk)
     if len(body)>5_000_000:raise ValueError('Provider response too large')
    modified=response.headers.get('last-modified')
  try:stamp=parsedate_to_datetime(modified).astimezone(timezone.utc) if modified else None
  except (TypeError,ValueError):stamp=None
  return list(csv.DictReader(io.StringIO(body.decode('utf-8-sig',errors='replace')))),stamp
 raise ValueError('Too many redirects')


def _int(value):
 try:
  v=int(str(value).strip())
  return v if v>=0 else None
 except (TypeError,ValueError):return None


def _price(value):
 try:
  v=round(float(str(value).strip()),3)
  return v if 1<v<=1000 else None
 except (TypeError,ValueError):return None


def normalize_fd(rows,season):
 out=[]
 for r in rows:
  if r.get('Div') not in (None,'','D1'):continue
  raw=(r.get('Date') or '').strip()
  try:day=datetime.strptime(raw,'%d/%m/%Y').date() if len(raw)==10 else datetime.strptime(raw,'%d/%m/%y').date()
  except ValueError:continue
  home,away=canonical(r.get('HomeTeam')),canonical(r.get('AwayTeam'))
  if not home or not away or home==away:continue
  hg,ag=_int(r.get('FTHG')),_int(r.get('FTAG'))
  out.append(dict(season=season,date=day.isoformat(),home=home,away=away,hg=hg,ag=ag,finished=hg is not None and ag is not None))
 return out


def normalize_ol(matches,season):
 out=[]
 for mt in matches if isinstance(matches,list) else []:
  try:
   kickoff=datetime.fromisoformat(mt['matchDateTimeUTC'].replace('Z','+00:00'))
   home,away=canonical(mt['team1']['teamName']),canonical(mt['team2']['teamName'])
  except (KeyError,TypeError,ValueError,AttributeError):continue
  if kickoff.tzinfo is None or not home or not away or home==away:continue
  final=[x for x in mt.get('matchResults') or [] if isinstance(x,dict) and x.get('resultTypeID')==2]
  finished=mt.get('matchIsFinished') is True and bool(final)
  hg=_int(final[0].get('pointsTeam1')) if finished else None;ag=_int(final[0].get('pointsTeam2')) if finished else None
  out.append(dict(season=season,id=mt.get('matchID'),kickoff=kickoff.isoformat(),date=kickoff.date().isoformat(),home=home,away=away,
                  hg=hg,ag=ag,finished=finished and hg is not None and ag is not None,matchday=(mt.get('group') or {}).get('groupOrderID')))
 return out


def cached(db,key,source_id):
 state=db.get(m.ProviderSyncState,key)
 if state is None:state=m.ProviderSyncState(id=key,source_id=source_id or FD_SOURCE_ID,payload={},failures=0);db.add(state);db.flush()
 return state


def ensure_source(db):
 source=db.get(m.Source,FD_SOURCE_ID)
 if source is None:
  source=m.Source(id=FD_SOURCE_ID,name=FD_SOURCE,permission='AUTHORIZED',enabled=True);db.add(source);db.flush()
  db.add(m.AuditEvent(actor='autonomous-source-setup',action='source.open_data_enabled',correlation_id=source.id,
     payload={'provider':'Football-Data.co.uk','terms_url':FD_TERMS,'permission_basis':'Publicly published free CSV datasets',
              'usage':'Results, research corroboration and indicative odds; not executable prices','independence_group':'football-data'}))
 return source


def refresh_history(factory,fetch_json=None,fetch_fd=None,at=None):
 """Cache normalised rows for the last N seasons from both providers. Finished past seasons are fetched once."""
 at=at or now();fetch_json=fetch_json or openligadb.fetch;fetch_fd=fetch_fd or fetch_csv
 current=season_start(at);report={'fetched':[],'errors':[]}
 for season in range(current-history_seasons(),current+1):
  for provider in ('ol','fd'):
   key=f'open-intel:{provider}:bl1:{season}'
   with factory.begin() as db:
    state=cached(db,key,openligadb.SOURCE_ID if provider=='ol' else FD_SOURCE_ID)
    due=not state.payload.get('rows') or (season==current and (not state.next_check_at or utc(state.next_check_at)<=at))
   if not due:continue
   try:
    if provider=='ol':rows=normalize_ol(fetch_json(OL_BASE+str(season)),season)
    else:
     code=f'{season%100:02d}{(season+1)%100:02d}'
     try:rows=normalize_fd(fetch_fd(FD_BASE+code+'/D1.csv')[0],season)
     except Exception as exc:
      if season==current and '404' in str(exc):rows=[]
      else:raise
   except Exception as exc:
    report['errors'].append({'provider':provider,'season':season,'code':type(exc).__name__})
    with factory.begin() as db:
     state=cached(db,key,None);state.failures=(state.failures or 0)+1;state.next_check_at=at+timedelta(minutes=min(360,15*2**min(state.failures,4)))
    continue
   with factory.begin() as db:
    state=cached(db,key,None);state.payload={'rows':rows,'season':season};state.failures=0;state.last_full_at=at
    state.next_check_at=at+CURRENT_REFRESH if season==current else None
   report['fetched'].append(key)
 return report


def load_rows(db,provider):
 rows=[]
 for state in db.scalars(select(m.ProviderSyncState).where(m.ProviderSyncState.id.like(f'open-intel:{provider}:bl1:%'))):
  rows.extend((state.payload or {}).get('rows') or [])
 return rows


# Corroborated final results ---------------------------------------------------------------

def _hash(*parts):return hashlib.sha256(json.dumps(parts,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def add_observation(db,source_id,fixture_id,section,data,url,at,reference):
 digest=_hash(source_id,fixture_id,section,data)
 existing=db.scalar(select(m.Observation).where(m.Observation.source_id==source_id,m.Observation.content_hash==digest))
 if existing:return existing,False
 obs=m.Observation(source_id=source_id,fixture_id=fixture_id,observed_at=at,source_url=url,content_hash=digest,
                   payload={'section':section,'data':data,'source_reference':reference,'verification':'CROSS_SOURCE_QUORUM',
                            'independence_group':GROUPS[source_id],'producer':'autonomous-open-intelligence'})
 db.add(obs);db.flush()
 return obs,True


def outcome(hg,ag):
 # Settles every market the market model can price (1X2, DC, totals, team totals, BTTS, odd/even, exact score).
 from app.modules.prediction.market_model import settled_outcomes
 return {'status':'FINAL','score':{'home':hg,'away':ag},'outcomes':settled_outcomes(hg,ag)}


def season_label(season):return f'{season}/{(season+1)%100:02d}'


def fixture_for(db,row,competition_id):
 kickoff=datetime.fromisoformat(row['kickoff'])
 fixture=db.scalar(select(m.Fixture).where(m.Fixture.competition_id==competition_id,m.Fixture.home_name==row['home'],m.Fixture.away_name==row['away'],
                                           m.Fixture.kickoff_at>=kickoff-timedelta(days=3),m.Fixture.kickoff_at<=kickoff+timedelta(days=3)))
 if fixture:return fixture
 from app.modules.ingestion.service import ingest_fixture
 result=ingest_fixture(db,openligadb.SOURCE,'Football',COMPETITION,row['home'],row['away'],kickoff,openligadb.BASE+'/getmatchdata/'+str(row['id']),
                       {'source_reference':'OpenLigaDB:match:'+str(row['id']),'licence':'ODbL 1.0','licence_url':openligadb.LICENCE,'attribution':openligadb.ATTRIBUTION,
                        'verification':'COMMUNITY_SOURCE_NOT_INDEPENDENTLY_VERIFIED'})
 fixture=db.get(m.Fixture,result['fixture_id'])
 label=season_label(row['season'])
 registered=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==fixture.competition_id,m.CompetitionSeason.label==label))
 if registered is None:
  registered=m.CompetitionSeason(competition_id=fixture.competition_id,label=label,start_date=date(row['season'],7,1),end_date=date(row['season']+1,6,30),is_current=False)
  db.add(registered);db.flush()
 fixture.season_id=fixture.season_id or registered.id
 if type(row.get('matchday')) is int and not fixture.matchday:fixture.matchday=row['matchday']
 return fixture


def corroborate_results(factory,at=None,limit=500):
 """Emit official_result observations from BOTH providers only when their final scores agree exactly."""
 at=at or now();report={'reconciled':0,'disagreements':0,'pending':0}
 with factory() as db:
  fd={(r['season'],r['home'],r['away']):r for r in load_rows(db,'fd') if r['finished']}
  ol=[r for r in load_rows(db,'ol') if r['finished'] and utc(datetime.fromisoformat(r['kickoff']))<at]
  tracked=db.get(m.ProviderSyncState,'open-intel:results')
  done=set(((tracked.payload or {}).get('done') or []) if tracked else [])
 todo=[]
 for r in sorted(ol,key=lambda r:r['kickoff']):
  other=fd.get((r['season'],r['home'],r['away']))
  key=f"{r['season']}:{r['id']}"
  if key in done:continue
  if other is None:report['pending']+=1;continue
  if (other['hg'],other['ag'])!=(r['hg'],r['ag']):report['disagreements']+=1;continue
  todo.append((key,r))
 from app.modules.results.automation import reconcile_observation
 for key,r in todo[:limit]:
  with factory.begin() as db:
   comp=db.scalar(select(m.Competition).where(m.Competition.name==COMPETITION,m.Competition.country=='Germany'))
   if comp is None:
    sport=db.scalar(select(m.Sport).where(m.Sport.name=='Football')) or m.Sport(name='Football')
    db.add(sport);db.flush();comp=m.Competition(sport_id=sport.id,name=COMPETITION,country='Germany');db.add(comp);db.flush()
   fixture=fixture_for(db,r,comp.id)
   # Evidence is stamped when this system observed agreement (after the match, never in the future).
   if utc(fixture.kickoff_at)+timedelta(hours=2)>at:continue
   stamp=at
   data=outcome(r['hg'],r['ag'])
   for source_id,url in ((openligadb.SOURCE_ID,openligadb.BASE+'/getmatchdata/'+str(r['id'])),(FD_SOURCE_ID,FD_BASE+f"{r['season']%100:02d}{(r['season']+1)%100:02d}/D1.csv")):
    obs,_=add_observation(db,source_id,fixture.id,'official_result',data,url,stamp,f"{GROUPS[source_id]}:{r['season']}:{r['home']}-{r['away']}")
    if db.scalar(select(m.ResultEvidence.observation_id).where(m.ResultEvidence.observation_id==obs.id)) is None:
     with db.begin_nested():reconcile_observation(db,obs.id)
   state=cached(db,'open-intel:results',None);state.payload={'done':sorted({*((state.payload or {}).get('done') or []),key})}
   report['reconciled']+=1
 return report


# Independent per-provider research evidence ----------------------------------------------------

def points(gf,ga):return 3 if gf>ga else 1 if gf==ga else 0


def team_matches(rows,team,before):
 out=[]
 for r in rows:
  if not r['finished'] or r['date']>before or team not in (r['home'],r['away']):continue
  gf,ga=(r['hg'],r['ag']) if r['home']==team else (r['ag'],r['hg'])
  out.append((r['date'],r['home'],r['away'],gf,ga))
 return sorted(out)


def features_for(rows,home,away,horizon):
 """The six model features from one provider's finished rows up to `horizon` (inclusive ISO date). None if too few matches."""
 h,a=team_matches(rows,home,horizon),team_matches(rows,away,horizon)
 if len(h)<MIN_MATCHES or len(a)<MIN_MATCHES:return None
 form=lambda ms:round(sum(points(gf,ga) for *_,gf,ga in ms[-FORM_WINDOW:])/len(ms[-FORM_WINDOW:]),4)
 rate=lambda ms,i:round(sum(x[i] for x in ms[-RATE_WINDOW:])/len(ms[-RATE_WINDOW:]),4)
 return {'home_form':form(h),'away_form':form(a),'home_scoring_rate':rate(h,3),'away_scoring_rate':rate(a,3),
         'home_conceding_rate':rate(h,4),'away_conceding_rate':rate(a,4)},h,a


def letters(ms):return ''.join('W' if gf>ga else 'D' if gf==ga else 'L' for *_,gf,ga in ms[-FORM_WINDOW:])


def table(rows,season,horizon):
 teams={}
 for r in rows:
  if r['season']!=season or not r['finished'] or r['date']>horizon:continue
  for team,gf,ga in ((r['home'],r['hg'],r['ag']),(r['away'],r['ag'],r['hg'])):
   t=teams.setdefault(team,dict(club=team,played=0,wins=0,draws=0,losses=0,goals_for=0,goals_against=0))
   t['played']+=1;t['goals_for']+=gf;t['goals_against']+=ga
   t['wins' if gf>ga else 'draws' if gf==ga else 'losses']+=1
 out=[]
 for t in teams.values():out.append({**t,'goal_difference':t['goals_for']-t['goals_against'],'points':3*t['wins']+t['draws']})
 out.sort(key=lambda t:(-t['points'],-t['goal_difference'],-t['goals_for'],t['club']))
 for i,t in enumerate(out,1):t['rank']=i
 return out


def sections_for(rows,home,away,season,horizon):
 built=features_for(rows,home,away,horizon)
 if built is None:return {}
 f,h,a=built
 meetings=sorted((r for r in rows if r['finished'] and r['date']<=horizon and {r['home'],r['away']}=={home,away}),key=lambda r:r['date'])[-H2H_WINDOW:]
 base={'horizon':horizon,'computed_from':'provider final results up to the shared horizon'}
 return {'recent_form':{**base,'home_form':f['home_form'],'away_form':f['away_form'],'home_last5':letters(h),'away_last5':letters(a),'window':FORM_WINDOW},
         'match_statistics':{**base,**{k:f[k] for k in ('home_scoring_rate','away_scoring_rate','home_conceding_rate','away_conceding_rate')},
                             'window':RATE_WINDOW,'home_matches':min(len(h),RATE_WINDOW),'away_matches':min(len(a),RATE_WINDOW)},
         'head_to_head':{**base,'meetings':[{'date':r['date'],'home':r['home'],'away':r['away'],'score':f"{r['hg']}-{r['ag']}"} for r in meetings]},
         'standings':{**base,'season':season_label(season),'rows':table(rows,season,horizon)}}


def shared_horizon(ol,fd,season):
 """Latest date both providers have published finished results for (so independent computations can agree)."""
 last=lambda rows:max((r['date'] for r in rows if r['season']==season and r['finished']),default=None)
 a,b=last(ol),last(fd)
 if a and b:return min(a,b)
 # Before the first matchday: use the previous season's common end.
 pa=max((r['date'] for r in ol if r['season']==season-1 and r['finished']),default=None)
 pb=max((r['date'] for r in fd if r['season']==season-1 and r['finished']),default=None)
 return min(pa,pb) if pa and pb else None


def produce_evidence(factory,at=None):
 at=at or now();report={'fixtures':0,'observations':0,'skipped':[]}
 with factory() as db:
  ol,fd=load_rows(db,'ol'),load_rows(db,'fd')
  comp=db.scalar(select(m.Competition).where(m.Competition.name==COMPETITION,m.Competition.country=='Germany'))
  if comp is None:return report
  fixtures=db.scalars(select(m.Fixture).where(m.Fixture.competition_id==comp.id,m.Fixture.kickoff_at>at,m.Fixture.kickoff_at<=at+timedelta(days=7),
                                            m.Fixture.status.notin_(['CANCELLED','CANCELED','ABANDONED']))).all()
  targets=[(f.id,f.home_name,f.away_name,f.kickoff_at) for f in fixtures]
 season=season_start(at);horizon=shared_horizon(ol,fd,season)
 if horizon is None:report['skipped'].append('NO_SHARED_HORIZON');return report
 for fixture_id,home,away,kickoff in targets:
  if horizon>=utc(kickoff).date().isoformat():continue
  per={source_id:sections_for(rows,home,away,season,horizon) for source_id,rows in ((openligadb.SOURCE_ID,ol),(FD_SOURCE_ID,fd))}
  if not all(per.values()):report['skipped'].append(fixture_id);continue
  with factory.begin() as db:
   for source_id,sections in per.items():
    url=OL_BASE+str(season) if source_id==openligadb.SOURCE_ID else FD_BASE+f'{season%100:02d}{(season+1)%100:02d}/D1.csv'
    for section,data in sections.items():
     _,created=add_observation(db,source_id,fixture_id,section,data,url,min(at,utc(kickoff)-timedelta(minutes=1)),f'{GROUPS[source_id]}:{section}:{horizon}')
     report['observations']+=created
  report['fixtures']+=1
 return report


# Indicative odds ---------------------------------------------------------------------------------

def odds_rows(row,stamp):
 iso=stamp.isoformat().replace('+00:00','Z');prices=[];other=[]
 for prefix,book in BOOKMAKERS.items():
  trio=[_price(row.get(prefix+s)) for s in ('H','D','A')]
  if all(trio):prices.extend(dict(bookmaker=book,market_key='1X2',outcome_key=k,decimal_odds=v,observed_at=iso) for k,v in zip(('HOME','DRAW','AWAY'),trio))
  ou=[_price(row.get(prefix+s)) for s in ('>2.5','<2.5')]
  if all(ou):other.extend(dict(bookmaker=book,market_key='OU_2.5',outcome_key=k,decimal_odds=v,observed_at=iso) for k,v in zip(('OVER','UNDER'),ou))
  line=(row.get('AHh') or '').strip();ah=[_price(row.get(prefix+s)) for s in ('AHH','AHA')]
  if line and all(ah):
   try:key='AH_'+format(float(line),'g')
   except ValueError:key=None
   if key:other.extend(dict(bookmaker=book,market_key=key,outcome_key=k,decimal_odds=v,observed_at=iso) for k,v in zip(('HOME','AWAY'),ah))
 return prices,other


def collect_odds(factory,fetch_fd=None,at=None):
 """Upcoming-fixture odds from Football-Data's published CSV. Prices are stamped with the file's Last-Modified time
 (when the provider captured them), so freshness gates judge them honestly."""
 at=at or now();fetch_fd=fetch_fd or fetch_csv;report={'fixtures':0,'quotes':0}
 rows,stamp=fetch_fd(FD_FIXTURES)
 stamp=min(stamp or at,at)
 from app.modules.pipeline.operations import import_prices
 for row in rows:
  if row.get('Div')!='D1':continue
  home,away=canonical(row.get('HomeTeam')),canonical(row.get('AwayTeam'))
  try:day=datetime.strptime((row.get('Date') or '').strip(),'%d/%m/%Y').date()
  except ValueError:continue
  prices,other=odds_rows(row,stamp)
  if not prices and not other:continue
  with factory.begin() as db:
   fixture=db.scalar(select(m.Fixture).join(m.Competition,m.Competition.id==m.Fixture.competition_id).where(m.Competition.name==COMPETITION,
        m.Fixture.home_name==home,m.Fixture.away_name==away,m.Fixture.kickoff_at>=datetime.combine(day-timedelta(days=2),datetime.min.time(),timezone.utc),
        m.Fixture.kickoff_at<=datetime.combine(day+timedelta(days=2),datetime.min.time(),timezone.utc)))
   if fixture is None or utc(fixture.kickoff_at)<=at:continue
   obs,created=add_observation(db,FD_SOURCE_ID,fixture.id,'market_odds',{'prices':prices,'other_prices':other},FD_FIXTURES,stamp,f'football-data:odds:{stamp.isoformat()}')
   if not created:continue
   if prices:
    try:
     with db.begin_nested():import_prices(db,fixture.id,at)
    except Exception as exc:report.setdefault('errors',[]).append({'fixture_id':fixture.id,'code':type(exc).__name__})
   for q in other:
    quote=m.Odds(fixture_id=fixture.id,bookmaker=q['bookmaker'],market_key=q['market_key'],outcome_key=q['outcome_key'],decimal_odds=q['decimal_odds'],observed_at=stamp)
    db.add(quote);db.flush();db.add(m.MarketEvidence(odds_id=quote.id,observation_id=obs.id,source_id=FD_SOURCE_ID))
   report['fixtures']+=1;report['quotes']+=len(prices)+len(other)
 return report


# Orchestration ---------------------------------------------------------------------------------

def due(factory,key,every,at):
 with factory.begin() as db:
  state=cached(db,key,None)
  if state.next_check_at and utc(state.next_check_at)>at:return False
  state.next_check_at=at+every
 return True


def collect(factory,at=None):
 """One autonomous step; each part is independently scheduled and failure-isolated."""
 at=at or now()
 if not enabled():return {'enabled':False,'errors':[]}
 report={'enabled':True,'errors':[]}
 with factory.begin() as db:ensure_source(db)
 for name,every,job in (('history',timedelta(minutes=5),lambda:refresh_history(factory,at=at)),
                        ('results',timedelta(minutes=1),lambda:corroborate_results(factory,at=at)),
                        ('evidence',EVIDENCE_REFRESH,lambda:produce_evidence(factory,at=at)),
                        ('odds',ODDS_REFRESH,lambda:collect_odds(factory,at=at)),
                        ('market-archive',timedelta(minutes=2),lambda:__import__('app.modules.markets.history_import',fromlist=['collect']).collect(factory,at=at)),
                        ('qualification',timedelta(minutes=2),lambda:__import__('app.modules.qualification.autonomous',fromlist=['cycle']).cycle(factory,at=at)),
                        ('accumulator',timedelta(minutes=5),lambda:__import__('app.modules.strategies.accumulator',fromlist=['cycle']).cycle(factory,at=at)),
                        ('singles',timedelta(minutes=5),lambda:__import__('app.modules.strategies.programme_engine',fromlist=['cycle']).cycle(factory,'singles',at=at)),
                        ('jackpot',timedelta(minutes=5),lambda:__import__('app.modules.strategies.programme_engine',fromlist=['cycle']).cycle(factory,'jackpot',at=at)),
                        ('draws',timedelta(minutes=5),lambda:__import__('app.modules.strategies.programme_engine',fromlist=['cycle']).cycle(factory,'draws',at=at)),
                        ('rollover',timedelta(minutes=5),lambda:__import__('app.modules.strategies.programme_engine',fromlist=['cycle']).cycle(factory,'rollover',at=at)),
                        ('ticket-builder',timedelta(minutes=1),lambda:__import__('app.modules.tickets.builder',fromlist=['cycle']).cycle(factory,at=at)),
                        ('market-benchmark',timedelta(minutes=30),lambda:__import__('app.modules.markets.intelligence',fromlist=['refresh_benchmark']).refresh_benchmark(factory,at=at))):
  if not due(factory,'open-intel:schedule:'+name,every,at):continue
  try:
   report[name]=job()
   report['errors'].extend(report[name].get('errors',[]) if isinstance(report[name],dict) else [])
  except Exception as exc:
   report['errors'].append({'step':name,'code':type(exc).__name__,'detail':str(exc)[:160]})
 try:
  from app.modules.autonomy.modelling import train_if_due,train_market_model_if_due
  report['modelling']=train_if_due(factory,at=at)
  report['market_model']=train_market_model_if_due(factory,at=at)
 except Exception as exc:
  report['errors'].append({'step':'modelling','code':type(exc).__name__,'detail':str(exc)[:160]})
 return report
