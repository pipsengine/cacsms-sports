"""Controlled provider payloads never enter the live database; live evidence is separate."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.autonomy import fixture_discovery as discovery, fixture_providers as providers
from app.modules.autonomy.fixture_status import summary
from app.modules.research import fixture_intelligence as routes
from test_browser_intelligence import factory as make_factory

AT = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv('SPORTS_FIXTURE_HORIZON_DAYS', '7')
    monkeypatch.setenv('SPORTS_DEPLOYMENT_ENV', 'development')
    session = make_factory()
    with session.begin() as db:
        db.add_all([m.Source(id=providers.OL_ID, name='Controlled ODbL provider', enabled=True, permission='AUTHORIZED'),
                    m.Source(id=providers.SPORTSDB_ID, name='Controlled API provider', enabled=True, permission='AUTHORIZED')])
    return session


def profile(store, shortcut='bl1'):
    with store.begin() as db:
        return discovery.register_competition(db, providers.OL_ID,
            {'provider_key': shortcut, 'name': {'bl1':'Bundesliga','bl2':'2. Bundesliga','bl3':'3. Liga'}[shortcut],
             'country': 'Germany', 'sport': 'Football', 'season': '2026', 'details': {}}, AT).id


def raw_ol(kickoff=AT+timedelta(days=1), **overrides):
    return {'matchID': 111, 'matchDateTimeUTC': kickoff.isoformat(), 'matchIsFinished': False,
            'team1': {'teamId': 1, 'teamName': 'Controlled Home'}, 'team2': {'teamId': 2, 'teamName': 'Controlled Away'}, **overrides}


def raw_sportsdb(kickoff=AT+timedelta(days=1), **overrides):
    return {'idEvent': '222', 'idLeague': '4331', 'strLeague': 'German Bundesliga', 'strSport': 'Soccer',
            'strSeason': '2026-2027', 'strHomeTeam': 'Controlled Home', 'strAwayTeam': 'Controlled Away',
            'strTimestamp': kickoff.replace(tzinfo=None).isoformat(), 'strStatus': 'NS', **overrides}


def acquire(store, source, request, payload, at=AT):
    with store.begin() as db: discovery.enqueue(db, source, request, at, interval=1)
    ticket = discovery.claim(store, at)
    assert ticket is not None
    return discovery.execute(store, ticket, lambda *_: payload, at)


def test_real_persistence_api_scope_and_two_provider_verification(store, monkeypatch):
    ident = profile(store)
    request = {'kind': 'fixtures', 'profile_id': ident, 'shortcut': 'bl1', 'season': '2026'}
    assert acquire(store, providers.OL_ID, request, [raw_ol()])['counts'] == {'EXTRACTED': 1}
    with store() as db:
        assert summary(db, AT)['verified_fixtures'] == 0
        fixture = db.scalar(select(m.Fixture))
        assert fixture.season_id and fixture.home_team_id and fixture.away_team_id
    assert acquire(store, providers.SPORTSDB_ID, {'kind': 'day'}, {'events': [raw_sportsdb()]}, AT+timedelta(seconds=4))['counts'] == {'VERIFIED': 1}
    with store() as db:
        assert summary(db, AT+timedelta(seconds=5))['verified_fixtures'] == 1
        result = routes.overview(db, at=AT+timedelta(seconds=5), hours=72)
        assert result['fixtures']['total'] == 1
        row = result['fixtures']['rows'][0]
        assert row['verification'] == 'VERIFIED' and len(row['source_evidence']) == 2
        assert row['kickoff_utc'].utcoffset() == timedelta(0)
        assert row['kickoff_lagos'].utcoffset() == timedelta(hours=1)
        assert db.scalar(select(func.count()).select_from(m.Prediction)) == 0
        assert summary(db, AT+timedelta(hours=25))['verified_fixtures'] == 0
    monkeypatch.setattr(routes, 'SessionLocal', store)
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app)
    assert client.get('/api/v1/sports/fixture-intelligence/overview?hours=720').status_code == 200
    assert client.get('/api/v1/sports/fixture-intelligence/jobs').json()['jobs']


def test_repeated_collection_deduplicates_and_reuses_canonical_team_keys(store):
    ident = profile(store); request = {'kind': 'fixtures', 'profile_id': ident, 'shortcut': 'bl1', 'season': '2026'}
    acquire(store, providers.OL_ID, request, [raw_ol()])
    result = acquire(store, providers.OL_ID, request, [raw_ol()], AT+timedelta(seconds=61))
    assert result['counts'] == {'DUPLICATE': 1}
    with store() as db:
        for model in (m.Fixture, m.FixtureCandidate, m.FixtureSourceMapping, m.Observation):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(m.Team.canonical_key).where(m.Team.name == 'Controlled Home')) == 'controlled home'


def test_openligadb_candidate_does_not_store_nested_team_artwork(store):
    ident=profile(store)
    request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    row=raw_ol(team1={'teamId':1,'teamName':'Controlled Home','teamIconUrl':'image-data'},
               team2={'teamId':2,'teamName':'Controlled Away','teamIconUrl':'image-data'})
    assert acquire(store,providers.OL_ID,request,[row])['counts']=={'EXTRACTED':1}
    with store() as db:
        raw=db.scalar(select(m.FixtureCandidate)).data['raw']
        assert 'teamIconUrl' not in raw['team1'] and 'teamIconUrl' not in raw['team2']


def test_disputed_feed_is_blocked_and_existing_fixtures_are_excluded(store, monkeypatch):
    from app.modules.autonomy import community_tables
    from app.modules.autonomy.fixture_status import verified_query
    reason = community_tables.QUARANTINED_TABLES['openligadb:la1:2026']
    monkeypatch.delitem(community_tables.QUARANTINED_TABLES, 'openligadb:la1:2026')
    with store.begin() as db:
        ident = discovery.register_competition(db, providers.OL_ID,
            {'provider_key': 'la1', 'name': 'La Liga', 'country': 'Spain',
             'sport': 'Football', 'season': '2026', 'details': {}}, AT).id
    request = {'kind': 'fixtures', 'profile_id': ident, 'shortcut': 'la1', 'season': '2026'}
    assert acquire(store, providers.OL_ID, request, [raw_ol()])['counts'] == {'EXTRACTED': 1}
    monkeypatch.setitem(community_tables.QUARANTINED_TABLES, 'openligadb:la1:2026', reason)
    with store.begin() as db:
        fixture = db.scalar(select(m.Fixture))
        existing = db.scalar(select(m.FixtureSourceMapping))
        db.add(m.FixtureSourceMapping(source_id=providers.SPORTSDB_ID, provider_fixture_id='matching',
            fixture_id=fixture.id, candidate_id=existing.candidate_id, job_id=existing.job_id,
            signature=existing.signature, state='VERIFIED', last_seen_at=AT))
        db.flush()
        assert db.scalars(verified_query(AT)).all() == []
        result = routes.overview(db, at=AT, hours=72)
        assert result['fixtures']['total'] == 0
        assert result['metrics']['quarantined_fixtures'] == 1
        assert result['metrics']['fixtures_window'] == 0
        assert db.scalar(select(func.count()).select_from(m.FixtureCandidate)) == 1
        job = discovery.enqueue(db, providers.OL_ID, request, AT + timedelta(seconds=61), interval=1)
        job_id = job.id
    assert discovery.claim(store, AT + timedelta(seconds=61)) is None
    with store() as db:
        blocked = db.get(m.FixtureDiscoveryJob, job_id)
        assert blocked.status == 'BLOCKED' and 'SOURCE_FEED_QUARANTINED' in blocked.error
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED', '1')
    with store.begin() as db:
        discovery.plan(db, AT + timedelta(minutes=5))
        assert not any(job.status == 'QUEUED' and job.request.get('shortcut') == 'la1'
                       for job in db.scalars(select(m.FixtureDiscoveryJob)))


@pytest.mark.parametrize('shortcut', ['bl1', 'bl2', 'bl3'])
def test_discovery_updates_provisional_bundesliga_table_and_rejects_bad_refresh(store, monkeypatch, shortcut):
    from app.modules.research import catalog
    from app.modules.standings import routes as standings_routes
    at=datetime.now(timezone.utc)-timedelta(minutes=5)
    ident=profile(store,shortcut);request={'kind':'fixtures','profile_id':ident,'shortcut':shortcut,'season':'2026'}
    finished=raw_ol(at-timedelta(days=1),matchIsFinished=True,matchResults=[
        {'resultTypeKind':'HalfTime','pointsTeam1':8,'pointsTeam2':0},
        {'resultTypeKind':'After90Minutes','pointsTeam1':2,'pointsTeam2':1}])
    assert acquire(store,providers.OL_ID,request,[finished],at)['table_status']=='UPDATED'
    with store() as db:
        p=db.get(m.DiscoveryCompetition,ident);cid,sid=p.competition_id,p.season_id
        table=catalog.standings(db,cid,sid)
        assert table['mode']=='community_computed' and table['source']['official'] is False
        assert table['source']['verified_at'] is None and table['rows'][0]['points']==3
        assert table['source']['source_url'].endswith('/getmatchdata/'+shortcut+'/2026')
        assert table['rows'][0]['goals_for']==2
        assert catalog.standings(db,cid,sid,scope='away')['rows'][1]['played']==1
        for model in (m.Result,m.StandingsSnapshot,m.Research,m.Prediction):
            assert db.scalar(select(func.count()).select_from(model))==0
    changed={**finished,'matchResults':[{'resultTypeKind':'After90Minutes','pointsTeam1':0,'pointsTeam2':3}]}
    assert acquire(store,providers.OL_ID,request,[changed],at+timedelta(seconds=61))['table_status']=='UPDATED'
    invalid={**finished,'matchResults':[{'resultTypeKind':'HalfTime','pointsTeam1':8,'pointsTeam2':0}]}
    rejected=acquire(store,providers.OL_ID,request,[invalid],at+timedelta(seconds=122))
    assert rejected['table_status']=='REJECTED' and rejected['table_error']=='INVALID_STANDINGS_FINAL_SCORE'
    with store() as db:
        table=catalog.standings(db,cid,sid)
        assert table['rows'][0]['club']=='Controlled Away' and table['rows'][0]['points']==3
        assert db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.error.is_not(None))).error=='STANDINGS:INVALID_STANDINGS_FINAL_SCORE'
    monkeypatch.setattr(standings_routes,'SessionLocal',store)
    app=FastAPI();app.include_router(standings_routes.router)
    response=TestClient(app).get('/api/v1/sports/standings/table',params={'competition_id':cid,'season':sid,'all_rows':True})
    assert response.status_code==200 and response.json()['classification']=='community_computed'
    assert response.json()['rows'][0]['club']=='Controlled Away'
    health=TestClient(app).get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()
    assert health['status']=='FAILED' and health['failures']==1 and health['errors']==['INVALID_STANDINGS_FINAL_SCORE']
    with store.begin() as db: db.get(m.Source,providers.OL_ID).enabled=False
    with store() as db: assert catalog.standings(db,cid,sid)['rows']==[]


def test_discovery_does_not_create_rankings_without_finished_games(store):
    ident=profile(store);request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    assert acquire(store,providers.OL_ID,request,[raw_ol()])['table_status']=='NO_COMPLETED_MATCHES'
    with store() as db:
        cache=db.get(m.ProviderSyncState,'openligadb:bl1:2026')
        assert cache.payload['community_tables']=={}


def test_german_season_history_is_partial_cutoff_safe_and_not_verified(store):
    from app.modules.research.deep_workspace_routes import build_workspace
    at=datetime.now(timezone.utc)-timedelta(minutes=1)
    ident=profile(store)
    request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    upcoming=raw_ol(at+timedelta(days=1),matchID=1000)
    matches=[upcoming]
    for day in range(1,23):
        matches.append(raw_ol(at-timedelta(days=day),matchID=1000+day,matchIsFinished=True,
            team1={'teamId':1,'teamName':'Controlled Home'},
            team2={'teamId':100+day,'teamName':'Opponent '+str(day)},
            matchResults=[{'resultTypeKind':'After90Minutes','pointsTeam1':2,'pointsTeam2':1}]))
    matches.append(raw_ol(at-timedelta(days=2),matchID=2000,matchIsFinished=True,
        team1={'teamName':'No Provider ID'},team2={'teamId':2,'teamName':'Controlled Away'},
        matchResults=[{'resultTypeKind':'After90Minutes','pointsTeam1':1,'pointsTeam2':0}]))
    result=acquire(store,providers.OL_ID,request,matches,at)
    assert result['history']['observations']==1 and result['history']['skipped_missing_team_identity']==1
    with store() as db:
        fixture=db.scalar(select(m.Fixture).where(m.Fixture.kickoff_at>at))
        fixture_id=fixture.id
        workspace=build_workspace(db,fixture.id)
        evidence=next(e for e in workspace['evidence'] if e['section']=='recent_form')
        assert evidence['verification']=='SINGLE_SOURCE'
        assert evidence['data']['coverage']=='PARTIAL' and len(evidence['data']['results'])==20
        assert evidence['data']['results'][0]['event_id']=='1001'
        assert all(datetime.fromisoformat(r['kickoff_at'])<at for r in evidence['data']['results'])
        assert next(s for s in workspace['sections'] if s['key']=='recent_form')['status']=='PROVISIONAL'
        assert db.scalar(select(func.count()).select_from(m.Prediction))==0
        assert not any(e['section']=='recent_form' for e in build_workspace(db,fixture.id,at-timedelta(seconds=1))['evidence'])
    with store.begin() as db: db.get(m.Source,providers.OL_ID).enabled=False
    with store() as db:
        evidence=next(e for e in build_workspace(db,fixture_id)['evidence'] if e['section']=='recent_form')
        assert evidence['status']=='UNVERIFIED' and evidence['data'] is None


def test_season_history_rejects_mismatched_league_before_caching(store):
    ident=profile(store)
    request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    row=raw_ol(leagueSeason=2025)
    result=acquire(store,providers.OL_ID,request,[row])
    assert result['table_status']=='REJECTED'
    assert result['table_error']=='HISTORY_COMPETITION_IDENTITY_MISMATCH'
    with store() as db:
        assert not (db.get(m.ProviderSyncState,'openligadb:bl1:2026').payload or {}).get('community_tables')


@pytest.mark.parametrize('shortcut', ['bl1', 'bl2', 'bl3'])
def test_stale_bundesliga_cache_prompts_a_durable_refresh(store,monkeypatch,shortcut):
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','0')
    ident=profile(store,shortcut);request={'kind':'fixtures','profile_id':ident,'shortcut':shortcut,'season':'2026'}
    with store.begin() as db:
        old=discovery.enqueue(db,providers.OL_ID,request,AT,interval=21600,priority=25)
        old.status='COMPLETED'
        db.add(m.ProviderSyncState(id='openligadb:'+shortcut+':2026',source_id=providers.OL_ID,
                                   payload={},failures=0,last_full_at=AT-timedelta(hours=7)))
        discovery.plan(db,AT)
        jobs=db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='fixtures')).all()
        assert any(job.status=='QUEUED' and job.request==request for job in jobs)


def test_community_table_warns_when_source_is_stale(store):
    from app.modules.research import catalog
    at=datetime.now(timezone.utc)-timedelta(hours=25)
    ident=profile(store);request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    match=raw_ol(at-timedelta(days=1),matchIsFinished=True,matchResults=[
        {'resultTypeKind':'After90Minutes','pointsTeam1':1,'pointsTeam2':0}])
    assert acquire(store,providers.OL_ID,request,[match],at)['table_status']=='UPDATED'
    with store() as db:
        p=db.get(m.DiscoveryCompetition,ident)
        assert 'over 24 hours old' in catalog.standings(db,p.competition_id,p.season_id)['warning']


def sportsdb_table_row(**overrides):
    return {'idLeague':'4331','strSeason':'2026-2027','idTeam':'1','strTeam':'Controlled Home',
            'strGroup':'League','intRank':'1','intPlayed':'4','intWin':'2','intDraw':'1','intLoss':'1',
            'intGoalsFor':'6','intGoalsAgainst':'4','intGoalDifference':'2','intPoints':'7',
            'strForm':'WWDL','dateUpdated':'2026-01-01 10:00:00',**overrides}


def test_sportsdb_partial_table_persists_and_preserves_scope_and_source_permissions(store, monkeypatch):
    from app.modules.research import catalog
    from app.modules.standings import routes as standings
    at=datetime.now(timezone.utc)-timedelta(minutes=5)
    assert acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb(at+timedelta(days=1))]},at)['counts']=={'EXTRACTED':1}
    with store() as db:
        p=db.scalar(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.source_id==providers.SPORTSDB_ID))
        pid,cid,sid=p.id,p.competition_id,p.season_id
    request={'kind':'table','profile_id':pid,'provider_key':'4331','season':'2026-2027'}
    assert 'lookuptable.php?l=4331&s=2026-2027' in providers.request_url(providers.SPORTSDB_ID,request)
    assert acquire(store,providers.SPORTSDB_ID,request,{'table':[sportsdb_table_row()]},at+timedelta(seconds=4))['table_status']=='UPDATED'
    with store() as db:
        report=catalog.standings(db,cid,sid)
        assert report['mode']=='community_partial' and report['rows'][0]['points']==7
        assert 'at most five rows' in report['warning'] and not report['source']['official']
        assert catalog.standings(db,cid,sid,scope='home')['rows']==[]
        assert db.scalar(select(func.count()).select_from(m.StandingsSnapshot))==0
    bad=sportsdb_table_row(intPlayed='5')
    result=acquire(store,providers.SPORTSDB_ID,request,{'table':[bad]},at+timedelta(seconds=8))
    assert result['table_status']=='REJECTED' and result['table_error']=='INCONSISTENT_STANDINGS_ROW'
    monkeypatch.setattr(standings,'SessionLocal',store)
    app=FastAPI();app.include_router(standings.router);client=TestClient(app)
    response=client.get('/api/v1/sports/standings/table',params={'competition_id':cid,'season':sid})
    assert response.json()['classification']=='community_partial' and response.json()['rows'][0]['club']=='Controlled Home'
    assert client.get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()['errors']==['INCONSISTENT_STANDINGS_ROW']
    with store.begin() as db: db.get(m.Source,providers.SPORTSDB_ID).enabled=False
    with store() as db: assert catalog.standings(db,cid,sid)['rows']==[]


@pytest.mark.parametrize('shortcut',['pl','la1'])
def test_quarantined_community_table_is_not_shown_instead_of_partial_source(store,monkeypatch,shortcut):
    from app.modules.research import catalog
    from app.modules.standings import routes as standings
    at=datetime.now(timezone.utc)-timedelta(minutes=5)
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb(at+timedelta(days=1))]},at)
    with store() as db:
        p=db.scalar(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.source_id==providers.SPORTSDB_ID))
        pid,cid,sid=p.id,p.competition_id,p.season_id
    request={'kind':'table','profile_id':pid,'provider_key':'4331','season':'2026-2027'}
    acquire(store,providers.SPORTSDB_ID,request,{'table':[sportsdb_table_row()]},at+timedelta(seconds=4))
    with store.begin() as db:
        db.add(m.ProviderSyncState(id='openligadb:'+shortcut+':2026',source_id=providers.OL_ID,
               last_full_at=at+timedelta(seconds=8),failures=0,payload={'competition_id':cid,'season_id':sid,
               'community_tables':{'overall':[{'rank':1,'club':'Wrong club'}]},'standings_url':'https://example.test'}))
    with store() as db:
        table=catalog.standings(db,cid,sid)
        assert table['mode']=='community_partial' and table['rows'][0]['club']=='Controlled Home'
        assert 'Quarantined source' in table['warning']
    monkeypatch.setattr(standings,'SessionLocal',store)
    app=FastAPI();app.include_router(standings.router)
    health=TestClient(app).get('/api/v1/sports/standings/health',params={'competition_id':cid}).json()
    assert health['status']=='FAILED' and health['errors']


@pytest.mark.parametrize('bad', [
    {'idLeague':'wrong'}, {'strSeason':'2025-2026'}, {'intGoalDifference':'9'},
    {'strTeam':''}, {'intWin':'not-a-number'}
])
def test_sportsdb_partial_table_rejects_mismatched_or_invalid_rows(store,bad):
    at=AT
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb()]},at)
    with store() as db: p=db.scalar(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.source_id==providers.SPORTSDB_ID)); pid=p.id
    request={'kind':'table','profile_id':pid,'provider_key':'4331','season':'2026-2027'}
    result=acquire(store,providers.SPORTSDB_ID,request,{'table':[sportsdb_table_row(**bad)]},at+timedelta(seconds=4))
    assert result['table_status']=='REJECTED'


def test_sportsdb_table_planning_and_empty_feed(store,monkeypatch):
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','1')
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb()]})
    with store.begin() as db:
        discovery.plan(db,AT+timedelta(seconds=4))
        job=db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='table'))
        assert job and job.request['season']=='2026-2027'
        request=dict(job.request)
        for pending in db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.status=='QUEUED')):
            pending.status='SUPERSEDED'
    assert acquire(store,providers.SPORTSDB_ID,request,{'table':None},AT+timedelta(seconds=8))['table_status']=='NO_DATA'


@pytest.mark.parametrize('sport,status,expected_status',[
    ('Ice Hockey','P2','LIVE'),('Ice Hockey','AOT','FINISHED'),
    ('Tennis','NS','SCHEDULED'),('Table Tennis','NS','SCHEDULED')])
def test_new_sports_are_persisted_with_provenance_and_visible_in_fixture_overview(store, monkeypatch, sport, status, expected_status):
    raw=raw_sportsdb(strSport=sport,strLeague='Controlled Competition',strStatus=status)
    result=acquire(store,providers.SPORTSDB_ID,{'kind':'day','sport':sport},{'events':[raw]})
    assert result['counts']=={'EXTRACTED':1}
    with store() as db:
        fixture=db.scalar(select(m.Fixture))
        assert fixture.status==expected_status
        mapping=db.scalar(select(m.FixtureSourceMapping))
        assert mapping.source_id==providers.SPORTSDB_ID and mapping.state=='EXTRACTED'
        listing=routes.overview(db,at=AT,hours=72,sport=sport,status='all')
        assert listing['fixtures']['total']==1
        assert listing['fixtures']['rows'][0]['sport']==sport
        assert listing['fixtures']['rows'][0]['verification']=='EXTRACTED'
    assert acquire(store,providers.SPORTSDB_ID,{'kind':'day','sport':sport},{'events':[raw]},AT+timedelta(seconds=61))['counts']=={'DUPLICATE':1}
    monkeypatch.setattr(routes,'SessionLocal',store)
    original_overview=routes.overview
    monkeypatch.setattr(routes,'overview',lambda db,**kwargs: original_overview(db,at=AT,**kwargs))
    app=FastAPI();app.include_router(routes.router)
    response=TestClient(app).get('/api/v1/sports/fixture-intelligence/overview',params={'sport':sport,'status':'all','hours':720})
    assert response.status_code==200 and response.json()['fixtures']['rows'][0]['sport']==sport


@pytest.mark.parametrize('sport,overrides,reason',[
    ('Ice Hockey',{'strHomeTeam':None},'INVALID_PARTICIPANTS'),
    ('Tennis',{'strAwayTeam':''},'INVALID_PARTICIPANTS'),
    ('Table Tennis',{'strStatus':None},'FIXTURE_STATUS_UNAVAILABLE'),
    ('Tennis',{'strStatus':'P2'},'UNSUPPORTED_FIXTURE_STATUS:P2'),
    ('Ice Hockey',{'strTimestamp':None,'dateEvent':None},'KICKOFF_TIME_UNAVAILABLE')])
def test_new_sports_reject_incomplete_or_unsupported_events(store,sport,overrides,reason):
    raw=raw_sportsdb(strSport=sport,**overrides)
    result=acquire(store,providers.SPORTSDB_ID,{'kind':'day','sport':sport},{'events':[raw]})
    assert result['counts']=={'REJECTED':1}
    with store() as db:
        assert db.scalar(select(func.count()).select_from(m.Fixture))==0
        assert reason in db.scalar(select(m.FixtureCandidate)).reasons[0]


@pytest.mark.parametrize('status,expected',[('P1','LIVE'),('P2','LIVE'),('P3','LIVE'),('PT','LIVE'),('AOT','FINISHED')])
def test_documented_ice_hockey_statuses(status,expected):
    assert providers.fixture(providers.SPORTSDB_ID,raw_sportsdb(strSport='Ice Hockey',strStatus=status),{})['status']==expected


def test_new_sports_accept_explicit_postponement_without_status():
    raw=raw_sportsdb(strSport='Tennis',strStatus=None,strPostponed='yes')
    assert providers.fixture(providers.SPORTSDB_ID,raw,{})['status']=='POSTPONED'


def test_planning_schedules_requested_sports_without_replacing_existing_sports(store,monkeypatch):
    monkeypatch.setenv('SPORTS_FIXTURE_DISCOVERY_ENABLED','1')
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','1')
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
    with store.begin() as db:
        discovery.plan(db,AT)
        requests=[job.request for job in db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='day'))]
        today=[request['sport'] for request in requests if request['date']==AT.date().isoformat()]
        assert set(today)=={'Soccer','Basketball','Ice Hockey','Tennis','Table Tennis'}
        assert len(today)==5
        assert set(summary(db,AT)['target_sports'])=={'Football','Basketball','Ice Hockey','Tennis','Table Tennis'}
        monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','0')
        assert summary(db,AT)['target_sports']==[]


@pytest.mark.parametrize('sport', ['Soccer', 'Basketball', 'Ice Hockey', 'Tennis', 'Table Tennis'])
def test_team_recent_is_single_source_partial_and_never_verifies_research(store, monkeypatch, sport):
    from app.modules.pipeline.operations import research, Waiting
    from app.modules.research.deep_workspace_routes import build_workspace
    at=datetime.now(timezone.utc)-timedelta(minutes=1)
    raw=raw_sportsdb(at+timedelta(days=1),strSport=sport,strLeague='Controlled Competition',
                     idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day','sport':sport},{'events':[raw]},at)
    with store() as db: fixture_id=db.scalar(select(m.Fixture.id))
    request={'kind':'team_recent','fixture_id':fixture_id,'side':'home','provider_team_id':'1234'}
    result={'idEvent':'999','idHomeTeam':'1234','idAwayTeam':'2000','strHomeTeam':'Controlled Home',
            'strAwayTeam':'Opponent','strSport':sport,'strStatus':'FT',
            'strTimestamp':(at-timedelta(days=1)).isoformat(),'intHomeScore':'2','intAwayScore':'1','strLeague':'Controlled Competition'}
    response=acquire(store,providers.SPORTSDB_ID,request,{'results':[result]},at+timedelta(seconds=4))
    assert response['team_recent']['accepted']==1
    with store() as db:
        observation=db.scalar(select(m.Observation).where(m.Observation.payload['section'].as_string()=='team_recent_results'))
        assert observation.payload['verification']=='SINGLE_SOURCE'
        assert observation.payload['data']['coverage']=='PARTIAL'
        workspace=build_workspace(db,fixture_id)
        evidence=next(e for e in workspace['evidence'] if e['id']==observation.id)
        assert evidence['section']=='recent_form' and evidence['verification']=='SINGLE_SOURCE'
        assert next(s for s in workspace['sections'] if s['key']=='recent_form')['status']=='PROVISIONAL'
        assert db.scalar(select(func.count()).select_from(m.Prediction))==0
        run=SimpleNamespace(fixture_id=fixture_id)
        with pytest.raises(Waiting) as exc: research(db,run,at+timedelta(seconds=5))
        assert exc.value.code=='NO_CORROBORATED_EVIDENCE'
        dossier=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture_id))
        assert dossier.status=='PARTIAL' and dossier.sections['recent_form']['status']=='PROVISIONAL'
        assert dossier.sections['recent_form']['evidence_ids']==[observation.id]
        with pytest.raises(Waiting): research(db,run,at+timedelta(seconds=6))
        assert db.scalar(select(func.count()).select_from(m.Research).where(m.Research.fixture_id==fixture_id))==1
        assert next(s for s in build_workspace(db,fixture_id)['sections'] if s['key']=='recent_form')['count']==1
    assert 'eventslast.php?id=1234' in providers.request_url(providers.SPORTSDB_ID,request)


def test_fixture_list_exposes_only_authorized_pre_cutoff_partial_form(store):
    at=datetime.now(timezone.utc)-timedelta(minutes=1)
    upcoming=raw_sportsdb(at+timedelta(days=1),idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[upcoming]},at)
    with store() as db: fixture_id=db.scalar(select(m.Fixture.id))
    request={'kind':'team_recent','fixture_id':fixture_id,'side':'home','provider_team_id':'1234'}
    event={'idEvent':'999','idHomeTeam':'1234','idAwayTeam':'2000','strHomeTeam':'Controlled Home',
           'strAwayTeam':'Opponent','strSport':'Soccer','strStatus':'FT',
           'strTimestamp':(at-timedelta(days=1)).isoformat(),'intHomeScore':'2','intAwayScore':'1'}
    acquire(store,providers.SPORTSDB_ID,request,{'results':[event]},at+timedelta(seconds=4))
    with store.begin() as db:
        db.add(m.Source(id='revoked',name='Revoked source',enabled=False,permission='AUTHORIZED'))
        data={'section':'team_recent_results','verification':'SINGLE_SOURCE',
              'data':{'side':'away','results':[{'event_id':'other'}]}}
        db.add_all([m.Observation(source_id='revoked',fixture_id=fixture_id,content_hash='revoked',
                                  observed_at=at,payload=data),
                    m.Observation(source_id=providers.SPORTSDB_ID,fixture_id=fixture_id,content_hash='future',
                                  observed_at=at+timedelta(hours=1),payload=data)])
    with store() as db:
        row=routes.overview(db,at=at+timedelta(seconds=5),hours=72)['fixtures']['rows'][0]
        assert row['partial_form']['sides']==['home'] and row['partial_form']['source_count']==1
        assert row['verification']=='EXTRACTED' and row['prediction'] is None and row['odds'] is None
    with store.begin() as db:db.get(m.Source,providers.SPORTSDB_ID).enabled=False
    with store() as db:
        assert routes.overview(db,at=at+timedelta(seconds=5),hours=72)['fixtures']['rows'][0]['partial_form'] is None


@pytest.mark.parametrize('sport,league', [('Soccer','English Premier League'),('Basketball','Controlled Basketball League'),('Ice Hockey','Controlled Hockey League')])
def test_sportsdb_season_history_is_partial_and_validated(store, monkeypatch, sport, league):
    from app.modules.research.deep_workspace_routes import build_workspace
    at=datetime.now(timezone.utc)-timedelta(minutes=1)
    upcoming=raw_sportsdb(at+timedelta(days=1),strSport=sport,strLeague=league,
                          idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day','sport':sport},{'events':[upcoming]},at)
    with store() as db:
        fixture=db.scalar(select(m.Fixture))
        fixture_id=fixture.id
        mapped=db.scalar(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.source_id==providers.SPORTSDB_ID,
                         m.DiscoveryCompetition.season_id==fixture.season_id))
        ident=mapped.id
    request={'kind':'season_history','profile_id':ident,'provider_key':'4331','season':'2026-2027'}
    row=raw_sportsdb(at-timedelta(days=3),idEvent='501',strSport=sport,strLeague=league,
                     strStatus='FT',idHomeTeam='1234',idAwayTeam='9999',intHomeScore='2',intAwayScore='1')
    outcome=acquire(store,providers.SPORTSDB_ID,request,{'events':[row,row,{**row,'idEvent':'502','idLeague':'999'},
        {**row,'idEvent':'503','strTimestamp':(at+timedelta(hours=1)).isoformat()},
        {**row,'idEvent':'504','intHomeScore':None}]},at+timedelta(seconds=4))
    assert outcome['season_history']['accepted_events']==1
    assert outcome['season_history']['observations']==1
    assert outcome['season_history']['rejected']==['INVALID_OR_DUPLICATE_EVENT_ID','HISTORY_COMPETITION_IDENTITY_MISMATCH',
                                                   'EVENT_NOT_BEFORE_CUTOFF','FINAL_SCORE_UNAVAILABLE']
    with store() as db:
        evidence=next(e for e in build_workspace(db,fixture_id)['evidence'] if e['section']=='recent_form')
        assert evidence['verification']=='SINGLE_SOURCE' and evidence['data']['coverage']=='PARTIAL'
        assert evidence['data']['results'][0]['event_id']=='501'
        assert 'may not contain the most recent' in evidence['data']['limitation']
        assert next(s for s in build_workspace(db,fixture_id)['sections'] if s['key']=='recent_form')['status']=='PROVISIONAL'
    assert 'eventsseason.php?id=4331&s=2026-2027' in providers.request_url(providers.SPORTSDB_ID,request)


def test_planning_schedules_season_history_for_upcoming_mapped_league(store,monkeypatch):
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','1')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb()]})
    with store.begin() as db:
        discovery.plan(db,AT+timedelta(seconds=4))
        jobs=db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='season_history')).all()
        assert len(jobs)==1 and jobs[0].request['season']=='2026-2027'


def test_recent_results_reject_wrong_team_future_and_incomplete_scores(store):
    at=datetime.now(timezone.utc)-timedelta(minutes=1)
    raw=raw_sportsdb(at+timedelta(days=1),idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw]},at)
    with store() as db: fixture_id=db.scalar(select(m.Fixture.id))
    request={'kind':'team_recent','fixture_id':fixture_id,'side':'home','provider_team_id':'1234'}
    result={'idEvent':'999','idHomeTeam':'1234','idAwayTeam':'2000','strHomeTeam':'Controlled Home',
            'strAwayTeam':'Opponent','strSport':'Soccer','strStatus':'FT',
            'strTimestamp':(at-timedelta(days=1)).isoformat(),'intHomeScore':'2','intAwayScore':'1'}
    rows=[{**result,'idHomeTeam':'wrong'}, {**result,'strTimestamp':(at+timedelta(hours=1)).isoformat()},
          {**result,'intAwayScore':None}, {**result,'strSport':'Basketball'}]
    outcome=acquire(store,providers.SPORTSDB_ID,request,{'results':rows},at+timedelta(seconds=4))
    assert outcome['team_recent']['accepted']==0
    assert outcome['team_recent']['rejected']==['TEAM_ID_MISMATCH','EVENT_NOT_BEFORE_CUTOFF','FINAL_SCORE_UNAVAILABLE','SPORT_MISMATCH']
    with store() as db:
        assert db.scalar(select(func.count()).select_from(m.Observation))==1


def test_planning_enqueues_recent_results_only_for_mapped_teams(store, monkeypatch):
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','1')
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','0')
    raw=raw_sportsdb(idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw]},AT)
    with store.begin() as db:
        discovery.plan(db,AT+timedelta(seconds=4))
        jobs=db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='team_recent')).all()
        assert {(j.request['side'],j.request['provider_team_id']) for j in jobs}=={('home','1234'),('away','5678')}
        assert {j.priority for j in jobs}=={23}


def test_expired_or_revoked_recent_jobs_do_not_fetch(store):
    raw=raw_sportsdb(AT+timedelta(seconds=30),idHomeTeam='1234',idAwayTeam='5678')
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw]},AT)
    with store.begin() as db:
        fixture=db.scalar(select(m.Fixture))
        fixture_id=fixture.id
        request={'kind':'team_recent','fixture_id':fixture_id,'side':'home','provider_team_id':'1234'}
        job=discovery.enqueue(db,providers.SPORTSDB_ID,request,AT+timedelta(seconds=4),interval=1)
        job_id=job.id
    assert discovery.claim(store,AT+timedelta(seconds=31)) is None
    with store.begin() as db:
        assert db.get(m.FixtureDiscoveryJob,job_id).status=='SUPERSEDED'
        db.get(m.Fixture,fixture_id).kickoff_at=AT+timedelta(days=1)
        job=discovery.enqueue(db,providers.SPORTSDB_ID,request,AT+timedelta(seconds=32),interval=1)
        job_id=job.id
        db.get(m.Source,providers.SPORTSDB_ID).enabled=False
    assert discovery.claim(store,AT+timedelta(seconds=32)) is None
    with store() as db:assert db.get(m.FixtureDiscoveryJob,job_id).status=='BLOCKED'


@pytest.mark.parametrize('raw,reason', [({'matchID': 5}, 'matchDateTimeUTC'),
    (raw_ol(team2={'teamName':'Controlled Home'}), 'INVALID_PARTICIPANTS'),
    (raw_ol(matchDateTimeUTC='2026-11-19T12:00:00'), 'UTC_TIMEZONE_MISSING'),
    ('parser changed', 'matchDateTimeUTC')])
def test_invalid_rows_are_quarantined_not_promoted(store, raw, reason):
    ident = profile(store)
    result = acquire(store, providers.OL_ID, {'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}, [raw])
    assert result['counts'] == {'REJECTED': 1}
    with store() as db:
        assert db.scalar(select(func.count()).select_from(m.Fixture)) == 0
        candidate = db.scalar(select(m.FixtureCandidate))
        assert reason in candidate.reasons[0]


def test_empty_feed_success_is_not_fixture_verification_and_schema_change_retries(store):
    result = acquire(store, providers.SPORTSDB_ID, {'kind': 'day'}, {'events': None})
    assert result['received'] == 0 and result['coverage_complete'] is False
    result = acquire(store, providers.SPORTSDB_ID, {'kind': 'day'}, {'renamed': []}, AT+timedelta(seconds=4))
    assert result['status'] == 'RETRY_SCHEDULED' and result['error'] == 'PARSER_SCHEMA_MISMATCH'
    with store() as db:
        health = summary(db, AT)
        assert health['verified_fixtures'] == 0
        source = next(row for row in health['sources'] if row['id'] == providers.SPORTSDB_ID)
        assert source['state'] == 'FAILED'
        assert source['errors'][0]['reason'] == 'PARSER_SCHEMA_MISMATCH'


def test_source_health_reports_restriction_and_candidate_counts(store):
    from app.modules.acquisition.source_policy import register_prohibited_sources
    ident = profile(store)
    acquire(store, providers.OL_ID, {'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}, [raw_ol()])
    with store.begin() as db:
        register_prohibited_sources(db)
    with store() as db:
        sources = summary(db, AT)['sources']
        assert next(row for row in sources if row['name'] == 'BetExplorer')['restriction']
        assert next(row for row in sources if row['id'] == providers.OL_ID)['candidate_counts'] == {'EXTRACTED': 1}


def test_leases_survive_connection_recreation_and_stale_owner_cannot_finish(store):
    with store.begin() as db:
        first = discovery.enqueue(db, providers.OL_ID, {'kind': 'catalogue','season':'2026'}, AT)
        assert discovery.enqueue(db, providers.OL_ID, {'kind': 'catalogue','season':'2026'}, AT).id == first.id
    ticket = discovery.claim(store, AT)
    assert discovery.claim(store, AT) is None
    replacement = discovery.claim(store, AT+timedelta(seconds=181))
    assert replacement['id'] == ticket['id'] and replacement['owner'] != ticket['owner']
    assert discovery.execute(store, ticket, lambda *_: [], AT+timedelta(seconds=181))['error'] == 'WORKER_LEASE_LOST'
    assert discovery.execute(store, replacement, lambda *_: [], AT+timedelta(seconds=181))['received'] == 0


def test_source_failure_backs_off_then_dead_letters_with_incident(store):
    with store.begin() as db: discovery.enqueue(db, providers.OL_ID, {'kind':'catalogue','season':'2026'}, AT)
    stamp = AT
    for attempt in range(3):
        ticket = discovery.claim(store, stamp)
        def fail(*_): raise providers.ProviderError('HTTP_429', retry_after=600)
        result = discovery.execute(store, ticket, fail, stamp)
        with store() as db:
            job = db.get(m.FixtureDiscoveryJob, ticket['id'])
            assert job.next_run_at.replace(tzinfo=timezone.utc) >= stamp+timedelta(seconds=600)
            stamp = job.next_run_at.replace(tzinfo=timezone.utc)
    assert result['status'] == 'DEAD'
    with store() as db:
        assert db.scalar(select(m.Incident)).severity == 'HIGH'
        assert len(db.scalar(select(m.FixtureDiscoveryJob)).result['failures']) == 3


def test_reschedule_disagreement_quarantines_identity_and_revocation_removes_verification(store):
    ident=profile(store);request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    acquire(store,providers.OL_ID,request,[raw_ol()])
    acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb()]},AT+timedelta(seconds=4))
    result=acquire(store,providers.SPORTSDB_ID,{'kind':'day'},{'events':[raw_sportsdb(AT+timedelta(days=2))]},AT+timedelta(seconds=8))
    assert result['counts']=={'CONFLICT':1}
    with store() as db:
        assert summary(db,AT)['verified_fixtures']==0
        assert db.scalar(select(func.count()).select_from(m.Fixture))==1
        assert db.scalar(select(m.Fixture.kickoff_at)).replace(tzinfo=timezone.utc)==AT+timedelta(days=1)


def test_development_key_is_not_a_production_credential(monkeypatch):
    monkeypatch.setenv('SPORTS_DEPLOYMENT_ENV','production');monkeypatch.setenv('SPORTS_THESPORTSDB_KEY','123')
    with pytest.raises(providers.ProviderError,match='PRODUCTION_CREDENTIAL_REQUIRED'):providers.sportsdb_key()


def test_unverified_managed_fixture_cannot_enter_prediction(store):
    from app.modules.pipeline.operations import predict,Waiting
    ident=profile(store)
    acquire(store,providers.OL_ID,{'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'},[raw_ol()])
    with store() as db:
        fixture=db.scalar(select(m.Fixture))
        with pytest.raises(Waiting,match='Fixture identity needs matching fresh evidence'):predict(db,SimpleNamespace(fixture_id=fixture.id),AT)


def test_unicode_competitions_rename_and_season_identity_stay_canonical(store):
    with store.begin() as db:
        value={'provider_key':'lower','name':'Test League','country':'Germany','sport':'Football','season':'2026','details':{}}
        first=discovery.register_competition(db,providers.OL_ID,value,AT)
        original=first.competition_id
        renamed=discovery.register_competition(db,providers.OL_ID,{**value,'name':'Renamed League'},AT+timedelta(hours=1))
        assert renamed.competition_id==original and db.get(m.Competition,original).name=='Renamed League'
        next_season=discovery.register_competition(db,providers.OL_ID,{**value,'season':'2027','name':'Renamed League'},AT+timedelta(hours=2))
        assert next_season.competition_id==original
        assert discovery.key('联赛甲')!=discovery.key('联赛乙')


def test_change_poll_only_schedules_delayed_refresh_on_change(store):
    ident=profile(store)
    request={'kind':'poll','profile_id':ident,'shortcut':'bl1','season':'2026','group':11}
    first=acquire(store,providers.OL_ID,request,'2026-11-18T09:00:00')
    assert first['change_detected'] is True
    with store() as db:
        refresh=db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.kind=='fixtures'))
        assert refresh.next_run_at.replace(tzinfo=timezone.utc)>=AT+timedelta(seconds=60)
        assert db.scalar(select(func.count()).select_from(m.Fixture))==0


def test_known_division_change_is_a_review_candidate_not_official_promotion(store):
    from datetime import date
    with store.begin() as db:
        old=discovery.register_competition(db,providers.OL_ID,{'provider_key':'bl1','name':'Bundesliga','sport':'Football','country':'Germany','season':'2025','details':{'division':1}},AT)
        season=m.CompetitionSeason(competition_id=old.competition_id,label='2025/26',start_date=date(2025,8,1),end_date=date(2026,6,1));db.add(season);db.flush()
        prior=m.Fixture(competition_id=old.competition_id,season_id=season.id,home_name='Controlled Home',away_name='Old Opponent',kickoff_at=AT-timedelta(days=200),status='FINISHED');db.add(prior);db.flush()
        db.add(m.Observation(source_id=providers.OL_ID,fixture_id=prior.id,source_url='https://api.openligadb.de/',content_hash='prior-season-evidence',observed_at=AT-timedelta(days=199),payload={'source_reference':'controlled-prior'}))
        current=discovery.register_competition(db,providers.OL_ID,{'provider_key':'bl2','name':'2. Bundesliga','sport':'Football','country':'Germany','season':'2026','details':{'division':2}},AT)
        ident=current.id
    acquire(store,providers.OL_ID,{'kind':'fixtures','profile_id':ident,'shortcut':'bl2','season':'2026'},[raw_ol()])
    with store() as db:
        change=db.scalar(select(m.AuditEvent).where(m.AuditEvent.action=='competition.membership_transition_candidate'))
        assert change.payload['classification']=='RELEGATION_CANDIDATE' and change.payload['review_required']


def test_production_credential_failure_does_not_disable_other_source_bootstrap(store,monkeypatch):
    monkeypatch.setenv('SPORTS_DEPLOYMENT_ENV','production');monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','1');monkeypatch.setenv('SPORTS_THESPORTSDB_KEY','123')
    with store.begin() as db:
        discovery.bootstrap(db)
        assert discovery.authorized(db,providers.OL_ID)
