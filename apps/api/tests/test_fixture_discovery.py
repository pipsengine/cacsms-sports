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


def profile(store):
    with store.begin() as db:
        return discovery.register_competition(db, providers.OL_ID,
            {'provider_key': 'bl1', 'name': 'Bundesliga', 'country': 'Germany', 'sport': 'Football', 'season': '2026', 'details': {}}, AT).id


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


def test_discovery_updates_provisional_bundesliga_table_and_rejects_bad_refresh(store, monkeypatch):
    from app.modules.research import catalog
    from app.modules.standings import routes as standings_routes
    at=datetime.now(timezone.utc)-timedelta(minutes=5)
    ident=profile(store);request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    finished=raw_ol(at-timedelta(days=1),matchIsFinished=True,matchResults=[
        {'resultTypeKind':'HalfTime','pointsTeam1':8,'pointsTeam2':0},
        {'resultTypeKind':'After90Minutes','pointsTeam1':2,'pointsTeam2':1}])
    assert acquire(store,providers.OL_ID,request,[finished],at)['table_status']=='UPDATED'
    with store() as db:
        p=db.get(m.DiscoveryCompetition,ident);cid,sid=p.competition_id,p.season_id
        table=catalog.standings(db,cid,sid)
        assert table['mode']=='community_computed' and table['source']['official'] is False
        assert table['source']['verified_at'] is None and table['rows'][0]['points']==3
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


def test_stale_bundesliga_cache_prompts_a_durable_refresh(store,monkeypatch):
    monkeypatch.setenv('SPORTS_OPENLIGADB_ENABLED','1')
    monkeypatch.setenv('SPORTS_THESPORTSDB_ENABLED','0')
    ident=profile(store);request={'kind':'fixtures','profile_id':ident,'shortcut':'bl1','season':'2026'}
    with store.begin() as db:
        old=discovery.enqueue(db,providers.OL_ID,request,AT,interval=21600,priority=25)
        old.status='COMPLETED'
        db.add(m.ProviderSyncState(id='openligadb:bl1:2026',source_id=providers.OL_ID,
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
