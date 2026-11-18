"""Durable multi-provider discovery integrated with the existing autonomous controller."""
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.db import models as m
from app.modules.autonomy import fixture_providers as providers
from app.modules.research.league import utc


def now(): return datetime.now(timezone.utc)
def enabled(): return os.getenv('SPORTS_FIXTURE_DISCOVERY_ENABLED', '0') == '1'
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
def key(value): return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if c.isalnum())


def horizon():
    value = int(os.getenv('SPORTS_FIXTURE_HORIZON_DAYS', '7'))
    if value not in (1, 3, 7, 30): raise ValueError('Fixture horizon must be 1, 3, 7 or 30 days')
    return value


def authorized(db, source_id):
    source = db.get(m.Source, source_id)
    return source is not None and source.enabled and source.permission == 'AUTHORIZED'


def bootstrap(db):
    definitions = [(providers.OL_ID, providers.openligadb.SOURCE, providers.openligadb.enabled(), providers.openligadb.LICENCE, 'ODbL 1.0 community API')]
    if os.getenv('SPORTS_THESPORTSDB_ENABLED', '0') == '1':
        try:credential=providers.sportsdb_key()
        except providers.ProviderError:credential=None
        if credential:definitions.append((providers.SPORTSDB_ID, 'TheSportsDB (documented API)', True,
                            'https://www.thesportsdb.com/docs_terms_of_use.php',
                            'Development-only public key' if credential == '123' else 'Configured API subscription; coverage depends on tier'))
    for source_id, name, allowed, licence, scope in definitions:
        if not allowed or db.get(m.Source, source_id) is not None: continue
        db.add(m.Source(id=source_id, name=name, permission='AUTHORIZED', enabled=True))
        db.add(m.AuditEvent(actor='fixture-discovery', action='source.fixture_adapter_registered', correlation_id=source_id,
                           payload={'terms_url': licence, 'permission_scope': scope, 'checked_at': '2026-11-18', 'images_collected': False}))
    db.flush()


def enqueue(db, source_id, request, at, interval=21600, priority=50):
    identity = digest([source_id, request, int(at.timestamp()) // interval])
    existing = db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.idempotency_key == identity))
    if existing: return existing
    try:
        with db.begin_nested():
            job = m.FixtureDiscoveryJob(source_id=source_id, kind=request['kind'], request=request,
                  idempotency_key=identity, priority=priority, status='QUEUED', next_run_at=at, created_at=at)
            db.add(job); db.flush()
        return job
    except IntegrityError:
        return db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.idempotency_key == identity))


def register_competition(db, source_id, value, at):
    if not value or not value['name'] or len(value['name']) > 200 or not value['provider_key']: raise ValueError('INVALID_COMPETITION_IDENTITY')
    value = {**value, 'details': dict(value.get('details', {}))}
    original_season = value['season']
    value['details']['provider_season'] = original_season
    match = re.fullmatch(r'(\d{4})[-/](\d{4})', original_season)
    if match: value['season'] = match[1] + '/' + match[2][-2:]
    elif source_id == providers.OL_ID and value['provider_key'] in ('bl1', 'bl2', 'bl3') and original_season.isdigit():
        value['season'] = original_season + '/' + str(int(original_season) + 1)[-2:]
    query = select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.source_id == source_id,
             m.DiscoveryCompetition.provider_key == value['provider_key'])
    profile = db.scalar(query.where(m.DiscoveryCompetition.season_label == value['season']))
    prior = db.scalar(query.order_by(m.DiscoveryCompetition.last_seen_at.desc()).limit(1))
    if profile is not None:
        old_name=profile.name
        if profile.name != value['name']:
            db.add(m.AuditEvent(actor='fixture-discovery', action='competition.provider_renamed', correlation_id=profile.competition_id,
                               payload={'source_id': source_id, 'before': profile.name, 'after': value['name']}))
        profile.name = value['name']; profile.last_seen_at = at; profile.active = True
        profile.details = {**profile.details, **value.get('details', {})}
        competition = db.get(m.Competition, profile.competition_id)
        if competition.name==old_name:competition.name=value['name']
        if value.get('country') and not competition.country: competition.country = value['country']
        return profile
    sport = db.scalar(select(m.Sport).where(m.Sport.name == value['sport']))
    if sport is None:
        sport = m.Sport(name=value['sport']); db.add(sport); db.flush()
    aliases = {'English Premier League': ('Premier League', 'England'), 'German Bundesliga': ('Bundesliga', 'Germany'),
               'Spanish La Liga': ('La Liga', 'Spain'), 'Italian Serie A': ('Serie A', 'Italy'), 'French Ligue 1': ('Ligue 1', 'France')}
    name, country = aliases.get(value['name'], (value['name'], value.get('country')))
    competition = db.get(m.Competition, prior.competition_id) if prior else db.scalar(select(m.Competition).where(m.Competition.sport_id == sport.id, m.Competition.name == name))
    if competition is not None and country and competition.country and competition.country != country:
        competition = None  # Equal labels in different countries do not establish identity.
    if competition is None:
        canonical_id = str(uuid5(NAMESPACE_URL, 'competition:' + sport.id + ':' + str(country) + ':' + key(name)))
        competition = db.get(m.Competition, canonical_id)
        if competition is None:
            competition = m.Competition(id=canonical_id, sport_id=sport.id, name=name, country=country)
            db.add(competition); db.flush()
    elif country and not competition.country: competition.country = country
    profile = m.DiscoveryCompetition(source_id=source_id, provider_key=value['provider_key'], season_label=value['season'],
                  competition_id=competition.id, name=value['name'], last_seen_at=at, active=True,
                  source_url=providers.openligadb.BASE if source_id == providers.OL_ID else 'https://www.thesportsdb.com/documentation', details=value.get('details', {}))
    db.add(profile); db.flush()
    db.add(m.AuditEvent(actor='fixture-discovery', action='competition.season_discovered', correlation_id=competition.id,
                       payload={'provider_key': value['provider_key'], 'season': value['season'], 'previous_season': prior.season_label if prior else None, 'source_id': source_id}))
    return profile


def plan(db, at):
    bootstrap(db)
    if providers.openligadb.enabled() and authorized(db, providers.OL_ID):
        for season in {at.year, at.year if at.month >= 7 else at.year - 1}:
            enqueue(db, providers.OL_ID, {'kind': 'catalogue', 'season': str(season)}, at, interval=86400, priority=5)
    if os.getenv('SPORTS_THESPORTSDB_ENABLED', '0') == '1' and authorized(db, providers.SPORTSDB_ID):
        enqueue(db, providers.SPORTSDB_ID, {'kind': 'catalogue'}, at, interval=86400, priority=5)
        for day in range(-1, horizon() + 1):
            for sport in providers.SPORTSDB_SPORTS:
                enqueue(db, providers.SPORTSDB_ID, {'kind': 'day', 'sport': sport, 'date': (at + timedelta(days=day)).date().isoformat()}, at, interval=900 if day==0 else 21600, priority=15 + day if day >= 0 else 35)
    seen = set()
    for profile in db.scalars(select(m.DiscoveryCompetition).where(m.DiscoveryCompetition.active.is_(True)).order_by(m.DiscoveryCompetition.last_seen_at.desc())):
        identity = (profile.source_id, profile.provider_key)
        if identity in seen or not authorized(db, profile.source_id): continue
        seen.add(identity)
        if profile.source_id == providers.OL_ID:
            provider_season = profile.details.get('provider_season', profile.season_label)
            if provider_season not in (str(at.year), str(at.year - 1) if at.month < 7 else str(at.year)): continue
            request = {'kind': 'fixtures', 'profile_id': profile.id, 'shortcut': profile.provider_key, 'season': provider_season}
        elif profile.source_id == providers.SPORTSDB_ID:
            request = {'kind': 'fixtures', 'provider_key': profile.provider_key}
            enqueue(db, profile.source_id, {'kind': 'league', 'provider_key': profile.provider_key}, at, interval=86400, priority=22)
        else: continue
        live = db.scalar(select(m.Fixture.id).where(m.Fixture.competition_id == profile.competition_id,
               m.Fixture.status.notin_(('FINISHED','CANCELLED','POSTPONED')),m.Fixture.kickoff_at>=at-timedelta(hours=4),m.Fixture.kickoff_at<=at+timedelta(minutes=30)).limit(1))
        interval = 900 if live and profile.source_id==providers.SPORTSDB_ID else 21600
        if profile.source_id == providers.OL_ID and profile.provider_key == 'bl1':
            cache = db.get(m.ProviderSyncState, 'openligadb:bl1:' + provider_season)
            if cache is None or not cache.last_full_at or utc(cache.last_full_at) < at - timedelta(hours=6):
                interval = 900
        enqueue(db, profile.source_id, request, at, interval=interval, priority=25)
        if live and profile.source_id==providers.OL_ID and profile.details.get('poll_group'):
            enqueue(db,profile.source_id,{**request,'kind':'poll','group':profile.details['poll_group']},at,interval=120,priority=20)
    pending=db.scalars(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.status.in_(('QUEUED','RETRY_SCHEDULED'))).order_by(m.FixtureDiscoveryJob.created_at.desc())).all()
    seen_requests=set()
    for job in pending:
        descriptor={k:v for k,v in job.request.items() if k!='profile_id' or job.source_id==providers.OL_ID}
        identity=(job.source_id,digest(descriptor))
        if identity in seen_requests:
            job.status='SUPERSEDED';job.finished_at=at;job.result={**job.result,'reason':'A newer queued refresh covers the same provider request; original execution history retained'}
        else:seen_requests.add(identity)


def claim(factory, at=None):
    at = at or now()
    with factory.begin() as db:
        jobs = db.scalars(select(m.FixtureDiscoveryJob).where(
            or_(m.FixtureDiscoveryJob.status.in_(('QUEUED', 'RETRY_SCHEDULED')),
                (m.FixtureDiscoveryJob.status == 'RUNNING') & or_(m.FixtureDiscoveryJob.lease_until <= at,m.FixtureDiscoveryJob.lease_until.is_(None))),
            m.FixtureDiscoveryJob.next_run_at <= at).order_by(m.FixtureDiscoveryJob.priority, m.FixtureDiscoveryJob.created_at)
            .limit(100).with_for_update(skip_locked=True)).all()
        for job in jobs:
            if not authorized(db, job.source_id):
                job.status = 'BLOCKED'; job.error = 'SOURCE_NOT_AUTHORIZED'; continue
            rate_id = 'fixture-rate:' + job.source_id
            rate = db.scalar(select(m.ProviderSyncState).where(m.ProviderSyncState.id == rate_id).with_for_update())
            if rate is None:
                rate = m.ProviderSyncState(id=rate_id, source_id=job.source_id, payload={}); db.add(rate); db.flush()
            if rate.next_check_at and utc(rate.next_check_at) > at: continue
            active = db.scalar(select(m.FixtureDiscoveryJob.id).where(m.FixtureDiscoveryJob.source_id == job.source_id,
                     m.FixtureDiscoveryJob.id != job.id, m.FixtureDiscoveryJob.status == 'RUNNING', m.FixtureDiscoveryJob.lease_until > at).limit(1))
            if active: continue
            if job.source_id==providers.OL_ID and job.request.get('shortcut'):
                league_rate_id='flr:'+job.source_id+':'+digest(job.request['shortcut'])[:16]
                league_rate=db.scalar(select(m.ProviderSyncState).where(m.ProviderSyncState.id==league_rate_id).with_for_update())
                if league_rate is None:
                    league_rate=m.ProviderSyncState(id=league_rate_id,source_id=job.source_id,payload={});db.add(league_rate);db.flush()
                if league_rate.next_check_at and utc(league_rate.next_check_at)>at:continue
                league_rate.next_check_at=at+timedelta(seconds=60)
            # Centralized source budget, independent of the number of dashboards/workers.
            rate.next_check_at = at + timedelta(seconds=3)
            if job.attempts >= 3:
                job.status = 'DEAD'; job.error = 'LEASE_RECOVERY_BUDGET_EXHAUSTED'; continue
            token = str(uuid4()); job.owner = token; job.attempts += 1; job.status = 'RUNNING'
            job.heartbeat_at = at; job.lease_until = at + timedelta(seconds=180)
            return {'id': job.id, 'owner': token, 'source_id': job.source_id, 'request': dict(job.request)}
    return None


def owned(db, ticket, at):
    job = db.scalar(select(m.FixtureDiscoveryJob).where(m.FixtureDiscoveryJob.id == ticket['id']).with_for_update())
    if job is None or job.owner != ticket['owner'] or job.status != 'RUNNING' or utc(job.lease_until) <= at:
        raise ValueError('WORKER_LEASE_LOST')
    if not authorized(db, job.source_id): raise PermissionError('SOURCE_NOT_AUTHORIZED')
    job.heartbeat_at = at; job.lease_until = at + timedelta(seconds=180)
    return job


def persist_fixture(db, job, raw, at):
    if not isinstance(raw, dict): raw = {'invalid_row': raw}
    source_id = job.source_id
    content_hash = digest(raw)
    identity = str(raw.get('matchID') if source_id == providers.OL_ID else raw.get('idEvent') or 'missing:' + content_hash)
    candidate = db.scalar(select(m.FixtureCandidate).where(m.FixtureCandidate.source_id == source_id,
                 m.FixtureCandidate.provider_fixture_id == identity, m.FixtureCandidate.content_hash == content_hash))
    duplicate = candidate is not None
    if candidate is None:
        # Ignore artwork; preserve the parser input relevant to fixture identity/status.
        safe = {k: v for k, v in raw.items() if not any(word in k.lower() for word in ('icon', 'badge', 'thumb', 'poster', 'fanart', 'banner', 'video'))}
        candidate = m.FixtureCandidate(source_id=source_id, job_id=job.id, provider_fixture_id=identity,
                      content_hash=content_hash, parser_version=providers.PARSER_VERSION, collected_at=at,
                      status='DISCOVERED', reasons=[], data={'raw': safe})
        db.add(candidate); db.flush()
    try:
        value = providers.fixture(source_id, raw, job.request)
        stamp = datetime.fromisoformat(value['kickoff_at']).astimezone(timezone.utc)
        if not isinstance(value['home'], str) or not isinstance(value['away'], str): raise ValueError('INVALID_PARTICIPANTS')
        home, away = value['home'].strip(), value['away'].strip()
        if not home or not away or not key(home) or not key(away) or len(home) > 200 or len(away) > 200 or key(home) == key(away): raise ValueError('INVALID_PARTICIPANTS')
        if identity in ('None', '', '0'): raise ValueError('PROVIDER_FIXTURE_ID_MISSING')
        if source_id == providers.OL_ID:
            profile = db.get(m.DiscoveryCompetition, job.request['profile_id'])
        else:
            if job.request.get('provider_key') and value['provider_key'] != job.request['provider_key']: raise ValueError('COMPETITION_MEMBERSHIP_MISMATCH')
            profile = register_competition(db, source_id, value['competition'], at)
        if profile is None: raise ValueError('COMPETITION_UNMAPPED')
        if stamp < at - timedelta(days=horizon()) or stamp > at + timedelta(days=horizon()):
            if not duplicate: candidate.status = 'OUT_OF_WINDOW'; candidate.reasons = ['OUTSIDE_COLLECTION_HORIZON']
            return 'OUT_OF_WINDOW'
        # Existing reviewed aliases align common English/German club spellings.
        from app.modules.autonomy.open_intelligence import canonical
        sport = db.get(m.Sport, db.get(m.Competition, profile.competition_id).sport_id)
        if sport.name == 'Football': home, away = canonical(home), canonical(away)
        value.update(home=home, away=away, kickoff_at=stamp.isoformat(), competition_id=profile.competition_id)
        signature = digest([profile.competition_id, key(home), key(away), stamp.isoformat(), value['status']])
        link = db.scalar(select(m.FixtureSourceMapping).where(m.FixtureSourceMapping.source_id == source_id, m.FixtureSourceMapping.provider_fixture_id == identity))
        fixture = db.get(m.Fixture, link.fixture_id) if link else db.scalar(select(m.Fixture).where(m.Fixture.competition_id == profile.competition_id,
                  m.Fixture.home_name == home, m.Fixture.away_name == away, m.Fixture.kickoff_at == stamp))
        if fixture is None:
            fixture = m.Fixture(competition_id=profile.competition_id, home_name=home, away_name=away, kickoff_at=stamp, status=value['status'])
            db.add(fixture); db.flush()
        if fixture.competition_id != profile.competition_id or key(fixture.home_name) != key(home) or key(fixture.away_name) != key(away): raise ValueError('PROVIDER_IDENTITY_CHANGED')
        candidate.status = 'EXTRACTED'; candidate.data = {**candidate.data, 'normalized': value}; candidate.fixture_id = fixture.id; candidate.reasons = []
        if link is None:
            link = m.FixtureSourceMapping(source_id=source_id, provider_fixture_id=identity, fixture_id=fixture.id,
                      candidate_id=candidate.id, job_id=job.id, signature=signature, last_seen_at=at, state='EXTRACTED')
            db.add(link); db.flush()
        else:
            link.candidate_id = candidate.id; link.job_id = job.id; link.signature = signature; link.last_seen_at = at
        peers = db.scalars(select(m.FixtureSourceMapping).join(m.Source, m.Source.id == m.FixtureSourceMapping.source_id).where(
                 m.FixtureSourceMapping.fixture_id == fixture.id, m.Source.enabled.is_(True), m.Source.permission == 'AUTHORIZED',
                 m.FixtureSourceMapping.last_seen_at >= at - timedelta(hours=24))).all()
        signatures = {p.signature for p in peers}
        state = 'CONFLICT' if len(signatures) > 1 else 'VERIFIED' if len({p.source_id for p in peers}) >= 2 else 'EXTRACTED'
        for peer in peers: peer.state = state
        if state != 'CONFLICT': fixture.kickoff_at = stamp; fixture.status = value['status']
        if profile.season_label != 'UNSPECIFIED':
            season = db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id == profile.competition_id, m.CompetitionSeason.label == profile.season_label))
            if season is None:
                season = m.CompetitionSeason(competition_id=profile.competition_id, label=profile.season_label, start_date=stamp.date(), end_date=stamp.date(), is_current=True)
                db.add(season); db.flush()
            else: season.start_date = min(season.start_date, stamp.date()); season.end_date = max(season.end_date, stamp.date())
            profile.season_id = season.id; fixture.season_id = season.id
        for name in (home, away):
            from app.modules.pipeline.operations import canonical_key
            team_key = canonical_key(name)
            team = db.scalar(select(m.Team).where(m.Team.sport_id == sport.id, m.Team.canonical_key == team_key))
            if team is None: team = m.Team(sport_id=sport.id, name=name, canonical_key=team_key); db.add(team); db.flush()
            if name == home: fixture.home_team_id = team.id
            else: fixture.away_team_id = team.id
            from app.modules.autonomy.membership import observe
            observe(db,team,fixture,profile)
        observation_hash = digest(['fixture-discovery', source_id, identity, content_hash])
        if db.scalar(select(m.Observation.id).where(m.Observation.source_id == source_id, m.Observation.content_hash == observation_hash)) is None:
            db.add(m.Observation(source_id=source_id, fixture_id=fixture.id, source_url=value['source_url'], content_hash=observation_hash,
                observed_at=at, payload={'section': 'fixture_identity', 'source_reference': identity, 'parser_version': providers.PARSER_VERSION,
                'data': value, 'discovery_candidate_id': candidate.id, 'verification': state}))
        return 'DUPLICATE' if duplicate else state
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        if duplicate: return candidate.status
        candidate.status = 'REJECTED'; candidate.reasons = [str(exc)[:300]]
        return 'REJECTED'


def execute(factory, ticket, fetcher=providers.fetch, at=None):
    fixed_at = at
    clock = lambda: fixed_at if fixed_at is not None else now()
    at = clock()
    try:
        payload = fetcher(ticket['source_id'], ticket['request'])
        records = providers.rows(ticket['source_id'], ticket['request'], payload)
        result = {'received': len(records), 'counts': {}, 'response_sha256': digest(payload), 'parser_version': providers.PARSER_VERSION,
                  'coverage_complete': False, 'limitation': 'Community coverage; not an official completeness guarantee' if ticket['source_id'] == providers.OL_ID else 'API tier may truncate results; no undocumented pagination is attempted'}
        for raw in records:
            with factory.begin() as db:
                job = owned(db, ticket, clock())
                if job.kind in ('catalogue','league'):
                    try:
                        value = providers.competition(job.source_id, raw)
                        if value: register_competition(db, job.source_id, value, at)
                        state = 'DISCOVERED' if value else 'UNSUPPORTED_SPORT'
                    except (ValueError,KeyError,TypeError,AttributeError) as exc:
                        state='REJECTED_COMPETITION'
                        result.setdefault('catalogue_rejections',[]).append({'record_hash':digest(raw),'reason':str(exc)[:200]})
                else:
                    state = persist_fixture(db, job, raw, at)
                result['counts'][state] = result['counts'].get(state, 0) + 1
        with factory.begin() as db:
            job = owned(db, ticket, clock())
            if job.source_id==providers.OL_ID and job.kind=='fixtures':
                timings=[]
                for raw in records:
                    try:
                        stamp=datetime.fromisoformat(raw['matchDateTimeUTC'].replace('Z','+00:00'));group=raw.get('group',{}).get('groupOrderID')
                        if stamp.tzinfo and type(group) is int:timings.append((abs((stamp-at).total_seconds()),group))
                    except (ValueError,TypeError,KeyError,AttributeError):pass
                profile=db.get(m.DiscoveryCompetition,job.request['profile_id'])
                if timings:profile.details={**profile.details,'poll_group':min(timings)[1]}
                if job.request['shortcut'] == 'bl1':
                    from app.modules.autonomy.community_tables import cache_discovery_table
                    try:
                        if profile is None or profile.source_id != job.source_id or profile.provider_key != 'bl1' or profile.details.get('provider_season', profile.season_label) != job.request['season']:
                            raise ValueError('STANDINGS_PROFILE_MISMATCH')
                        result['table_status'] = cache_discovery_table(db, profile, records, at)
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        result['table_status'] = 'REJECTED'
                        result['table_error'] = (str(exc) or type(exc).__name__)[:200]
                        if profile and profile.source_id == job.source_id and profile.provider_key == 'bl1':
                            cache_id = 'openligadb:bl1:' + job.request['season']
                            cache = db.get(m.ProviderSyncState, cache_id)
                            if cache is None:
                                cache = m.ProviderSyncState(id=cache_id, source_id=job.source_id, payload={}, failures=0)
                                db.add(cache)
                            cache.failures = (cache.failures or 0) + 1
                            cache.next_check_at = None
                            cache.payload = {**cache.payload, 'competition_id': profile.competition_id,
                                             'table_error': result['table_error']}
            if job.kind=='poll':
                profile=db.get(m.DiscoveryCompetition,job.request['profile_id'])
                changed=profile.details.get('change_marker')!=payload
                result['change_detected']=changed
                if changed:
                    request={**job.request,'kind':'fixtures','change_marker':digest(payload)};request.pop('group',None)
                    enqueue(db,job.source_id,request,at+timedelta(seconds=60),priority=20)
                profile.details={**profile.details,'change_marker':payload}
            job.status = 'COMPLETED'; job.result = {**result,'failures':job.result.get('failures',[])}
            job.finished_at = at; job.owner = None; job.lease_until = None
            job.error = 'STANDINGS:' + result['table_error'] if result.get('table_error') else 'CATALOGUE_REJECTIONS:'+str(result['counts']['REJECTED_COMPETITION']) if result['counts'].get('REJECTED_COMPETITION') else None
            db.add(m.AuditEvent(actor='fixture-discovery-worker', action='fixture_discovery.completed', correlation_id=job.id, payload=result))
        return result
    except Exception as exc:
        with factory.begin() as db:
            job = db.get(m.FixtureDiscoveryJob, ticket['id'])
            if job is None or job.owner != ticket['owner']: return {'error': 'WORKER_LEASE_LOST'}
            job.status = 'BLOCKED' if isinstance(exc, PermissionError) or str(exc)=='PRODUCTION_CREDENTIAL_REQUIRED' else 'DEAD' if job.attempts >= 3 else 'RETRY_SCHEDULED'
            job.error = str(exc)[:300] if isinstance(exc, (ValueError, PermissionError)) else type(exc).__name__
            if isinstance(exc, IntegrityError):
                diagnostic = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
                job.error += ':' + str(diagnostic or 'DATABASE_CONSTRAINT')
            job.result={**job.result,'failures':[*job.result.get('failures',[]),{'at':at.isoformat(),'attempt':job.attempts,'error':job.error}]}
            job.owner = None; job.lease_until = None; job.finished_at = at
            job.next_run_at = at + timedelta(seconds=max(60 * 2 ** job.attempts, getattr(exc, 'retry_after', 0)))
            if job.status in ('DEAD', 'BLOCKED'):
                message = 'FIXTURE_DISCOVERY:' + job.source_id + ':' + job.error
                if not db.scalar(select(m.Incident.id).where(m.Incident.message == message, m.Incident.status == 'OPEN')):
                    db.add(m.Incident(severity='HIGH', status='OPEN', message=message))
            return {'error': job.error, 'status': job.status}


def collect(factory, fetcher=providers.fetch, at=None):
    if not enabled(): return {'enabled': False, 'errors': []}
    clock = lambda: at if at is not None else now()
    with factory.begin() as db: plan(db, clock())
    report = {'enabled': True, 'executed_jobs': [], 'errors': []}
    for _ in range(max(1,min(8,int(os.getenv('SPORTS_FIXTURE_JOBS_PER_CYCLE', '4'))))):
        ticket = claim(factory, clock())
        if ticket is None: break
        result = execute(factory, ticket, fetcher, at)
        report['executed_jobs'].append({'id': ticket['id'], 'source_id': ticket['source_id'], **result})
        if result.get('error'): report['errors'].append({'job_id': ticket['id'], 'code': result['error']})
    return report
