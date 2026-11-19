"""Two-provider corroboration of complete league result windows (beyond the Bundesliga).

Each provider's *complete* league-season results are cached separately. For an upcoming fixture,
each provider computes form, scoring rates and head-to-head on its own; observations are emitted for
both providers only when the two computations are identical, so the research quorum can verify them.
A provider that is behind, missing a match or disagreeing on a score yields no evidence (never a
blend). Team names are resolved conservatively per league and the resolution is auditable.

Providers:
- API-Football (documented API; requires SPORTS_APIFOOTBALL_KEY; plan must cover the season).
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
GROUPS = {APIF_ID: 'api-football', BE_ID: 'betexplorer'}
CURRENT_REFRESH = timedelta(hours=6)
PREVIOUS_REFRESH = timedelta(days=7)
MAX_DATA_AGE = timedelta(hours=12)
BE_SPACING = timedelta(seconds=30)
USER_AGENT = 'CACSMS-Sports/1.0 (league results research; low-frequency)'

# Competition (casefolded name, country or None) -> provider identities. 'calendar' leagues use one-year seasons.
# Wrong identities are safe: unmatched teams or differing results produce no evidence.
LEAGUES = {
    ('belgian pro league', 'belgium'): {'apifootball': 144, 'betexplorer': 'football/belgium/jupiler-pro-league'},
    ('premier league', 'england'): {'apifootball': 39, 'betexplorer': 'football/england/premier-league'},
    ('english league championship', 'england'): {'apifootball': 40, 'betexplorer': 'football/england/championship'},
    ('la liga', 'spain'): {'apifootball': 140, 'betexplorer': 'football/spain/laliga'},
    ('serie a', 'italy'): {'apifootball': 135, 'betexplorer': 'football/italy/serie-a'},
    ('ligue 1', 'france'): {'apifootball': 61, 'betexplorer': 'football/france/ligue-1'},
    ('eredivisie', 'netherlands'): {'apifootball': 88, 'betexplorer': 'football/netherlands/eredivisie'},
    ('dutch eredivisie', 'the netherlands'): {'apifootball': 88, 'betexplorer': 'football/netherlands/eredivisie'},
    ('scottish premier league', 'scotland'): {'apifootball': 179, 'betexplorer': 'football/scotland/premiership'},
    ('greek super league 1', 'greece'): {'apifootball': 197, 'betexplorer': 'football/greece/super-league'},
    ('swedish allsvenskan', 'sweden'): {'apifootball': 113, 'betexplorer': 'football/sweden/allsvenskan', 'calendar': True},
    ('norwegian eliteserien', 'norway'): {'apifootball': 103, 'betexplorer': 'football/norway/eliteserien', 'calendar': True},
    ('brazilian serie a', 'brazil'): {'apifootball': 71, 'betexplorer': 'football/brazil/serie-a-betano', 'calendar': True},
}
LEGAL_TOKENS = {'fc', 'afc', 'cf', 'sc', 'kv', 'kvc', 'krc', 'kaa', 'rsc', 'ksv', 'sv', 'fk', 'sk', 'bk', 'ac',
                'cd', 'ud', 'ssc', 'sad', 'if', 'ff', 'aik', 'ec', 'se'}


class ProviderError(ValueError):
    pass


def now(): return datetime.now(timezone.utc)
def enabled(): return os.getenv('SPORTS_WINDOW_CORROBORATION_ENABLED', '1').lower() not in ('0', 'false', 'no')
def apifootball_key(): return os.getenv('SPORTS_APIFOOTBALL_KEY', '').strip()
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


def league_for(competition):
    if competition is None: return None
    table = leagues()
    return table.get((fold(competition.name), fold(competition.country) or None)) or (
        table.get((fold(competition.name), None)) if not competition.country else None)


def season_of(at, calendar):
    return at.year if calendar or at.month >= 7 else at.year - 1


# Sources ---------------------------------------------------------------------------------

def ensure_sources(db):
    """Register API-Football when a key is configured; enable BetExplorer only with recorded consent."""
    changed = []
    source = db.get(m.Source, APIF_ID)
    if apifootball_key():
        if source is None:
            db.add(m.Source(id=APIF_ID, name=APIF_NAME, permission='AUTHORIZED', enabled=True)); db.flush()
            db.add(m.AuditEvent(actor='window-corroboration', action='source.fixture_adapter_registered', correlation_id=APIF_ID,
                                payload={'terms_url': 'https://www.api-football.com/terms', 'permission_scope': 'Configured API subscription; coverage depends on plan',
                                         'independence_group': GROUPS[APIF_ID], 'checked_at': '2026-11-19'}))
            changed.append('api-football')
    elif source is not None and source.enabled and source.permission == 'AUTHORIZED':
        source.enabled = False
        db.add(m.AuditEvent(actor='window-corroboration', action='source.disabled', correlation_id=APIF_ID,
                            payload={'reason': 'SPORTS_APIFOOTBALL_KEY is not configured'}))
        changed.append('api-football-disabled')
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


def registry(db):
    """Quorum policy entries for enabled corroboration providers (used by the research stage)."""
    return {sid: {'reviewed': True, 'independence_group': group, 'sections': list(SECTIONS), 'producer': PRODUCER}
            for sid, group in GROUPS.items() if authorized(db, sid)}


# HTTP -------------------------------------------------------------------------------------

def _get(url, headers=None, limit=4_000_000):
    import httpx
    from app.modules.acquisition.jobs import validate_feed_url
    source_policy.assert_permitted(url)
    validate_feed_url(url)
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False,
                      headers={'User-Agent': USER_AGENT, **(headers or {})}) as client:
        with client.stream('GET', url) as response:
            if response.status_code != 200: raise ProviderError('HTTP_' + str(response.status_code))
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
        if league.get('apifootball'):
            yield APIF_ID, 'apifootball', str(league['apifootball']), year, current, apifootball_url(league['apifootball'], year)
        if league.get('betexplorer'):
            yield BE_ID, 'betexplorer', league['betexplorer'], year, current, betexplorer_url(league['betexplorer'], year, calendar, current)


def refresh(factory, at, fetchers):
    report = {'fetched': [], 'errors': [], 'skipped': 0}
    with factory() as db:
        wanted = {}
        for _, league in targets(db, at):
            for request in provider_requests(league, at):
                if authorized(db, request[0]): wanted[cache_id(request[1], request[2], request[3])] = request
    for key, (sid, provider, league, season, current, url) in sorted(wanted.items(), key=lambda kv: not kv[1][4]):
        with factory.begin() as db:
            state = cached(db, key, sid)
            if state.next_check_at and utc(state.next_check_at) > at:
                report['skipped'] += 1; continue
            if provider == 'betexplorer':
                rate = cached(db, 'wc:rate:betexplorer', sid)
                if rate.next_check_at and utc(rate.next_check_at) > at:
                    report['skipped'] += 1; continue
                rate.next_check_at = at + BE_SPACING
        try:
            if provider == 'apifootball':
                rows, skipped = parse_apifootball(fetchers['apifootball'](league, season), season, at), 0
            else:
                rows, skipped = parse_betexplorer(fetchers['betexplorer'](url), season, at)
        except Exception as exc:
            code = (str(exc) if isinstance(exc, (ValueError, PermissionError)) else type(exc).__name__)[:200]
            report['errors'].append({'provider': provider, 'league': league, 'season': season, 'code': code})
            with factory.begin() as db:
                state = cached(db, key, sid); state.failures = (state.failures or 0) + 1
                state.next_check_at = at + timedelta(minutes=min(720, 15 * 2 ** min(state.failures, 5)))
                state.payload = {**(state.payload or {}), 'error': code, 'error_at': at.isoformat()}
            continue
        with factory.begin() as db:
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
        sid = next((s for s in GROUPS if authorized(db, s)), None)
        if sid is None: return
        state = m.ProviderSyncState(id='wc:fixture:' + fixture_id, source_id=sid, payload={}, failures=0); db.add(state)
    state.payload = {'status': status, 'detail': detail}


def produce(factory, at):
    report = {'fixtures': 0, 'observations': 0, 'outcomes': {}}
    with factory() as db:
        providers = [(sid, name) for sid, name in ((APIF_ID, 'apifootball'), (BE_ID, 'betexplorer')) if authorized(db, sid)]
        work = [(f.id, f.home_name, f.away_name, f.kickoff_at, league) for f, league in targets(db, at)]
    for fixture_id, home, away, kickoff, league in work:
        outcome, detail, per = None, None, {}
        usable = [(sid, name) for sid, name in providers if league.get(name)]
        if len(usable) < 2:
            outcome = 'SECOND_PROVIDER_REQUIRED'
        else:
            with factory() as db:
                loaded = {sid: (name,) + provider_rows(db, name, league, at) for sid, name in usable}
            for sid, (name, rows, reason, urls) in loaded.items():
                if rows is None: outcome, detail = 'DATA_' + reason, name; break
                latest = max((r['season'] for r in rows), default=None)
                current = {t for r in rows if r['season'] == latest for t in (r['home'], r['away'])}
                ph, pa = resolve(home, current, name), resolve(away, current, name)
                if not ph or not pa or ph == pa: outcome, detail = 'TEAM_UNMAPPED', name; break
                per[sid] = (name, rows, ph, pa, urls)
        if outcome is None:
            horizon = max(r['date'] for _, rows, *_ in per.values() for r in rows) if all(v[1] for v in per.values()) else None
            built = {sid: sections_for(rows, ph, pa, horizon, home, away) for sid, (_, rows, ph, pa, _) in per.items()} if horizon else {}
            if not horizon or horizon >= utc(kickoff).date().isoformat() or not all(built.values()):
                outcome = 'INSUFFICIENT_HISTORY'
            elif len({json.dumps(v, sort_keys=True) for v in built.values()}) != 1:
                differing = sorted(s for s in SECTIONS if len({json.dumps(v[s], sort_keys=True) for v in built.values()}) > 1)
                outcome, detail = 'PROVIDERS_DISAGREE', ', '.join(differing)
            else:
                outcome = 'CORROBORATED'
                with factory.begin() as db:
                    stamp = min(at, utc(kickoff) - timedelta(minutes=1))
                    for sid, sections in built.items():
                        name, _, ph, pa, urls = per[sid]
                        for section, data in sections.items():
                            digest = _hash(sid, fixture_id, section, data)
                            if db.scalar(select(m.Observation.id).where(m.Observation.source_id == sid, m.Observation.content_hash == digest)): continue
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
    """Record finished league results on which BOTH providers agree (team identity, date within a day, score).

    These become official_result evidence and versioned Results, i.e. the corroborated history used to validate
    a per-competition market model. A disagreement or an unresolved team records nothing."""
    report = {'reconciled': 0, 'existing': 0, 'disagreements': 0, 'unmatched': 0, 'competitions': 0}
    with factory() as db:
        if not (authorized(db, APIF_ID) and authorized(db, BE_ID)): return {**report, 'status': 'SECOND_PROVIDER_REQUIRED'}
        leagues_by_comp = {}
        for fixture, league in targets(db, at):
            if league.get('apifootball') and league.get('betexplorer'): leagues_by_comp.setdefault(fixture.competition_id, league)
        work = []
        for comp_id, league in leagues_by_comp.items():
            a, _, urls_a = provider_rows(db, 'apifootball', league, at)
            b, _, urls_b = provider_rows(db, 'betexplorer', league, at)
            if a is None or b is None: continue
            marker = _hash(sorted(json.dumps(r, sort_keys=True) for r in a + b))
            state = db.get(m.ProviderSyncState, 'wc:results:' + comp_id[:40])
            if state is not None and (state.payload or {}).get('marker') == marker: continue
            known = {n for row in db.execute(select(m.Fixture.home_name, m.Fixture.away_name).where(m.Fixture.competition_id == comp_id)) for n in row}
            work.append((comp_id, a, b, known, urls_a, urls_b, marker))
    from app.modules.autonomy.open_intelligence import outcome
    from app.modules.results.automation import reconcile_observation
    for comp_id, a, b, known, urls_a, urls_b, marker in work:
        report['competitions'] += 1
        canon_a = {n: canonical_name(n, known, 'apifootball') or n for r in a for n in (r['home'], r['away'])}
        universe = set(canon_a.values())
        canon_b = {n: canonical_name(n, universe, 'betexplorer') for r in b for n in (r['home'], r['away'])}
        index = {}
        for r in a:
            index.setdefault((r['season'], canon_a[r['home']], canon_a[r['away']]), []).append(r)
        agreed = []
        for r in b:
            home, away = canon_b[r['home']], canon_b[r['away']]
            if not home or not away:
                report['unmatched'] += 1; continue
            day = date.fromisoformat(r['date'])
            match = next((x for x in index.get((r['season'], home, away), []) if abs((date.fromisoformat(x['date']) - day).days) <= 1), None)
            if match is None: report['unmatched'] += 1
            elif (match['hg'], match['ag']) != (r['hg'], r['ag']): report['disagreements'] += 1
            elif utc(datetime.fromisoformat(match['kickoff'])) + timedelta(hours=2) <= at: agreed.append((home, away, match))
        for home, away, row in agreed[:limit]:
            kickoff = utc(datetime.fromisoformat(row['kickoff']))
            with factory.begin() as db:
                fixture = db.scalar(select(m.Fixture).where(m.Fixture.competition_id == comp_id, m.Fixture.home_name == home, m.Fixture.away_name == away,
                                                            m.Fixture.kickoff_at >= kickoff - timedelta(hours=36), m.Fixture.kickoff_at <= kickoff + timedelta(hours=36)))
                if fixture is None:
                    fixture = m.Fixture(competition_id=comp_id, home_name=home, away_name=away, kickoff_at=kickoff, status='FINISHED')
                    db.add(fixture); db.flush()
                data = outcome(row['hg'], row['ag'])
                created = False
                for sid, url in ((APIF_ID, urls_a[0]), (BE_ID, urls_b[0])):
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
                    state = m.ProviderSyncState(id='wc:results:' + comp_id[:40], source_id=APIF_ID, payload={}, failures=0); db.add(state)
                state.payload = {'marker': marker, 'agreed': len(agreed), 'at': at.isoformat()}; state.last_full_at = at
    return report


def readiness_note(db, fixture):
    """One sentence for the research workspace explaining corroboration status for this fixture."""
    league = league_for(db.get(m.Competition, fixture.competition_id))
    if not league or not enabled(): return ''
    parts = []
    if league.get('apifootball'):
        parts.append('API-Football: ' + ('enabled' if authorized(db, APIF_ID) else 'not configured (set SPORTS_APIFOOTBALL_KEY)'))
    if league.get('betexplorer'):
        parts.append('BetExplorer: ' + ('enabled under recorded consent' if authorized(db, BE_ID)
                                        else 'blocked until the operator\'s written consent is recorded in SPORTS_SOURCE_CONSENT'))
    state = db.get(m.ProviderSyncState, 'wc:fixture:' + fixture.id)
    if state and (state.payload or {}).get('status'):
        parts.append('window corroboration: ' + state.payload['status'] + (f" ({state.payload['detail']})" if state.payload.get('detail') else ''))
    return ' Corroboration providers — ' + '; '.join(parts) + '.' if parts else ''


def collect(factory, at=None, fetchers=None):
    at = at or now()
    if not enabled(): return {'enabled': False, 'errors': []}
    with factory.begin() as db: report = {'enabled': True, 'sources_changed': ensure_sources(db)}
    fetchers = {'apifootball': fetch_apifootball, 'betexplorer': fetch_betexplorer, **(fetchers or {})}
    report['refresh'] = refresh(factory, at, fetchers)
    report['evidence'] = produce(factory, at)
    report['results'] = corroborate_results(factory, at)
    report['errors'] = report['refresh']['errors']
    return report
