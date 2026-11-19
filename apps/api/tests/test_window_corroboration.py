"""Two-provider league-window corroboration: verified only when independent computations agree."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from app.db import models as m
from app.modules.acquisition import source_policy
from app.modules.autonomy import window_corroboration as wc
from app.modules.pipeline import operations
from app.modules.pipeline.operations import research
from test_browser_intelligence import factory as make_factory

AT = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)
KICKOFF = AT + timedelta(days=1, hours=9)

# (date, home, away, hg, ag) in canonical names; provider-specific spellings are applied below.
CURRENT = [('2026-08-02', 'Cercle Brugge', 'Genk', 1, 0), ('2026-08-09', 'Westerlo', 'Gent', 2, 2),
           ('2026-08-16', 'Anderlecht', 'Cercle Brugge', 3, 1), ('2026-08-23', 'Club Brugge', 'Westerlo', 1, 1),
           ('2026-09-13', 'Cercle Brugge', 'Union Saint-Gilloise', 0, 2), ('2026-09-20', 'Westerlo', 'Anderlecht', 0, 1),
           ('2026-10-04', 'Gent', 'Cercle Brugge', 1, 1), ('2026-10-18', 'Genk', 'Westerlo', 2, 3),
           ('2026-11-01', 'Cercle Brugge', 'Club Brugge', 2, 1), ('2026-11-08', 'Westerlo', 'Union Saint-Gilloise', 1, 0)]
PREVIOUS = [('2026-02-14', 'Westerlo', 'Cercle Brugge', 2, 0), ('2026-04-25', 'Cercle Brugge', 'Westerlo', 1, 1)]
APIF_NAMES = {'Cercle Brugge': 'Cercle Brugge KSV', 'Westerlo': 'KVC Westerlo', 'Club Brugge': 'Club Brugge KV',
              'Union Saint-Gilloise': 'Union St. Gilloise', 'Genk': 'KRC Genk', 'Gent': 'KAA Gent', 'Anderlecht': 'RSC Anderlecht'}


def apif_payload(rows, season, override=None):
    response = []
    for index, (day, home, away, hg, ag) in enumerate(rows):
        if override and (day, home) == override[0]: hg, ag = override[1]
        response.append({'fixture': {'id': season * 1000 + index, 'date': day + 'T18:45:00+00:00', 'status': {'short': 'FT'}},
                         'teams': {'home': {'name': APIF_NAMES[home]}, 'away': {'name': APIF_NAMES[away]}},
                         'goals': {'home': hg, 'away': ag}, 'score': {'fulltime': {'home': hg, 'away': ag}}})
    response.append({'fixture': {'id': season * 1000 + 999, 'date': '2026-11-21T18:45:00+00:00', 'status': {'short': 'NS'}},
                     'teams': {'home': {'name': 'KRC Genk'}, 'away': {'name': 'KAA Gent'}}, 'score': {'fulltime': {'home': None, 'away': None}}})
    return {'get': 'fixtures', 'errors': [], 'results': len(response), 'paging': {'current': 1, 'total': 1}, 'response': response}


def be_html(rows, extra=''):
    body = ''.join(
        f'<tr><td class="h-text-left"><a href="/football/belgium/x/{i}/" class="in-match"><span>{h}</span> - <span><strong>{a}</strong></span></a></td>'
        f'<td class="h-text-center"><a href="/m/{i}/">{hg}:{ag}</a></td><td class="table-main__odds" data-odd="2.1"></td>'
        f'<td class="h-text-right h-text-no-wrap">{d[8:10]}.{d[5:7]}.{d[:4]}</td></tr>'
        for i, (d, h, a, hg, ag) in enumerate(rows))
    return f'<html><body><table class="table-main js-tablebanner-t"><tr><th colspan="2">1. Round</th></tr>{body}{extra}</table></body></html>'


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv('SPORTS_APIFOOTBALL_KEY', 'testkey')
    monkeypatch.setenv('SPORTS_SOURCE_CONSENT', 'betexplorer.com=TEST-LICENCE-001')
    monkeypatch.setenv('SPORTS_RESEARCH_DEADLINE_MINUTES', '60')
    session = make_factory()
    with session.begin() as db:
        sport = m.Sport(name='Football'); db.add(sport); db.flush()
        comp = m.Competition(sport_id=sport.id, name='Belgian Pro League', country='Belgium'); db.add(comp); db.flush()
        db.add(m.Fixture(id='fx-cercle', competition_id=comp.id, home_name='Cercle Brugge', away_name='Westerlo',
                         kickoff_at=KICKOFF, status='SCHEDULED'))
    return session


def fetchers(override=None):
    calls = []
    def apif(league, season):
        calls.append(('apifootball', league, season))
        return apif_payload(CURRENT if season == 2026 else PREVIOUS, season, override)
    def be(url):
        calls.append(('betexplorer', url))
        return be_html(PREVIOUS if '2025-2026' in url else CURRENT)
    return {'apifootball': apif, 'betexplorer': be}, calls


def collect_twice(store, override=None):
    """BetExplorer requests are spaced, so a second cycle collects its previous season."""
    fx, calls = fetchers(override)
    first = wc.collect(store, at=AT, fetchers=fx)
    second = wc.collect(store, at=AT + timedelta(minutes=1), fetchers=fx)
    return first, second, calls


def test_parsers_keep_only_regulation_results():
    rows, skipped = wc.parse_betexplorer(be_html(CURRENT[:2], extra=(
        '<tr><td class="h-text-left"><a class="in-match"><span>Genk</span> - <span>Gent</span></a></td>'
        '<td class="h-text-center"><a>POSTP.</a></td><td class="h-text-right h-text-no-wrap">Yesterday</td></tr>')), 2026, AT)
    assert [(r['date'], r['home'], r['away'], r['hg'], r['ag']) for r in rows] == CURRENT[:2]
    assert skipped == 1
    assert wc._be_date('17.11.', AT).isoformat() == '2026-11-17'
    assert wc._be_date('28.12.', AT).isoformat() == '2025-12-28'
    with pytest.raises(wc.ProviderError, match='PARSER_SCHEMA_MISMATCH'):
        wc.parse_betexplorer('<html><table class="other"></table></html>', 2026, AT)
    parsed = wc.parse_apifootball(apif_payload(CURRENT, 2026), 2026, AT)
    assert len(parsed) == len(CURRENT) and parsed[0]['home'] == 'Cercle Brugge KSV'
    with pytest.raises(wc.ProviderError, match='PROVIDER_ERROR'):
        wc.parse_apifootball({'errors': {'plan': 'Free plans do not have access to this season'}, 'response': []}, 2026, AT)
    with pytest.raises(wc.ProviderError, match='INCOMPLETE_PAGING'):
        wc.parse_apifootball({**apif_payload(CURRENT, 2026), 'paging': {'current': 1, 'total': 2}}, 2026, AT)


def test_team_resolution_is_unique_or_refused(monkeypatch):
    league = list(APIF_NAMES.values())
    assert wc.resolve('Union Saint-Gilloise', league, 'apifootball') == 'Union St. Gilloise'
    assert wc.resolve('Club Brugge', league, 'apifootball') == 'Club Brugge KV'
    assert wc.resolve('Cercle Brugge', league, 'apifootball') == 'Cercle Brugge KSV'
    assert wc.resolve('Brugge', league, 'apifootball') is None
    monkeypatch.setenv('SPORTS_TEAM_ALIASES_JSON', '{"betexplorer": {"Royale Union SG": "Union Saint-Gilloise"}}')
    assert wc.resolve('Union Saint-Gilloise', ['Royale Union SG', 'Genk'], 'betexplorer') == 'Royale Union SG'


def test_betexplorer_stays_prohibited_without_written_consent(store, monkeypatch):
    monkeypatch.delenv('SPORTS_SOURCE_CONSENT')
    with store.begin() as db: source_policy.register_prohibited_sources(db)
    fx, calls = fetchers()
    report = wc.collect(store, at=AT, fetchers=fx)
    assert all(call[0] == 'apifootball' for call in calls)
    with store() as db:
        assert db.get(m.Source, wc.BE_ID).permission == 'PROHIBITED'
        assert 'blocked until' in wc.readiness_note(db, db.get(m.Fixture, 'fx-cercle'))
    assert report['evidence']['outcomes'] == {'SECOND_PROVIDER_REQUIRED': 1}
    with pytest.raises(PermissionError):
        source_policy.assert_permitted(wc.betexplorer_url('football/belgium/jupiler-pro-league', 2026, False, True))


def test_agreeing_complete_windows_verify_research_sections(store, monkeypatch):
    _, second, calls = collect_twice(store)
    assert second['evidence']['outcomes'] == {'CORROBORATED': 1}
    assert ('betexplorer', 'https://www.betexplorer.com/football/belgium/jupiler-pro-league/results/') in calls
    with store.begin() as db:
        assert db.get(m.Source, wc.BE_ID).permission == 'AUTHORIZED'
        assert db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == 'source.consent_recorded')).payload['consent_reference'] == 'TEST-LICENCE-001'
        derived = db.scalars(select(m.Observation).where(m.Observation.fixture_id == 'fx-cercle')).all()
        assert {(o.source_id, o.payload['section']) for o in derived} == {(s, x) for s in wc.GROUPS for x in wc.SECTIONS}
        form = next(o for o in derived if o.payload['section'] == 'recent_form').payload['data']
        assert form['home_last5'] == 'WLLDW' and form['away_last5'] == 'DDLWW'
        h2h = next(o for o in derived if o.payload['section'] == 'head_to_head').payload['data']
        assert [x['home'] for x in h2h['meetings']] == ['Westerlo', 'Cercle Brugge']
        receipts = []
        monkeypatch.setattr(operations, 'receipt', lambda db, run, key, kind, refs, details, at, **_: receipts.append((kind, details)))
        research(db, SimpleNamespace(fixture_id='fx-cercle'), AT + timedelta(minutes=2))
        kind, details = receipts[0]
        assert kind == 'DOSSIER_VERIFIED' and not details['missing_data_report']
        assert set(wc.SECTIONS) <= set(details['verified_sections'])
        assert 'CROSS_SOURCE_QUORUM' in details['verification_methods']


def test_disagreeing_provider_yields_no_evidence(store):
    _, second, _ = collect_twice(store, override=(('2026-11-01', 'Cercle Brugge'), (2, 2)))
    assert second['evidence']['outcomes'] == {'PROVIDERS_DISAGREE': 1}
    with store() as db:
        assert not db.scalars(select(m.Observation).where(m.Observation.fixture_id == 'fx-cercle')).all()
        assert 'PROVIDERS_DISAGREE' in wc.readiness_note(db, db.get(m.Fixture, 'fx-cercle'))


def test_agreed_past_results_become_corroborated_history(store):
    first, second, _ = collect_twice(store, override=(('2026-11-01', 'Cercle Brugge'), (2, 2)))
    # Cycle 1 has this season from both providers; cycle 2 adds last season once BetExplorer's spaced request ran.
    assert first['results']['reconciled'] == len(CURRENT) - 1 and first['results']['disagreements'] == 1
    results = {'reconciled': first['results']['reconciled'] + second['results']['reconciled']}
    assert second['results']['unmatched'] == 0
    assert results['reconciled'] == len(CURRENT) + len(PREVIOUS) - 1
    from app.modules.research.league import verified_matches
    with store() as db:
        comp_id = db.get(m.Fixture, 'fx-cercle').competition_id
        matches = verified_matches(db, comp_id, AT + timedelta(minutes=5))
        assert len(matches) == results['reconciled']
        names = {n for g in matches for n in (g['home_id'], g['away_id'])}
        # Our stored names win where known; other clubs take one consistent provider name across both providers.
        assert {'Cercle Brugge', 'Westerlo', 'Club Brugge KV', 'Union St. Gilloise'} <= names
        assert not any(g['home_id'] == 'Cercle Brugge' and g['away_id'] == 'Club Brugge KV' for g in matches), 'disputed score is not recorded'
    again = wc.collect(store, at=AT + timedelta(minutes=2), fetchers=fetchers()[0])
    assert again['results']['reconciled'] == 0, 'unchanged provider data is not reprocessed'


def test_models_forecast_only_competitions_they_were_validated_on(store):
    from app.modules.prediction.scope import competitions_for, in_scope
    with store.begin() as db:
        fixture = db.get(m.Fixture, 'fx-cercle')
        legacy = m.ModelVersion(sport_id=fixture.competition.sport_id, name='Legacy', version='1', status='ACTIVE', validation={})
        scoped = m.ModelVersion(sport_id=fixture.competition.sport_id, name='Scoped', version='2', status='ACTIVE',
                                validation={'competition_ids': [fixture.competition_id]})
        db.add_all([legacy, scoped]); db.flush()
        assert competitions_for(db, legacy) == set(), 'legacy models are Bundesliga-only (absent here)'
        assert not in_scope(db, legacy, fixture.competition_id) and in_scope(db, scoped, fixture.competition_id)
