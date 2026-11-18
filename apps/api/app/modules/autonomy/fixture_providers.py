"""Documented, permission-scoped fixture adapters. No website scraping or images."""
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from uuid import uuid5, NAMESPACE_URL
from app.modules.acquisition.jobs import validate_feed_url
from app.modules.autonomy import openligadb

SPORTSDB_ID = str(uuid5(NAMESPACE_URL, 'https://www.thesportsdb.com/'))
OL_ID = openligadb.SOURCE_ID
PARSER_VERSION = 'fixture-discovery-v1'
SPORTSDB_SPORTS = {
    'Basketball': 'Basketball',
    'Soccer': 'Football',
    'Ice Hockey': 'Ice Hockey',
    'Tennis': 'Tennis',
    'Table Tennis': 'Table Tennis',
}


class ProviderError(ValueError):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.retry_after = retry_after


def sportsdb_key():
    key = os.getenv('SPORTS_THESPORTSDB_KEY', '123')
    if os.getenv('SPORTS_DEPLOYMENT_ENV', 'development') == 'production' and key == '123':
        raise ProviderError('PRODUCTION_CREDENTIAL_REQUIRED')
    if not key or not all(c.isalnum() or c in '_-' for c in key): raise ProviderError('INVALID_CREDENTIAL_CONFIGURATION')
    return key


def request_url(provider, request):
    if provider == OL_ID:
        if request['kind'] == 'catalogue': return openligadb.BASE + '/getavailableleagues/' + str(request['season'])
        if request['kind'] == 'poll': return openligadb.BASE + '/getlastchangedate/' + quote(request['shortcut'],safe='') + '/' + quote(request['season'],safe='') + '/' + str(request['group'])
        return openligadb.BASE + '/getmatchdata/' + quote(request['shortcut'], safe='') + '/' + quote(request['season'], safe='')
    methods = {'catalogue': 'all_leagues.php', 'day': 'eventsday.php', 'fixtures': 'eventsnextleague.php', 'league': 'lookupleague.php'}
    method = methods[request['kind']]
    params = {'day': {'d': request.get('date'), 's': request.get('sport')},
              'fixtures': {'id': request.get('provider_key')}, 'league': {'id': request.get('provider_key')}}.get(request['kind'], {})
    return 'https://www.thesportsdb.com/api/v1/json/' + sportsdb_key() + '/' + method + ('?' + urlencode(params) if params else '')


def fetch(provider, request):
    import httpx
    url = request_url(provider, request)
    validate_feed_url(url)
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False,
                      headers={'User-Agent': os.getenv('SPORTS_OPENLIGADB_USER_AGENT', 'CACSMS-Sports/1.0 (centralized local research)'), 'Accept': 'application/json'}) as client:
        with client.stream('GET', url) as response:
            if response.status_code != 200:
                retry = response.headers.get('retry-after', '')
                raise ProviderError('HTTP_' + str(response.status_code), min(int(retry), 86400) if retry.isdigit() else 0)
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 4_000_000: raise ProviderError('RESPONSE_TOO_LARGE')
    try: return json.loads(body)
    except (ValueError, UnicodeError) as exc: raise ProviderError('INVALID_JSON_RESPONSE') from exc


def rows(provider, request, payload):
    if provider == OL_ID:
        if request['kind']=='poll':
            if not isinstance(payload,str):raise ProviderError('INVALID_CHANGE_MARKER')
            return []
        if not isinstance(payload, list) or len(payload) > 10000: raise ProviderError('PARSER_SCHEMA_MISMATCH')
        return payload
    key = 'leagues' if request['kind'] in ('catalogue', 'league') else 'events'
    if not isinstance(payload, dict) or key not in payload: raise ProviderError('PARSER_SCHEMA_MISMATCH')
    result = payload[key]
    if result is None: return []
    if not isinstance(result, list) or len(result) > 10000: raise ProviderError('PARSER_SCHEMA_MISMATCH')
    return result


def competition(provider, raw, season='UNSPECIFIED'):
    if provider == OL_ID:
        sport_id = (raw.get('sport') or {}).get('sportId')
        sport = 'Football' if sport_id in (1, 79) else 'Basketball' if 'basket' in str(raw.get('sport', '')).casefold() else None
        if sport is None: return None
        key = str(raw['leagueShortcut']).strip()
        country = 'Germany' if key in ('bl1', 'bl2', 'bl3') else None
        name = {'bl1': 'Bundesliga', 'bl2': '2. Bundesliga', 'bl3': '3. Liga'}.get(key, str(raw['leagueName']).strip())
        return {'provider_key': key, 'name': name, 'sport': sport, 'country': country,
                'season': str(raw['leagueSeason']), 'details': {'provider_league_id': raw.get('leagueId'),'provider_name':raw['leagueName'], 'shortcut': key, 'community': True,'division':{'bl1':1,'bl2':2,'bl3':3}.get(key)}}
    sport = raw.get('strSport')
    if sport not in SPORTSDB_SPORTS: return None
    return {'provider_key': str(raw['idLeague']), 'name': str(raw['strLeague']).strip(),
            'sport': SPORTSDB_SPORTS[sport], 'country': raw.get('strCountry') if 'strCurrentSeason' in raw else None,
            'season': str(raw.get('strCurrentSeason') or season),
            'details': {'division': raw.get('intDivision'), 'provider_name': raw['strLeague'],
                        'coverage': 'LIMITED_DEVELOPMENT_API' if sportsdb_key() == '123' else 'SUBSCRIPTION_DEPENDENT'}}


def fixture(provider, raw, request):
    """Source-specific UTC semantics. An absent event time is never replaced by midnight."""
    if provider == OL_ID:
        stamp = datetime.fromisoformat(raw['matchDateTimeUTC'].replace('Z', '+00:00'))
        if stamp.tzinfo is None: raise ProviderError('UTC_TIMEZONE_MISSING')
        home, away = raw['team1']['teamName'], raw['team2']['teamName']
        league = {'provider_key': request['shortcut'], 'season': request['season']}
        identity = str(raw['matchID'])
        return {'provider_fixture_id': identity, **league, 'home': home, 'away': away, 'kickoff_at': stamp.isoformat(),
                'status': 'FINISHED' if raw.get('matchIsFinished') is True else 'SCHEDULED',
                'venue': (raw.get('location') or {}).get('locationStadium'), 'group': (raw.get('group') or {}).get('groupName'),
                'home_provider_id': raw['team1'].get('teamId'), 'away_provider_id': raw['team2'].get('teamId'),
                'source_url': openligadb.BASE + '/getmatchdata/' + identity}
    identity = str(raw['idEvent'])
    value = raw.get('strTimestamp')
    if not value:
        if not raw.get('dateEvent') or not raw.get('strTime'): raise ProviderError('KICKOFF_TIME_UNAVAILABLE')
        value = raw['dateEvent'] + 'T' + raw['strTime']
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # The documented V1 provider timezone is UTC, including timestamps without an offset.
    if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
    state = str(raw.get('strStatus') or '').strip().upper()
    postponed = str(raw.get('strPostponed', '')).lower() == 'yes'
    if not state and not postponed and raw.get('strSport') in ('Ice Hockey', 'Tennis', 'Table Tennis'):
        raise ProviderError('FIXTURE_STATUS_UNAVAILABLE')
    status = {'NS': 'SCHEDULED', 'NOT STARTED': 'SCHEDULED', 'TBD': 'SCHEDULED', '': 'SCHEDULED',
              'FT': 'FINISHED', 'AET': 'FINISHED', 'AP': 'FINISHED', 'MATCH FINISHED': 'FINISHED',
              'CANC': 'CANCELLED', 'CANCELLED': 'CANCELLED', 'CANCELED': 'CANCELLED',
              'POST': 'POSTPONED', 'PST': 'POSTPONED', 'POSTPONED': 'POSTPONED',
              '1H': 'LIVE', '2H': 'LIVE', 'HT': 'LIVE', 'LIVE': 'LIVE', 'IN PLAY': 'LIVE',
              'Q1': 'LIVE', 'Q2': 'LIVE', 'Q3': 'LIVE', 'Q4': 'LIVE', 'OT': 'LIVE', 'BT': 'LIVE'}.get(state)
    if raw.get('strSport') == 'Ice Hockey':
        status = {'P1': 'LIVE', 'P2': 'LIVE', 'P3': 'LIVE', 'PT': 'LIVE', 'AOT': 'FINISHED'}.get(state, status)
    if postponed: status = 'POSTPONED'
    if status is None: raise ProviderError('UNSUPPORTED_FIXTURE_STATUS:' + state[:40])
    profile = competition(provider, raw, raw.get('strSeason') or 'UNSPECIFIED')
    if profile is None: raise ProviderError('UNSUPPORTED_SPORT')
    return {'provider_fixture_id': identity, 'provider_key': str(raw['idLeague']), 'season': str(raw.get('strSeason') or 'UNSPECIFIED'),
            'competition': profile, 'home': raw['strHomeTeam'], 'away': raw['strAwayTeam'], 'kickoff_at': stamp.isoformat(),
            'status': status, 'venue': raw.get('strVenue'), 'group': raw.get('strGroup'),
            'home_provider_id': raw.get('idHomeTeam'), 'away_provider_id': raw.get('idAwayTeam'),
            'source_url': 'https://www.thesportsdb.com/documentation'}
