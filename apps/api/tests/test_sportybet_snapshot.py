from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models as m
from app.db.base import Base
from app.modules.acquisition.service import ingest_observation
from app.modules.acquisition.sportybet_snapshot import SnapshotError, parse_snapshot
from app.modules.markets.odds_intelligence import assess
from app.modules.pipeline.operations import import_prices


AT = datetime.now(timezone.utc) - timedelta(minutes=1)


def snapshot():
    return {'data': {'tournaments': [{'id': 'league-test', 'name': 'Test League',
        'categoryName': 'Test Country', 'events': [{
            'eventId': 'event-test', 'homeTeamName': 'Test Home', 'awayTeamName': 'Test Away',
            'estimateStartTime': int((AT + timedelta(days=1)).timestamp() * 1000),
            'markets': [{'status': 0, 'desc': '1X2', 'outcomes': [
                {'isActive': 1, 'desc': 'Home', 'odds': '2.10'},
                {'isActive': 1, 'desc': 'Draw', 'odds': '3.20'},
                {'isActive': 0, 'desc': 'Away', 'odds': '4.00'},
            ]}]}]}]}}


def test_snapshot_extracts_unverified_fixture_and_active_prices():
    result = parse_snapshot(snapshot(), sport='Football', observed_at=AT)
    fixture = result['fixtures'][0]
    assert result['rejected'] == []
    assert (fixture['provider_event_id'], fixture['competition_id'], fixture['status']) == (
        'event-test', 'league-test', 'UNVERIFIED')
    assert (fixture['home'], fixture['away']) == ('Test Home', 'Test Away')
    assert [(p['outcome_key'], p['decimal_odds']) for p in fixture['prices']] == [
        ('HOME', '2.10'), ('DRAW', '3.20')]
    assert all(p['observed_at'] == AT.isoformat() for p in fixture['prices'])


def test_rejects_bad_identity_and_conflicting_duplicates_without_inventing_data():
    payload = snapshot()
    events = payload['data']['tournaments'][0]['events']
    duplicate = deepcopy(events[0])
    duplicate['awayTeamName'] = 'Different Away'
    events.append(duplicate)
    invalid = deepcopy(events[0])
    invalid.update(eventId='missing-time', estimateStartTime=None)
    events.append(invalid)
    result = parse_snapshot(payload, sport='Football', observed_at=AT)
    assert result['fixtures'] == []
    assert {row['reason'] for row in result['rejected']} == {'DUPLICATE_EVENT_ID', 'INVALID_KICKOFF'}


def test_unsupported_markets_invalid_prices_and_ambiguous_outcomes_are_not_mapped():
    payload = snapshot()
    markets = payload['data']['tournaments'][0]['events'][0]['markets']
    markets[0]['outcomes'].extend([
        {'isActive': 1, 'desc': 'Home', 'odds': '2.25'},
        {'isActive': 1, 'desc': 'Away', 'odds': 'NaN'},
    ])
    markets.append({'status': 0, 'desc': '1st Half 1X2',
                    'outcomes': [{'isActive': 1, 'desc': 'Away', 'odds': '3.00'}]})
    result = parse_snapshot(payload, sport='Football', observed_at=AT)
    assert [row['outcome_key'] for row in result['fixtures'][0]['prices']] == ['DRAW']
    assert {row['reason'] for row in result['rejected']} == {'DUPLICATE_OUTCOME', 'INVALID_ODDS'}
    assert parse_snapshot(payload, sport='Ice Hockey', observed_at=AT)['fixtures'][0]['prices'] == []
    with pytest.raises(SnapshotError, match='CAPTURE_TIME_TIMEZONE_REQUIRED'):
        parse_snapshot(payload, sport='Football', observed_at=AT.replace(tzinfo=None))
    with pytest.raises(SnapshotError, match='INVALID_TOURNAMENTS'):
        parse_snapshot({'data': {}}, sport='Football', observed_at=AT)


def test_fixture_survives_missing_or_closed_markets_without_prices():
    payload = snapshot()
    event = payload['data']['tournaments'][0]['events'][0]
    event['markets'][0]['status'] = 1
    result = parse_snapshot(payload, sport='Football', observed_at=AT)
    assert len(result['fixtures']) == 1 and result['fixtures'][0]['prices'] == []
    del event['markets']
    result = parse_snapshot(payload, sport='Football', observed_at=AT)
    assert len(result['fixtures']) == 1 and result['fixtures'][0]['prices'] == []
    assert result['rejected'][0]['reason'] == 'INVALID_MARKETS'


def test_controlled_snapshot_can_flow_through_existing_evidence_gates():
    engine = create_engine('sqlite://', poolclass=StaticPool,
        execution_options={'schema_translate_map': {t.schema: None for t in Base.metadata.tables.values()}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    candidate = parse_snapshot(snapshot(), sport='Football', observed_at=AT)['fixtures'][0]
    with factory.begin() as db:
        db.add(m.Sport(id='sport', name='Football'))
        db.add(m.Source(id='test-source', name='Synthetic test source', enabled=True, permission='AUTHORIZED'))
        db.flush()
        db.add(m.Competition(id='league', sport_id='sport', name='Test League'))
        db.flush()
        db.add(m.Fixture(id='fixture', competition_id='league', home_name=candidate['home'],
                         away_name=candidate['away'], kickoff_at=datetime.fromisoformat(candidate['kickoff_at'])))
        db.flush()
        kwargs = dict(source_id='test-source', fixture_id='fixture', section='market_odds',
                      source_url='https://test.example/snapshot', observed_at=AT,
                      payload={'prices': candidate['prices']})
        first = ingest_observation(db, **kwargs)
        assert ingest_observation(db, **kwargs)['id'] == first['id']
        import_prices(db, 'fixture', AT)
        import_prices(db, 'fixture', AT)
        quotes = db.scalars(select(m.Odds)).all()
        assert len(quotes) == 2 and all(assess(db, quote, AT)['eligible'] for quote in quotes)
        db.get(m.Source, 'test-source').permission = 'UNVERIFIED'
        db.flush()
        assert all('SOURCE_NOT_AUTHORIZED' in assess(db, quote, AT)['rejection_reasons'] for quote in quotes)
    engine.dispose()
