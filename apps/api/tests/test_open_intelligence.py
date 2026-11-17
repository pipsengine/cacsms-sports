from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine,select,func,event,DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.autonomy import open_intelligence as oi, openligadb, modelling
from app.modules.pipeline import operations

TEAMS=[('Bayern Munich','FC Bayern München'),('FC Koln','1. FC Köln'),('Dortmund','Borussia Dortmund'),('Leverkusen','Bayer 04 Leverkusen')]


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine)
    def aware(target,*_):  # SQLite drops tzinfo; production PostgreSQL keeps it.
        for col in target.__table__.columns:
            v=target.__dict__.get(col.key)
            if isinstance(col.type,DateTime) and isinstance(v,datetime) and v.tzinfo is None:target.__dict__[col.key]=v.replace(tzinfo=timezone.utc)
    event.listen(Base,'load',aware,propagate=True)
    factory=sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(m.Source(id=openligadb.SOURCE_ID,name=openligadb.SOURCE,permission='AUTHORIZED',enabled=True));db.flush()
        oi.ensure_source(db)
    yield factory
    event.remove(Base,'load',aware)
    engine.dispose()


def season_rows(season,start,score=lambda i,j,k:(i+k)%3,ol_override=None):
    """Double round robin; returns (openligadb rows, football-data rows) with identical scores unless overridden."""
    ol,fd=[],[];day=start;n=0
    for i,(fd_h,ol_h) in enumerate(TEAMS):  # every ordered pairing once = double round robin
        for j,(fd_a,ol_a) in enumerate(TEAMS):
            if i==j:continue
            hg,ag=score(i,j,0),score(j,i,1)
            kick=datetime.combine(day,datetime.min.time(),timezone.utc)+timedelta(hours=15,minutes=30)
            ol_hg,ol_ag=(ol_override or {}).get(n,(hg,ag))
            ol.append(dict(matchID=season*1000+n,matchDateTimeUTC=kick.isoformat().replace('+00:00','Z'),team1={'teamName':ol_h},team2={'teamName':ol_a},
                           matchIsFinished=True,matchResults=[{'resultTypeID':2,'pointsTeam1':ol_hg,'pointsTeam2':ol_ag}],group={'groupOrderID':n//2+1}))
            fd.append({'Div':'D1','Date':day.strftime('%d/%m/%Y'),'HomeTeam':fd_h,'AwayTeam':fd_a,'FTHG':str(hg),'FTAG':str(ag)})
            n+=1;day+=timedelta(days=3)
    return ol,fd


def load(factory,season,ol,fd):
    with factory.begin() as db:
        oi.cached(db,f'open-intel:ol:bl1:{season}',openligadb.SOURCE_ID).payload={'rows':oi.normalize_ol(ol,season)}
        oi.cached(db,f'open-intel:fd:bl1:{season}',oi.FD_SOURCE_ID).payload={'rows':oi.normalize_fd(fd,season)}


def test_team_names_map_to_canonical_identity():
    assert oi.canonical("M'gladbach")=='Borussia Mönchengladbach'
    assert oi.canonical('1. FC Koln')=='1. FC Köln' or oi.canonical('FC Koln')=='1. FC Köln'
    assert oi.canonical('FC BAYERN MÜNCHEN')=='FC Bayern München'
    assert oi.canonical('Unknown FC')=='Unknown FC'


def test_only_agreeing_scores_become_verified_results(factory):
    ol,fd=season_rows(2024,date(2024,8,1),ol_override={0:(9,9)})
    load(factory,2024,ol,fd)
    report=oi.corroborate_results(factory,at=datetime(2025,7,1,tzinfo=timezone.utc))
    assert report['reconciled']==len(ol)-1 and report['disagreements']==1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.Result))==len(ol)-1
        evidence=db.execute(select(m.ResultEvidence.result_id,func.count()).group_by(m.ResultEvidence.result_id)).all()
        assert evidence and all(n==2 for _,n in evidence), 'every verified result is backed by both independence groups'
        assert {db.get(m.Source,s).name for s in db.scalars(select(m.ResultEvidence.source_id).distinct())}=={openligadb.SOURCE,oi.FD_SOURCE}
    assert oi.corroborate_results(factory,at=datetime(2025,7,1,tzinfo=timezone.utc))['reconciled']==0, 'idempotent'


def test_independent_evidence_verifies_research_and_uncovered_sections_are_unavailable(factory):
    ol,fd=season_rows(2025,date(2025,8,1))
    load(factory,2025,ol,fd)
    at=datetime(2026,3,1,tzinfo=timezone.utc)
    oi.corroborate_results(factory,at=at)
    with factory.begin() as db:
        comp=db.scalar(select(m.Competition))
        db.add(m.Fixture(id='upcoming',competition_id=comp.id,home_name='FC Bayern München',away_name='1. FC Köln',kickoff_at=at+timedelta(days=2)));db.flush()
        db.add(m.PipelineRun(id='run',fixture_id='upcoming',mode='PAPER',status='PENDING',idempotency_key='k',context={}))
    report=oi.produce_evidence(factory,at=at)
    assert report['fixtures']==1 and report['observations']==8
    with factory.begin() as db:
        pairs={}
        for o in db.scalars(select(m.Observation).where(m.Observation.fixture_id=='upcoming')):pairs.setdefault(o.payload['section'],[]).append(o.payload['data'])
        assert all(len(v)==2 and v[0]==v[1] for v in pairs.values()), 'each provider computes the same values independently'
        receipt=operations.research(db,db.get(m.PipelineRun,'run'),at)
        dossier=db.scalar(select(m.Research).where(m.Research.fixture_id=='upcoming'))
        assert dossier.status=='VERIFIED' and receipt is not None
        status={k:v['status'] for k,v in dossier.sections.items()}
        assert all(status[k]=='VERIFIED' for k in oi.PRODUCED_SECTIONS)
        assert {status[k] for k in ('team_news','lineups','injuries')}=={'UNAVAILABLE'}
        assert dossier.sections['injuries']['details']['method']=='NO_SOURCE_COVERAGE'
    assert oi.produce_evidence(factory,at=at)['observations']==0, 'unchanged evidence is not duplicated'


def test_disagreeing_providers_do_not_verify(factory):
    ol,fd=season_rows(2025,date(2025,8,1))
    fd[3]['FTHG']=str(int(fd[3]['FTHG'])+4)
    load(factory,2025,ol,fd)
    at=datetime(2026,3,1,tzinfo=timezone.utc)
    with factory.begin() as db:
        sport=m.Sport(name='Football');db.add(sport);db.flush()
        comp=m.Competition(sport_id=sport.id,name='Bundesliga',country='Germany');db.add(comp);db.flush()
        db.add(m.Fixture(id='upcoming',competition_id=comp.id,home_name=TEAMS[0][1],away_name=TEAMS[1][1],kickoff_at=at+timedelta(days=2)));db.flush()
        db.add(m.PipelineRun(id='run',fixture_id='upcoming',mode='PAPER',status='PENDING',idempotency_key='k',context={}))
    oi.produce_evidence(factory,at=at)
    with factory.begin() as db:
        with pytest.raises(operations.Waiting):
            operations.research(db,db.get(m.PipelineRun,'run'),at)


def test_training_examples_use_only_earlier_matches():
    games=[dict(id=f'g{i}',kickoff=datetime(2025,8,1,tzinfo=timezone.utc)+timedelta(days=3*i),home_id=h,away_id=a,home_score=hs,away_score=as_)
           for i,(h,a,hs,as_) in enumerate([('A','B',2,0),('B','A',1,1),('A','B',3,1),('B','A',0,2),('A','B',1,0),('B','A',2,2),('A','B',0,1),('B','A',5,0)])]
    examples=modelling.examples_from(games)
    first=examples[0]
    assert first['fixture_id']=='g3', 'needs three prior matches per team'
    # g3 (B home vs A) may only see g0..g2: B scored 0,1,1 -> 0.6667 per match.
    assert first['features']['home_scoring_rate']==round((0+1+1)/3,4)
    games[0]['home_score']=9
    assert modelling.examples_from(games)[0]['features']!=first['features']
    games[3]['home_score']=9
    later=[e for e in modelling.examples_from(games) if e['fixture_id']=='g3'][0]
    assert later['features']==modelling.examples_from(games)[0]['features'], "a match's own result never feeds its features"


def test_odds_are_stamped_with_provider_time_and_stored_with_evidence(factory):
    published=datetime.now(timezone.utc)-timedelta(hours=20)
    with factory.begin() as db:
        sport=m.Sport(name='Football');db.add(sport);db.flush()
        comp=m.Competition(sport_id=sport.id,name='Bundesliga',country='Germany');db.add(comp);db.flush()
        db.add(m.Fixture(id='f',competition_id=comp.id,home_name='FC Bayern München',away_name='1. FC Köln',kickoff_at=published+timedelta(days=3)))
    row={'Div':'D1','Date':(published+timedelta(days=3)).strftime('%d/%m/%Y'),'HomeTeam':'Bayern Munich','AwayTeam':'FC Koln',
         'B365H':'1.27','B365D':'5.40','B365A':'12.00','B365>2.5':'1.56','B365<2.5':'2.47','AHh':'-1.75','B365AHH':'1.90','B365AHA':'1.95','AvgH':'1.30'}
    report=oi.collect_odds(factory,fetch_fd=lambda url:([row,{'Div':'E0','HomeTeam':'x'}],published))
    assert report['fixtures']==1 and report['quotes']==7
    assert report['status']=='STALE_PROVIDER_ODDS'
    with factory() as db:
        quotes=db.scalars(select(m.Odds)).all()
        assert {(q.bookmaker,q.market_key,q.outcome_key) for q in quotes}>={('Bet365','1X2','HOME'),('Bet365','OU_2.5','OVER'),('Bet365','AH_-1.75','AWAY')}
        assert all(abs((q.observed_at-published).total_seconds())<1 for q in quotes), 'never re-stamped as fresh'
        assert all(db.get(m.MarketEvidence,q.id) is not None for q in quotes)
    assert oi.collect_odds(factory,fetch_fd=lambda url:([row],published))['quotes']==0, 'same file is not re-imported'


def test_odds_reports_missing_competition_coverage(factory):
    at=datetime(2026,11,17,tzinfo=timezone.utc)
    report=oi.collect_odds(factory,fetch_fd=lambda url:([{'Div':'E0'}],at),at=at)
    assert report['status']=='NO_COMPETITION_COVERAGE'
    assert report['feed_rows']==1 and report['competition_rows']==0
    assert report['quotes']==0


def test_disabled_without_open_data_opt_in(factory,monkeypatch):
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
    assert oi.collect(factory)=={'enabled':False,'errors':[]}
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1');monkeypatch.setenv('SPORTS_FOOTBALL_DATA_ENABLED','0')
    assert oi.collect(factory)['enabled'] is False
