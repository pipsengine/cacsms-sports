"""Development-source samples reach research but never become verified features."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func
from app.db import models as m
from app.modules.autonomy import fixture_providers as providers
from app.modules.research import evidence_bridge as bridge
from app.modules.pipeline.operations import research, Waiting, autonomous_quorum
from test_fixture_discovery import store, acquire, raw_sportsdb, AT


def collect(store, sport='Football'):
    provider_sport='Soccer' if sport=='Football' else sport
    event = raw_sportsdb(strSport=provider_sport,idHomeTeam='10', idAwayTeam='20')
    acquire(store, providers.SPORTSDB_ID, {'kind': 'day'}, {'events': [event]})
    with store() as db:
        fixture_id = db.scalar(select(m.Fixture.id))
    for index, (side, team, name) in enumerate((('home', '10', 'Controlled Home'), ('away', '20', 'Controlled Away'))):
        row = {'idEvent': str(800 + index), 'idHomeTeam': team, 'idAwayTeam': '30',
               'strHomeTeam': name, 'strAwayTeam': 'Opponent', 'strSport': provider_sport,
               'strStatus': 'FT', 'strTimestamp': (AT-timedelta(days=3)).isoformat(),
               'intHomeScore': '91' if sport=='Basketball' else '2', 'intAwayScore': '86' if sport=='Basketball' else '1'}
        acquire(store, providers.SPORTSDB_ID, {'kind': 'team_recent', 'fixture_id': fixture_id,
                'side': side, 'provider_team_id': team}, {'results': [row]}, AT+timedelta(seconds=4*(index+1)))
    return fixture_id


def test_real_collector_histories_are_normalized_idempotently_without_promotion(store):
    fixture_id = collect(store)
    with store.begin() as db:
        for _ in range(2):
            with pytest.raises(Waiting) as exc:
                research(db, SimpleNamespace(fixture_id=fixture_id), AT+timedelta(seconds=12))
            assert exc.value.code == 'PROVISIONAL_RESEARCH_ONLY'
            assert exc.value.state == 'INSUFFICIENT_DATA'
            assert 'single-source research was saved' in str(exc.value)
        derived = [o for o in db.scalars(select(m.Observation)) if o.payload.get('producer') == bridge.PRODUCER]
        assert len(derived) == 2
        form = next(o for o in derived if o.payload['section'] == 'recent_form')
        assert form.payload['data']['home_form'] == 3
        assert len(form.payload['parent_observation_ids']) == 2
        assert bridge.utc(form.observed_at) == AT+timedelta(seconds=8)
        assert form.payload['verification'] == 'SINGLE_SOURCE'
        dossier = db.scalar(select(m.Research))
        assert dossier.status == 'PARTIAL'
        assert dossier.sections['match_statistics']['status'] == 'PROVISIONAL'
        assert db.scalar(select(func.count()).select_from(m.Feature)) == 0
        assert db.scalar(select(func.count()).select_from(m.Prediction)) == 0
        assert autonomous_quorum(db)[providers.SPORTSDB_ID]['producer'] == bridge.PRODUCER


def test_stale_or_revoked_parent_cannot_supply_derived_sections(store):
    fixture_id = collect(store)
    with store.begin() as db:
        fixture = db.get(m.Fixture, fixture_id)
        assert bridge.assemble(db, fixture, AT+timedelta(seconds=12))['usable_parent_observation_ids']
        report, _ = bridge.inspect(db, fixture, AT+timedelta(hours=25))
        assert not report['usable_parent_observation_ids']
        assert 'older than 24 hours' in report['reason']
        db.get(m.Source, providers.SPORTSDB_ID).permission = 'REVOKED'
        report, _ = bridge.inspect(db, fixture, AT+timedelta(seconds=12))
        assert not report['usable_parent_observation_ids']


def test_mapping_changes_and_failed_jobs_reject_histories(store):
    fixture_id = collect(store)
    with store.begin() as db:
        raw = db.scalar(select(m.Observation).where(m.Observation.payload['section'].as_string() == 'team_recent_results'))
        db.get(m.FixtureDiscoveryJob, raw.payload['job_id']).status = 'DEAD'
        report, _ = bridge.inspect(db, db.get(m.Fixture, fixture_id), AT+timedelta(seconds=12))
        assert 'successful provider collection job' in report['reason']
        assert len(report['usable_parent_observation_ids']) == 1


def test_fixture_only_evidence_creates_actionable_partial_dossier(store):
    acquire(store, providers.SPORTSDB_ID, {'kind': 'day'}, {'events': [raw_sportsdb(idHomeTeam='10', idAwayTeam='20')]})
    with store.begin() as db:
        fixture_id = db.scalar(select(m.Fixture.id))
        with pytest.raises(Waiting) as exc:
            research(db, SimpleNamespace(fixture_id=fixture_id), AT+timedelta(seconds=4))
        assert 'no completed-match history' in str(exc.value)
        assert exc.value.details['research_readiness']['providers'][1]['mapped'] is True
        dossier = db.scalar(select(m.Research))
        assert dossier.status == 'PARTIAL' and dossier.evidence_ids == []
        assert dossier.sections['recent_form']['status'] == 'PENDING'


def test_registering_both_groups_does_not_promote_matching_samples(store, monkeypatch):
    fixture_id = collect(store)
    with store.begin() as db:
        fixture = db.get(m.Fixture, fixture_id)
        bridge.assemble(db, fixture, AT+timedelta(seconds=12))
        derived = [o for o in db.scalars(select(m.Observation)) if o.payload.get('producer') == bridge.PRODUCER]
        for obs in derived:
            db.add(m.Observation(source_id=providers.OL_ID, fixture_id=fixture_id, content_hash='copied-'+obs.content_hash[:55],
                observed_at=obs.observed_at, payload=obs.payload))
        # Even an explicit policy cannot turn the discovery collector's partial
        # coverage into a model-ready window.
        monkeypatch.setenv('SPORTS_RESEARCH_QUORUM_JSON', '{}')
        with pytest.raises(Waiting):
            research(db, SimpleNamespace(fixture_id=fixture_id), AT+timedelta(seconds=12))
        dossier = db.scalar(select(m.Research).order_by(m.Research.version.desc()))
        assert dossier.status == 'PARTIAL'
        assert dossier.sections['recent_form']['status'] == 'PROVISIONAL'


@pytest.mark.parametrize('change', [
    {'home_score': True}, {'home_score': -1}, {'home': 'Wrong team'},
    {'kickoff_at': AT.isoformat()}, {'kickoff_at': '2026-11-17T10:00:00'},
])
def test_invalid_samples_are_rejected_without_inferred_coverage(change):
    fixture = SimpleNamespace(home_name='Home', away_name='Away', kickoff_at=AT+timedelta(days=1))
    row = {'event_id': '1', 'home': 'Home', 'away': 'Opponent', 'home_score': 2, 'away_score': 1,
           'kickoff_at': (AT-timedelta(days=1)).isoformat(), **change}
    with pytest.raises(ValueError):
        bridge.normalized_results({'side': 'home', 'team': 'Home', 'results': [row]}, fixture, AT)


def test_duplicate_matches_do_not_inflate_sample_size():
    fixture = SimpleNamespace(home_name='Home', away_name='Away', kickoff_at=AT+timedelta(days=1))
    row = {'event_id': '1', 'home': 'Home', 'away': 'Opponent', 'home_score': 2, 'away_score': 1,
           'kickoff_at': (AT-timedelta(days=1)).isoformat()}
    with pytest.raises(ValueError, match='Duplicate'):
        bridge.normalized_results({'side': 'home', 'team': 'Home', 'results': [row, {**row, 'event_id': '2'}]}, fixture, AT)


def test_derived_freshness_keeps_an_old_team_sample_stale():
    from app.modules.research.deep_workspace_routes import form_freshness
    payload={'producer':bridge.PRODUCER,'data':{'samples':{
        'home':[{'kickoff_at':(AT-timedelta(days=45)).isoformat()}],
        'away':[{'kickoff_at':(AT-timedelta(days=2)).isoformat()}]}}}
    status,latest=form_freshness(payload,AT,AT)
    assert status=='STALE' and latest==AT-timedelta(days=45)
