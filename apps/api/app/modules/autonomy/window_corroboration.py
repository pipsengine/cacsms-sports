"""Multi-provider corroboration of complete league result windows (beyond the Bundesliga).

Each provider's *complete* league-season results are cached separately. For an upcoming fixture,
each provider computes form, scoring rates and head-to-head on its own; observations are emitted for
both providers only when the two computations are identical, so the research quorum can verify them.
A provider that is behind, missing a match or disagreeing on a score yields no evidence (never a
blend). Team names are resolved conservatively per league and the resolution is auditable.

Providers (any two whose computations are identical verify a section):
- football-data.org (documented API v4; requires SPORTS_FOOTBALL_DATA_ORG_KEY; free tier covers the top leagues).
- API-Football (documented API; requires SPORTS_APIFOOTBALL_KEY; plan must cover the season).
- TheSportsDB with a PAID key only (the public development key truncates seasons, so it is never used here).
- BetExplorer (results pages). Its terms prohibit automated access without express written consent,
  so it stays PROHIBITED and every request is refused by acquisition.source_policy until the consent
  reference is recorded as SPORTS_SOURCE_CONSENT=betexplorer.com=<reference>. When enabled it obeys
  robots.txt, fetches one results page per league season at most every 6 hours, and spaces requests.
"""
import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from uuid import uuid5, NAMESPACE_URL

from sqlalchemy import select
from app.db import models as m
from app.modules.acquisition import source_policy
from app.modules.research.league import utc

PRODUCER = 'window-corroboration-v1'
SECTIONS = ('recent_form', 'match_statistics', 'head_to_head')
APIF_ID = str(uuid5(NAMESPACE_URL, 'https://www.api-football.com/'))
APIF_NAME = 'API-Football (documented API)'
APIF_BASE = 'https://v3.football.api-sports.io'
BE_ID = source_policy.source_id_for('betexplorer.com')
BE_NAME = source_policy.PROHIBITED['betexplorer.com']['name']
BE_BASE = 'https://www.betexplorer.com'
FDORG_ID = str(uuid5(NAMESPACE_URL, 'https://www.football-data.org/'))
FDORG_NAME = 'football-data.org (documented API)'
FDORG_BASE = 'https://api.football-data.org/v4'
from app.modules.autonomy.fixture_providers import SPORTSDB_ID as TSDB_ID  # noqa: E402  (registered by fixture discovery)
GROUPS = {FDORG_ID: 'football-data-org', APIF_ID: 'api-football', TSDB_ID: 'thesportsdb', BE_ID: 'betexplorer'}
# Provider name -> source id, in preference order (providers with kickoff timestamps first).
IDS = {'footballdata': FDORG_ID, 'apifootball': APIF_ID, 'thesportsdb': TSDB_ID, 'betexplorer': BE_ID}
LABELS = {'footballdata': 'football-data.org', 'apifootball': 'API-Football', 'thesportsdb': 'TheSportsDB (paid key)', 'betexplorer': 'BetExplorer'}
TIMESTAMPED = ('footballdata', 'apifootball', 'thesportsdb')
# Centralised spacing between requests to one provider (football-data.org free tier: 10 requests/minute).
SPACING = {'footballdata': timedelta(seconds=7), 'apifootball': timedelta(seconds=1), 'thesportsdb': timedelta(seconds=2),
           'betexplorer': timedelta(seconds=30)}
CURRENT_REFRESH = timedelta(hours=6)
PREVIOUS_REFRESH = timedelta(days=7)
MAX_DATA_AGE = timedelta(hours=12)
USER_AGENT = 'CACSMS-Sports/1.0 (league results research; low-frequency)'

# Competition (casefolded name, country or None) -> provider identities. 'calendar' leagues use one-year seasons.
# Wrong identities are safe: unmatched teams or differing results produce no evidence.
_EPL = {'footballdata': 'PL', 'apifootball': 39, 'thesportsdb': 4328, 'betexplorer': 'football/england/premier-league'}
_LALIGA = {'footballdata': 'PD', 'apifootball': 140, 'thesportsdb': 4335, 'betexplorer': 'football/spain/laliga'}
_ERE = {'footballdata': 'DED', 'apifootball': 88, 'thesportsdb': 4337, 'betexplorer': 'football/netherlands/eredivisie'}
_PPL = {'footballdata': 'PPL', 'apifootball': 94, 'thesportsdb': 4344, 'betexplorer': 'football/portugal/liga-portugal'}
LEAGUES = {
    ('belgian pro league', 'belgium'): {'apifootball': 144, 'thesportsdb': 4338, 'betexplorer': 'football/belgium/jupiler-pro-league'},
    ('premier league', 'england'): _EPL, ('english premier league', 'england'): _EPL,
    ('english league championship', 'england'): {'footballdata': 'ELC', 'apifootball': 40, 'thesportsdb': 4329, 'betexplorer': 'football/england/championship'},
    ('la liga', 'spain'): _LALIGA, ('laliga ea sports', 'spain'): _LALIGA,
    ('serie a', 'italy'): {'footballdata': 'SA', 'apifootball': 135, 'thesportsdb': 4332, 'betexplorer': 'football/italy/serie-a'},
    ('ligue 1', 'france'): {'footballdata': 'FL1', 'apifootball': 61, 'thesportsdb': 4334, 'betexplorer': 'football/france/ligue-1'},
    ('eredivisie', 'netherlands'): _ERE, ('dutch eredivisie', 'the netherlands'): _ERE,
    ('primeira liga', 'portugal'): _PPL, ('portuguese primeira liga', 'portugal'): _PPL,
    ('scottish premier league', 'scotland'): {'apifootball': 179, 'thesportsdb': 4330, 'betexplorer': 'football/scotland/premiership'},
    ('greek super league 1', 'greece'): {'apifootball': 197, 'thesportsdb': 4336, 'betexplorer': 'football/greece/super-league'},
    ('swedish allsvenskan', 'sweden'): {'apifootball': 113, 'thesportsdb': 4347, 'betexplorer': 'football/sweden/allsvenskan', 'calendar': True},
    ('norwegian eliteserien', 'norway'): {'apifootball': 103, 'thesportsdb': 4358, 'betexplorer': 'football/norway/eliteserien', 'calendar': True},
    ('brazilian serie a', 'brazil'): {'footballdata': 'BSA', 'apifootball': 71, 'thesportsdb': 4351, 'betexplorer': 'football/brazil/serie-a-betano', 'calendar': True},
}
LEGAL_TOKENS = {'fc', 'afc', 'cf', 'sc', 'kv', 'kvc', 'krc', 'kaa', 'rsc', 'ksv', 'sv', 'fk', 'sk', 'bk', 'ac',
                'cd', 'ud', 'ssc', 'sad', 'if', 'ff', 'aik', 'ec', 'se'}


class ProviderError(ValueError):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.retry_after = retry_after


def _seconds(value, default=0):
    try: return max(0, min(3600, int(str(value).strip())))
    except (TypeError, ValueError): return default


def now(): return datetime.now(timezone.utc)
def enabled(): return os.getenv('SPORTS_WINDOW_CORROBORATION_ENABLED', '1').lower() not in ('0', 'false', 'no')
def apifootball_key(): return os.getenv('SPORTS_APIFOOTBALL_KEY', '').strip()
def footballdata_key(): return os.getenv('SPORTS_FOOTBALL_DATA_ORG_KEY', '').strip()


def sportsdb_premium_key():
    """TheSportsDB key only when it is a paid one; the public development key truncates seasons."""
    try:
        from app.modules.autonomy.fixture_providers import sportsdb_key
        key = sportsdb_key()
    except ValueError:
        return None
    return key if key and key != '123' else None
def betexplorer_consent(): return source_policy.consents().get('betexplorer.com')
def _hash(*parts): return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()
def fold(text): return ''.join(c for c in unicodedata.normalize('NFKD', str(text or '')) if not unicodedata.combining(c)).casefold().strip()


def leagues():
    table = dict(LEAGUES)
    try: extra = json.loads(os.getenv('SPORTS_CORROBORATION_LEAGUES_JSON') or '{}')
    except ValueError: extra = {}
    # {"Competition name|Country": {"apifootball": 144, "betexplorer": "football/x/y", "calendar": false}}
    for label, entry in (extra.items() if isinstance(extra, dict) else ()):
        name, _, country = str(label).partition('|')
        if isinstance(entry, dict): table[(fold(name), fold(country) or None)] = entry
    return table


def league_name(name):
    """Competition name without a trailing season or qualifier, e.g. 'Premier League 2026/2027' -> 'premier league'."""
    return re.sub(r'\s+\d{4}(?:\s*[/-]\s*\d{2,4})?(?:\s*\([^)]*\))?$', '', fold(name)).strip()


def league_for(competition):
    if competition is None: return None
    table = leagues()
    country = fold(competition.country) or None
    for name in dict.fromkeys((fold(competition.name), league_name(competition.name))):
        entry = table.get((name, country)) or (table.get((name, None)) if not country else None)
        if entry: return entry
    return None


def season_of(at, calendar):
    return at.year if calendar or at.month >= 7 else at.year - 1


# Sources ---------------------------------------------------------------------------------

def ensure_sources(db):
    """Register keyed API providers when their key is configured; enable BetExplorer only with recorded consent."""
    changed = []
    for sid, name, key, env, terms, label in (
            (APIF_ID, APIF_NAME, apifootball_key(), 'SPORTS_APIFOOTBALL_KEY', 'https://www.api-football.com/terms', 'api-football'),
            (FDORG_ID, FDORG_NAME, footballdata_key(), 'SPORTS_FOOTBALL_DATA_ORG_KEY', 'https://www.football-data.org/terms', 'football-data-org')):
        source = db.get(m.Source, sid)
        if key:
            if source is None:
                db.add(m.Source(id=sid, name=name, permission='AUTHORIZED', enabled=True)); db.flush()
                db.add(m.AuditEvent(actor='window-corroboration', action='source.fixture_adapter_registered', correlation_id=sid,
                                    payload={'terms_url': terms, 'permission_scope': 'Configured API key; coverage depends on plan',
                                             'independence_group': GROUPS[sid], 'checked_at': '2026-11-19'}))
                changed.append(label)
            elif not source.enabled and source.permission == 'AUTHORIZED':
                source.enabled = True; changed.append(label + '-re-enabled')
        elif source is not None and source.enabled and source.permission == 'AUTHORIZED':
            source.enabled = False
            db.add(m.AuditEvent(actor='window-corroboration', action='source.disabled', correlation_id=sid,
                                payload={'reason': env + ' is not configured'}))
            changed.append(label + '-disabled')
    consent = betexplorer_consent()
    if consent:
        source = db.get(m.Source, BE_ID) or db.scalar(select(m.Source).where(m.Source.name == BE_NAME))
        if source is None:
            source = m.Source(id=BE_ID, name=BE_NAME, permission='AUTHORIZED', enabled=True); db.add(source); db.flush()
        elif source.permission == 'AUTHORIZED' and source.enabled:
            return changed
        source.permission = 'AUTHORIZED'; source.enabled = True
        db.add(m.AuditEvent(actor='window-corroboration', action='source.consent_recorded', correlation_id=source.id,
                            payload={'domain': 'betexplorer.com', 'consent_reference': consent,
                                     'terms_url': source_policy.PROHIBITED['betexplorer.com']['terms_url'],
                                     'scope': 'League results pages only; robots.txt obeyed; low-frequency'}))
        changed.append('betexplorer')
    db.flush()
    return changed


def authorized(db, source_id):
    source = db.get(m.Source, source_id)
    return bool(source and source.enabled and source.permission == 'AUTHORIZED')


def provider_enabled(db, name):
    if not authorized(db, IDS[name]): return False
    return name != 'thesportsdb' or bool(sportsdb_premium_key())


def registry(db):
    """Quorum policy entries for enabled corroboration providers (used by the research stage)."""
    return {IDS[name]: {'reviewed': True, 'independence_group': GROUPS[IDS[name]], 'sections': list(SECTIONS), 'producer': PRODUCER}
            for name in IDS if provider_enabled(db, name)}


# HTTP -------------------------------------------------------------------------------------

def _get(url, headers=None, limit=4_000_000, capture=None):
    """GET with policy checks. `capture` (a dict) receives the response headers, e.g. provider rate-limit counters."""
    import httpx
    from app.modules.acquisition.jobs import validate_feed_url
    source_policy.assert_permitted(url)
    validate_feed_url(url)
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False,
                      headers={'User-Agent': USER_AGENT, **(headers or {})}) as client:
        with client.stream('GET', url) as response:
            if capture is not None: capture.update({k.lower(): v for k, v in response.headers.items()})
            if response.status_code != 200:
                wait = _seconds(response.headers.get('x-requestcounter-reset') or response.headers.get('retry-after'))
                raise ProviderError('HTTP_' + str(response.status_code), wait)
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit: raise ProviderError('RESPONSE_TOO_LARGE')
    return bytes(body)


def apifootball_url(league, season): return f'{APIF_BASE}/fixtures?league={int(league)}&season={int(season)}'


def fetch_apifootball(league, season):
    key = apifootball_key()
    if not key or not all(c.isalnum() for c in key): raise ProviderError('INVALID_CREDENTIAL_CONFIGURATION')
    try: return json.loads(_get(apifootball_url(league, season), {'x-apisports-key': key, 'Accept': 'application/json'}))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ProviderError): raise
        raise ProviderError('INVALID_JSON_RESPONSE') from exc


def footballdata_url(code, season):
    if not re.fullmatch(r'[A-Z0-9]{2,5}', str(code)): raise ProviderError('INVALID_COMPETITION_CODE')
    return f'{FDORG_BASE}/competitions/{code}/matches?season={int(season)}'


def fetch_footballdata(code, season):
    """One competition season. The provider's counters (X-Requests-Available-Minute, X-RequestCounter-Reset) are
    returned under '_throttle' so the scheduler waits for the reset instead of hitting the rate limiter."""
    key = footballdata_key()
    if not key or not all(c.isalnum() for c in key): raise ProviderError('INVALID_CREDENTIAL_CONFIGURATION')
    headers = {}
    try: payload = json.loads(_get(footballdata_url(code, season), {'X-Auth-Token': key, 'Accept': 'application/json'}, capture=headers))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ProviderError): raise
        raise ProviderError('INVALID_JSON_RESPONSE') from exc
    if isinstance(payload, dict):
        payload['_throttle'] = {'available': _seconds(headers.get('x-requests-available-minute'), None),
                                'reset': _seconds(headers.get('x-requestcounter-reset'), 60)}
    return payload


def throttle_wait(payload):
    """Seconds to pause a provider after a successful response, from its own rate-limit counters."""
    info = payload.get('_throttle') if isinstance(payload, dict) else None
    if not isinstance(info, dict) or info.get('available') is None: return 0
    return info['reset'] if info['available'] <= 1 else 0


def sportsdb_season(season, calendar): return str(season) if calendar else f'{season}-{season + 1}'


def sportsdb_reference_url(league, season, calendar):
    # Observations never carry the credential, which TheSportsDB places in the request path.
    return f'https://www.thesportsdb.com/league/{int(league)}?season={sportsdb_season(season, calendar)}'


def fetch_thesportsdb(league, season_label):
    key = sportsdb_premium_key()
    if not key: raise ProviderError('PAID_THESPORTSDB_KEY_REQUIRED')
    if not re.fullmatch(r'\d{4}(?:-\d{4})?', season_label): raise ProviderError('INVALID_SEASON')
    url = f'https://www.thesportsdb.com/api/v1/json/{key}/eventsseason.php?id={int(league)}&s={season_label}'
    try: return json.loads(_get(url, {'Accept': 'application/json'}))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ProviderError): raise
        raise ProviderError('INVALID_JSON_RESPONSE') from exc


def betexplorer_url(path, season, calendar, current):
    if not re.fullmatch(r'[a-z0-9-]+(?:/[a-z0-9-]+){2}', path or ''): raise ProviderError('INVALID_BETEXPLORER_PATH')
    suffix = '' if current else (f'-{season}' if calendar else f'-{season}-{season + 1}')
    return f'{BE_BASE}/{path}{suffix}/results/'


def fetch_betexplorer(url):
    """One results page, only when robots.txt allows it for this user agent."""
    from urllib.robotparser import RobotFileParser
    robots = RobotFileParser()
    robots.parse(_get(BE_BASE + '/robots.txt', limit=500_000).decode('utf-8', 'replace').splitlines())
    if not robots.can_fetch(USER_AGENT, url): raise PermissionError('ROBOTS_DISALLOWED')
    return _get(url, {'Accept': 'text/html'}).decode('utf-8', 'replace')


# Parsers (pure) ---------------------------------------------------------------------------

def parse_apifootball(payload, season, at):
    """Finished regulation-time league results; any provider error or paging rejects the whole response."""
    if not isinstance(payload, dict) or not isinstance(payload.get('response'), list): raise ProviderError('PARSER_SCHEMA_MISMATCH')
    errors = payload.get('errors')
    if errors: raise ProviderError('PROVIDER_ERROR:' + json.dumps(errors, sort_keys=True)[:200])
    paging = payload.get('paging') or {}
    if isinstance(paging, dict) and isinstance(paging.get('total'), int) and paging['total'] > 1: raise ProviderError('INCOMPLETE_PAGING')
    rows, seen = [], set()
    for item in payload['response']:
        fixture, teams, score = item.get('fixture') or {}, item.get('teams') or {}, (item.get('score') or {}).get('fulltime') or {}
        if (fixture.get('status') or {}).get('short') != 'FT': continue
        identity = fixture.get('id')
        home, away = (teams.get('home') or {}).get('name'), (teams.get('away') or {}).get('name')
        hg, ag = score.get('home'), score.get('away')
        stamp = datetime.fromisoformat(str(fixture.get('date')).replace('Z', '+00:00'))
        if (type(identity) is not int or identity in seen or not isinstance(home, str) or not isinstance(away, str)
                or not home.strip() or fold(home) == fold(away) or type(hg) is not int or type(ag) is not int
                or min(hg, ag) < 0 or stamp.tzinfo is None or utc(stamp) >= at):
            raise ProviderError('INVALID_RESULT_ROW')
        seen.add(identity)
        rows.append({'season': season, 'date': utc(stamp).date().isoformat(), 'kickoff': utc(stamp).isoformat(),
                     'home': home.strip(), 'away': away.strip(), 'hg': hg, 'ag': ag, 'finished': True})
    return rows


def parse_footballdata(payload, season, at):
    """football-data.org v4 matches: FINISHED, regulation-duration results only; a malformed finished row rejects all."""
    if not isinstance(payload, dict) or not isinstance(payload.get('matches'), list): raise ProviderError('PARSER_SCHEMA_MISMATCH')
    rows, seen = [], set()
    for item in payload['matches']:
        if not isinstance(item, dict) or item.get('status') != 'FINISHED': continue
        score = item.get('score') or {}
        if score.get('duration', 'REGULAR') != 'REGULAR': continue
        full = score.get('fullTime') or {}
        identity, hg, ag = item.get('id'), full.get('home'), full.get('away')
        home, away = (item.get('homeTeam') or {}).get('name'), (item.get('awayTeam') or {}).get('name')
        stamp = datetime.fromisoformat(str(item.get('utcDate')).replace('Z', '+00:00'))
        if (type(identity) is not int or identity in seen or not isinstance(home, str) or not isinstance(away, str)
                or not home.strip() or fold(home) == fold(away) or type(hg) is not int or type(ag) is not int
                or min(hg, ag) < 0 or stamp.tzinfo is None or utc(stamp) >= at):
            raise ProviderError('INVALID_RESULT_ROW')
        seen.add(identity)
        rows.append({'season': season, 'date': utc(stamp).date().isoformat(), 'kickoff': utc(stamp).isoformat(),
                     'home': home.strip(), 'away': away.strip(), 'hg': hg, 'ag': ag, 'finished': True})
    return rows


def parse_thesportsdb(payload, season, at):
    """TheSportsDB eventsseason (paid key): finished, non-postponed events with integer scores."""
    if not isinstance(payload, dict) or 'events' not in payload: raise ProviderError('PARSER_SCHEMA_MISMATCH')
    events = payload['events'] or []
    if not isinstance(events, list): raise ProviderError('PARSER_SCHEMA_MISMATCH')
    rows, seen = [], set()
    for item in events:
        if not isinstance(item, dict): raise ProviderError('INVALID_RESULT_ROW')
        if str(item.get('strStatus') or '').upper() not in ('FT', 'MATCH FINISHED') or str(item.get('strPostponed') or '').lower() == 'yes': continue
        identity, home, away = str(item.get('idEvent') or ''), item.get('strHomeTeam'), item.get('strAwayTeam')
        scores = (item.get('intHomeScore'), item.get('intAwayScore'))
        stamp = datetime.fromisoformat(str(item.get('strTimestamp')).replace('Z', '+00:00'))
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        if (not identity.isdigit() or identity in seen or not isinstance(home, str) or not isinstance(away, str) or not home.strip()
                or fold(home) == fold(away) or any(isinstance(v, bool) or not str(v).isdigit() for v in scores) or utc(stamp) >= at):
            raise ProviderError('INVALID_RESULT_ROW')
        seen.add(identity)
        rows.append({'season': season, 'date': utc(stamp).date().isoformat(), 'kickoff': utc(stamp).isoformat(),
                     'home': home.strip(), 'away': away.strip(), 'hg': int(scores[0]), 'ag': int(scores[1]), 'finished': True})
    return rows


class _ResultsTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = 0; self.depth = 0; self.rows = []; self.row = None; self.cell = None; self.in_match = False; self.in_span = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); classes = (attrs.get('class') or '').split()
        if tag == 'table':
            if self.depth: self.depth += 1
            elif 'table-main' in classes: self.depth = 1; self.tables += 1
        if not self.depth: return
        if tag == 'tr': self.row = {'teams': [], 'score': '', 'date': '', 'cells': 0}
        elif tag == 'td' and self.row is not None:
            self.row['cells'] += 1
            self.cell = 'date' if 'h-text-no-wrap' in classes else 'score' if 'h-text-center' in classes else 'other'
        elif tag == 'a' and self.row is not None and 'in-match' in classes: self.in_match = True
        elif tag == 'span' and self.in_match:
            if not self.in_span: self.row['teams'].append('')
            self.in_span += 1

    def handle_endtag(self, tag):
        if not self.depth: return
        if tag == 'table':
            self.depth -= 1
        elif tag == 'span' and self.in_span: self.in_span -= 1
        elif tag == 'a': self.in_match = False; self.in_span = 0
        elif tag == 'td': self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row['teams'] or self.row['score'].strip(): self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.row is None: return
        if self.in_match:
            if self.in_span: self.row['teams'][-1] += data
        elif self.cell == 'score': self.row['score'] += data
        elif self.cell == 'date': self.row['date'] += data


def _be_date(text, captured):
    text = ' '.join(text.split())
    if text.casefold() == 'today': return captured.date()
    if text.casefold() == 'yesterday': return captured.date() - timedelta(days=1)
    full = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4})', text)
    if full: return date(int(full[3]), int(full[2]), int(full[1]))
    short = re.fullmatch(r'(\d{2})\.(\d{2})\.', text)
    if short:
        value = date(captured.year, int(short[2]), int(short[1]))
        return value if value <= captured.date() + timedelta(days=1) else date(captured.year - 1, int(short[2]), int(short[1]))
    raise ProviderError('UNPARSEABLE_DATE')


def parse_betexplorer(html, season, captured):
    """Regulation results from a BetExplorer league results page. Postponed/cancelled/awarded rows are excluded."""
    parser = _ResultsTable(); parser.feed(html); parser.close()
    if not parser.tables: raise ProviderError('PARSER_SCHEMA_MISMATCH')
    rows, skipped = [], 0
    for raw in parser.rows:
        teams = [' '.join(t.split()) for t in raw['teams']]
        score = ' '.join(raw['score'].split())
        if len(teams) != 2 or not all(teams) or fold(teams[0]) == fold(teams[1]): raise ProviderError('INVALID_RESULT_ROW')
        match = re.fullmatch(r'(\d{1,2}):(\d{1,2})', score)
        if not match:
            skipped += 1  # POSTP., CAN., AWA., or extra-time/penalty results (not regulation league scores)
            continue
        day = _be_date(raw['date'], captured)
        if day > captured.date(): raise ProviderError('RESULT_AFTER_CAPTURE')
        rows.append({'season': season, 'date': day.isoformat(), 'home': teams[0], 'away': teams[1],
                     'hg': int(match[1]), 'ag': int(match[2]), 'finished': True})
    if len({(r['date'], fold(r['home']), fold(r['away'])) for r in rows}) != len(rows): raise ProviderError('DUPLICATE_RESULT')
    return rows, skipped


# Team resolution --------------------------------------------------------------------------

def tokens(name):
    words = re.sub(r'[^0-9a-z]+', ' ', fold(name)).split()
    words = ['saint' if w in ('st', 'sint', 'san', 'sankt') else w for w in words]
    return frozenset(w for w in words if w not in LEGAL_TOKENS) or frozenset(words)


def aliases(provider):
    try: table = json.loads(os.getenv('SPORTS_TEAM_ALIASES_JSON') or '{}')
    except ValueError: return {}
    entry = table.get(provider) if isinstance(table, dict) else None
    return {fold(k): v for k, v in entry.items()} if isinstance(entry, dict) else {}


def resolve(ours, candidates, provider):
    """Provider name for one of our team names: alias, exact token match, else a unique containment match."""
    alias = [c for c in candidates if fold(aliases(provider).get(fold(c), '')) == fold(ours)]
    if len(alias) == 1: return alias[0]
    target = tokens(ours)
    exact = [c for c in candidates if tokens(c) == target]
    if len(exact) == 1: return exact[0]
    if exact: return None
    contained = [c for c in candidates if target <= tokens(c) or tokens(c) <= target]
    return contained[0] if len(contained) == 1 else None


# Section computation ----------------------------------------------------------------------

def sections_for(rows, home, away, horizon, our_home, our_away):
    from app.modules.autonomy.open_intelligence import features_for, letters, FORM_WINDOW, RATE_WINDOW, H2H_WINDOW, season_label
    built = features_for(rows, home, away, horizon)
    if built is None: return {}
    f, h, a = built
    named = {home: our_home, away: our_away}
    meetings = sorted((r for r in rows if r['date'] <= horizon and {r['home'], r['away']} == {home, away}), key=lambda r: r['date'])[-H2H_WINDOW:]
    base = {'horizon': horizon, 'computed_from': 'complete provider league results up to the shared horizon', 'scope': 'league matches only'}
    seasons = sorted({r['season'] for r in rows})
    return {'recent_form': {**base, 'home_form': f['home_form'], 'away_form': f['away_form'], 'home_last5': letters(h), 'away_last5': letters(a), 'window': FORM_WINDOW},
            'match_statistics': {**base, **{k: f[k] for k in ('home_scoring_rate', 'away_scoring_rate', 'home_conceding_rate', 'away_conceding_rate')},
                                 'window': RATE_WINDOW, 'home_matches': min(len(h), RATE_WINDOW), 'away_matches': min(len(a), RATE_WINDOW)},
            'head_to_head': {**base, 'seasons_covered': [season_label(s) for s in seasons],
                             'meetings': [{'season': season_label(r['season']), 'home': named[r['home']], 'away': named[r['away']],
                                           'score': f"{r['hg']}-{r['ag']}"} for r in meetings]}}


# Caching and orchestration ----------------------------------------------------------------

def cache_id(provider, league, season): return f'wc:{provider}:{_hash(league)[:12]}:{season}'


def cached(db, key, source_id):
    state = db.get(m.ProviderSyncState, key)
    if state is None:
        state = m.ProviderSyncState(id=key, source_id=source_id, payload={}, failures=0); db.add(state); db.flush()
    return state


def targets(db, at):
    from app.modules.autonomy.fixture_status import quarantined_fixtures
    fixtures = db.scalars(select(m.Fixture).join(m.Competition, m.Competition.id == m.Fixture.competition_id)
                          .join(m.Sport, m.Sport.id == m.Competition.sport_id)
                          .where(m.Sport.name == 'Football', m.Fixture.kickoff_at > at, m.Fixture.kickoff_at <= at + timedelta(days=7),
                                 m.Fixture.id.not_in(quarantined_fixtures()),
                                 m.Fixture.status.notin_(('FINISHED', 'CANCELLED', 'CANCELED', 'ABANDONED', 'POSTPONED')))).all()
    out = []
    for fixture in fixtures:
        league = league_for(db.get(m.Competition, fixture.competition_id))
        if league: out.append((fixture, league))
    return out


def provider_requests(league, at):
    calendar = bool(league.get('calendar'))
    season = season_of(at, calendar)
    for current, year in ((True, season), (False, season - 1)):
        for name in IDS:
            key = league.get(name)
            if not key: continue
            url = (footballdata_url(key, year) if name == 'footballdata' else apifootball_url(key, year) if name == 'apifootball'
                   else sportsdb_reference_url(key, year, calendar) if name == 'thesportsdb' else betexplorer_url(key, year, calendar, current))
            yield IDS[name], name, str(key), year, current, url


def refresh(factory, at, fetchers):
    report = {'fetched': [], 'errors': [], 'skipped': 0}
    with factory() as db:
        wanted, calendars = {}, {}
        for _, league in targets(db, at):
            for request in provider_requests(league, at):
                if provider_enabled(db, request[1]):
                    key = cache_id(request[1], request[2], request[3])
                    wanted[key] = request; calendars[key] = bool(league.get('calendar'))
    for key, (sid, provider, league, season, current, url) in sorted(wanted.items(), key=lambda kv: not kv[1][4]):
        with factory.begin() as db:
            state = cached(db, key, sid)
            if state.next_check_at and utc(state.next_check_at) > at:
                report['skipped'] += 1; continue
            rate = cached(db, 'wc:rate:' + provider, sid)
            if rate.next_check_at and utc(rate.next_check_at) > at:
                report['skipped'] += 1; continue
            rate.next_check_at = at + SPACING[provider]
        pause = 0
        try:
            if provider == 'apifootball':
                rows, skipped = parse_apifootball(fetchers['apifootball'](league, season), season, at), 0
            elif provider == 'footballdata':
                payload = fetchers['footballdata'](league, season)
                pause = throttle_wait(payload)
                rows, skipped = parse_footballdata(payload, season, at), 0
            elif provider == 'thesportsdb':
                rows, skipped = parse_thesportsdb(fetchers['thesportsdb'](league, sportsdb_season(season, calendars[key])), season, at), 0
            else:
                rows, skipped = parse_betexplorer(fetchers['betexplorer'](url), season, at)
        except Exception as exc:
            code = (str(exc) if isinstance(exc, (ValueError, PermissionError)) else type(exc).__name__)[:200]
            report['errors'].append({'provider': provider, 'league': league, 'season': season, 'code': code})
            with factory.begin() as db:
                state = cached(db, key, sid)
                if code == 'HTTP_429':
                    # Rate limited: pause the whole provider until its counter resets; not a data failure.
                    wait = timedelta(seconds=getattr(exc, 'retry_after', 0) or 60)
                    cached(db, 'wc:rate:' + provider, sid).next_check_at = at + wait
                    state.next_check_at = at + wait
                else:
                    state.failures = (state.failures or 0) + 1
                    state.next_check_at = at + timedelta(minutes=min(720, 15 * 2 ** min(state.failures, 5)))
                state.payload = {**(state.payload or {}), 'error': code, 'error_at': at.isoformat()}
            continue
        with factory.begin() as db:
            if pause:
                rate = cached(db, 'wc:rate:' + provider, sid)
                rate.next_check_at = max(utc(rate.next_check_at) if rate.next_check_at else at, at + timedelta(seconds=pause))
            state = cached(db, key, sid)
            state.payload = {'rows': rows, 'season': season, 'league': league, 'url': url, 'excluded_rows': skipped,
                             'response_sha256': _hash(rows)}
            state.failures = 0; state.last_full_at = at
            state.next_check_at = at + (CURRENT_REFRESH if current else PREVIOUS_REFRESH)
        report['fetched'].append({'provider': provider, 'league': league, 'season': season, 'results': len(rows)})
    return report


def provider_rows(db, provider, league, at):
    """Both seasons for one provider, or (None, reason) if the current season is missing or stale."""
    rows, urls = [], []
    for sid, name, key, season, current, url in provider_requests(league, at):
        if name != provider: continue
        state = db.get(m.ProviderSyncState, cache_id(name, key, season))
        if state is None or not state.last_full_at:
            if current: return None, 'NOT_COLLECTED', []
            continue
        if current and at - utc(state.last_full_at) > MAX_DATA_AGE: return None, 'STALE', []
        rows.extend((state.payload or {}).get('rows') or []); urls.append(url)
    return rows, None, urls


def record(db, fixture_id, status, detail=None):
    """Per-fixture outcome for the research workspace (needs a registered provider row for the FK)."""
    state = db.get(m.ProviderSyncState, 'wc:fixture:' + fixture_id)
    if state is None:
        sid = next((IDS[n] for n in IDS if provider_enabled(db, n)), None)
        if sid is None: return
        state = m.ProviderSyncState(id='wc:fixture:' + fixture_id, source_id=sid, payload={}, failures=0); db.add(state)
    state.payload = {'status': status, 'detail': detail}


def produce(factory, at):
    report = {'fixtures': 0, 'observations': 0, 'outcomes': {}}
    with factory() as db:
        providers = [(IDS[name], name) for name in IDS if provider_enabled(db, name)]
        work = [(f.id, f.home_name, f.away_name, f.kickoff_at, league) for f, league in targets(db, at)]
    for fixture_id, home, away, kickoff, league in work:
        outcome, detail, per, problems = None, None, {}, []
        usable = [(sid, name) for sid, name in providers if league.get(name)]
        if not usable:
            outcome = 'SECOND_PROVIDER_REQUIRED'
        else:
            with factory() as db:
                loaded = {sid: (name,) + provider_rows(db, name, league, at) for sid, name in usable}
            for sid, (name, rows, reason, urls) in loaded.items():
                if rows is None: problems.append(('DATA_' + reason, name)); continue
                latest = max((r['season'] for r in rows), default=None)
                current = {t for r in rows if r['season'] == latest for t in (r['home'], r['away'])}
                ph, pa = resolve(home, current, name), resolve(away, current, name)
                if not ph or not pa or ph == pa: problems.append(('TEAM_UNMAPPED', name)); continue
                per[sid] = (name, rows, ph, pa, urls)
            horizon = max(r['date'] for _, rows, *_ in per.values() for r in rows) if per and all(v[1] for v in per.values()) else None
            built = {sid: sections_for(rows, ph, pa, horizon, home, away) for sid, (_, rows, ph, pa, _) in per.items()} if horizon else {}
            built = {sid: v for sid, v in built.items() if v}
            camps = {}
            for sid, sections in built.items(): camps.setdefault(json.dumps(sections, sort_keys=True), []).append(sid)
            agree = max(camps.values(), key=len) if camps else []
            if not per:
                outcome, detail = problems[0] if problems else ('SECOND_PROVIDER_REQUIRED', None)
            elif not horizon or horizon >= utc(kickoff).date().isoformat():
                outcome = 'INSUFFICIENT_HISTORY'
            elif len(built) == 1:
                outcome = 'PROVISIONAL_SINGLE_SOURCE'
                with factory.begin() as db:
                    stamp = min(at, utc(kickoff) - timedelta(minutes=1))
                    sid = next(iter(built))
                    name, _, ph, pa, urls = per[sid]
                    for section, data in built[sid].items():
                        digest = _hash(sid, fixture_id, section, data)
                        if db.scalar(select(m.Observation.id).where(m.Observation.source_id == sid, m.Observation.content_hash == digest)): continue
                        db.add(m.Observation(source_id=sid, fixture_id=fixture_id, observed_at=stamp, source_url=urls[0], content_hash=digest,
                                             payload={'section': section, 'data': data, 'verification': 'SINGLE_SOURCE',
                                                      'independence_group': GROUPS[sid], 'producer': PRODUCER,
                                                      'source_reference': f'{GROUPS[sid]}:{section}:{horizon}',
                                                      'team_resolution': {home: ph, away: pa}, 'source_urls': urls}))
                        report['observations'] += 1
                report['fixtures'] += 1
            elif len(built) < 2:
                outcome = 'INSUFFICIENT_HISTORY'
            elif len(agree) < 2:
                differing = sorted(s for s in SECTIONS if len({json.dumps(v[s], sort_keys=True) for v in built.values()}) > 1)
                outcome, detail = 'PROVIDERS_DISAGREE', ', '.join(differing)
            else:
                # Any two (or more) independent providers with identical computations verify; others are named.
                outcome = 'CORROBORATED'
                outvoted = [LABELS[per[sid][0]] for sid in built if sid not in agree]
                if outvoted: detail = 'disagreeing: ' + ', '.join(outvoted)
                with factory.begin() as db:
                    stamp = min(at, utc(kickoff) - timedelta(minutes=1))
                    for sid in agree:
                        name, _, ph, pa, urls = per[sid]
                        for section, data in built[sid].items():
                            digest = _hash(sid, fixture_id, section, data)
                            existing = db.scalar(select(m.Observation).where(m.Observation.source_id == sid, m.Observation.content_hash == digest))
                            if existing:
                                if existing.payload.get('verification') == 'SINGLE_SOURCE':
                                    existing.payload = {**existing.payload, 'verification': 'CROSS_SOURCE_QUORUM'}
                                continue
                            db.add(m.Observation(source_id=sid, fixture_id=fixture_id, observed_at=stamp, source_url=urls[0], content_hash=digest,
                                                 payload={'section': section, 'data': data, 'verification': 'CROSS_SOURCE_QUORUM',
                                                          'independence_group': GROUPS[sid], 'producer': PRODUCER,
                                                          'source_reference': f'{GROUPS[sid]}:{section}:{horizon}',
                                                          'team_resolution': {home: ph, away: pa}, 'source_urls': urls}))
                            report['observations'] += 1
                report['fixtures'] += 1
        report['outcomes'][outcome] = report['outcomes'].get(outcome, 0) + 1
        with factory.begin() as db: record(db, fixture_id, outcome, detail)
    return report


def canonical_name(name, known, provider):
    """Our stored team name for a provider name (alias, exact tokens, or unique containment), else None."""
    alias = aliases(provider).get(fold(name))
    if alias and alias in known: return alias
    return resolve(name, known, '')


def corroborate_results(factory, at, limit=400):
    """Record finished league results on which two independent providers agree (team identity, date within a day, score).

    A timestamped provider is the reference and every other enabled provider is compared with it. Agreed matches become
    official_result evidence and versioned Results: the corroborated history a per-competition market model is validated
    on. A disagreement or an unresolved team records nothing."""
    report = {'reconciled': 0, 'existing': 0, 'disagreements': 0, 'unmatched': 0, 'competitions': 0}
    with factory() as db:
        enabled_names = [name for name in IDS if provider_enabled(db, name)]
        leagues_by_comp = {}
        for fixture, league in targets(db, at):
            if sum(1 for n in enabled_names if league.get(n)) >= 2: leagues_by_comp.setdefault(fixture.competition_id, league)
        if not leagues_by_comp: return {**report, 'status': 'SECOND_PROVIDER_REQUIRED'}
        work = []
        for comp_id, league in leagues_by_comp.items():
            loaded = {}
            for name in enabled_names:
                if not league.get(name): continue
                rows, _, urls = provider_rows(db, name, league, at)
                if rows is not None: loaded[name] = (rows, urls)
            reference = next((n for n in TIMESTAMPED if n in loaded), None)
            if reference is None or len(loaded) < 2: continue
            marker = _hash(sorted(json.dumps(r, sort_keys=True) for rows, _ in loaded.values() for r in rows))
            state = db.get(m.ProviderSyncState, 'wc:results:' + comp_id[:40])
            if state is not None and (state.payload or {}).get('marker') == marker: continue
            known = {n for row in db.execute(select(m.Fixture.home_name, m.Fixture.away_name).where(m.Fixture.competition_id == comp_id)) for n in row}
            work.append((comp_id, reference, loaded, known, marker))
    from app.modules.autonomy.open_intelligence import outcome
    from app.modules.results.automation import reconcile_observation
    for comp_id, reference, loaded, known, marker in work:
        report['competitions'] += 1
        a, urls_a = loaded[reference]
        canon_a = {n: canonical_name(n, known, reference) or n for r in a for n in (r['home'], r['away'])}
        universe = set(canon_a.values())
        index = {}
        for r in a:
            index.setdefault((r['season'], canon_a[r['home']], canon_a[r['away']]), []).append(r)
        agreed = []
        for partner, (b, urls_b) in loaded.items():
            if partner == reference: continue
            canon_b = {n: canonical_name(n, universe, partner) for r in b for n in (r['home'], r['away'])}
            for r in b:
                home, away = canon_b[r['home']], canon_b[r['away']]
                if not home or not away:
                    report['unmatched'] += 1; continue
                day = date.fromisoformat(r['date'])
                match = next((x for x in index.get((r['season'], home, away), []) if abs((date.fromisoformat(x['date']) - day).days) <= 1), None)
                if match is None: report['unmatched'] += 1
                elif (match['hg'], match['ag']) != (r['hg'], r['ag']): report['disagreements'] += 1
                elif utc(datetime.fromisoformat(match['kickoff'])) + timedelta(hours=2) <= at: agreed.append((home, away, match, partner, urls_b))
        for home, away, row, partner, urls_b in agreed[:limit]:
            kickoff = utc(datetime.fromisoformat(row['kickoff']))
            with factory.begin() as db:
                fixture = db.scalar(select(m.Fixture).where(m.Fixture.competition_id == comp_id, m.Fixture.home_name == home, m.Fixture.away_name == away,
                                                            m.Fixture.kickoff_at >= kickoff - timedelta(hours=36), m.Fixture.kickoff_at <= kickoff + timedelta(hours=36)))
                if fixture is None:
                    fixture = m.Fixture(competition_id=comp_id, home_name=home, away_name=away, kickoff_at=kickoff, status='FINISHED')
                    db.add(fixture); db.flush()
                data = outcome(row['hg'], row['ag'])
                created = False
                for sid, url in ((IDS[reference], urls_a[0]), (IDS[partner], urls_b[0])):
                    digest = _hash(sid, fixture.id, 'official_result', data)
                    obs = db.scalar(select(m.Observation).where(m.Observation.source_id == sid, m.Observation.content_hash == digest))
                    if obs is None:
                        obs = m.Observation(source_id=sid, fixture_id=fixture.id, observed_at=at, source_url=url, content_hash=digest,
                                            payload={'section': 'official_result', 'data': data, 'verification': 'CROSS_SOURCE_QUORUM',
                                                     'independence_group': GROUPS[sid], 'producer': PRODUCER,
                                                     'source_reference': f"{GROUPS[sid]}:result:{row['season']}:{home}-{away}"})
                        db.add(obs); db.flush(); created = True
                    if not db.scalar(select(m.ResultEvidence.observation_id).where(m.ResultEvidence.observation_id == obs.id)):
                        with db.begin_nested(): reconcile_observation(db, obs.id)
                if (fixture.status or '').upper() != 'FINISHED': fixture.status = 'FINISHED'
                report['reconciled' if created else 'existing'] += 1
        if len(agreed) <= limit:
            with factory.begin() as db:
                state = db.get(m.ProviderSyncState, 'wc:results:' + comp_id[:40])
                if state is None:
                    state = m.ProviderSyncState(id='wc:results:' + comp_id[:40], source_id=IDS[reference], payload={}, failures=0); db.add(state)
                state.payload = {'marker': marker, 'agreed': len(agreed), 'at': at.isoformat()}; state.last_full_at = at
    return report


def readiness_note(db, fixture):
    """One sentence for the research workspace explaining corroboration status for this fixture."""
    league = league_for(db.get(m.Competition, fixture.competition_id))
    if not league or not enabled(): return ''
    missing = {'footballdata': 'not configured (set SPORTS_FOOTBALL_DATA_ORG_KEY; free key)',
               'apifootball': 'not configured (set SPORTS_APIFOOTBALL_KEY)',
               'thesportsdb': 'needs a paid SPORTS_THESPORTSDB_KEY (the public key truncates seasons)',
               'betexplorer': 'not used without recorded operator consent'}
    parts = [LABELS[name] + ': ' + ('enabled' if provider_enabled(db, name) else missing[name]) for name in IDS if league.get(name)]
    state = db.get(m.ProviderSyncState, 'wc:fixture:' + fixture.id)
    if state and (state.payload or {}).get('status'):
        parts.append('window corroboration: ' + state.payload['status'] + (f" ({state.payload['detail']})" if state.payload.get('detail') else ''))
    return ' Corroboration providers — ' + '; '.join(parts) + '.' if parts else ''


def collect(factory, at=None, fetchers=None):
    at = at or now()
    if not enabled(): return {'enabled': False, 'errors': []}
    with factory.begin() as db: report = {'enabled': True, 'sources_changed': ensure_sources(db)}
    fetchers = {'footballdata': fetch_footballdata, 'apifootball': fetch_apifootball, 'thesportsdb': fetch_thesportsdb,
                'betexplorer': fetch_betexplorer, **(fetchers or {})}
    report['refresh'] = refresh(factory, at, fetchers)
    report['evidence'] = produce(factory, at)
    report['results'] = corroborate_results(factory, at)
    report['errors'] = report['refresh']['errors']
    return report
