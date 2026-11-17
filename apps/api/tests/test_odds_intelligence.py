from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import models as m
from app.modules.markets.odds_intelligence import assess
from app.modules.markets import odds_routes
from app.modules.governance.history import evaluation_history
from test_market_scanner import store


def test_freshness_boundary_and_recent_import_cannot_refresh_price(store):
    factory, at = store
    with factory.begin() as db:
        quote = db.scalar(select(m.Odds))
        assert assess(db, quote, at)['eligible']
        assert assess(db, quote, at + timedelta(minutes=10))['eligible']
        assert 'STALE_PRICE' in assess(db, quote, at + timedelta(minutes=10, microseconds=1))['rejection_reasons']
        proof = db.get(m.MarketEvidence, quote.id)
        db.get(m.Observation, proof.observation_id).observed_at = at + timedelta(hours=1)
        assert not assess(db, quote, at + timedelta(minutes=11))['eligible']


def test_historical_research_prohibited_and_unmapped_fail_closed(store):
    factory, at = store
    with factory.begin() as db:
        quote = db.scalar(select(m.Odds))
        proof = db.get(m.MarketEvidence, quote.id)
        observation = db.get(m.Observation, proof.observation_id)
        for classification in ('HISTORICAL', 'RESEARCH_SNAPSHOT'):
            observation.payload = {**observation.payload, 'classification': classification}
            result = assess(db, quote, at)
            assert result['classification'] == classification and not result['eligible']
        observation.payload = {'section': 'market_odds', 'data': {}}
        assert 'MARKET_MAPPING_UNVERIFIED' in assess(db, quote, at)['rejection_reasons']
        source = db.get(m.Source, 'source')
        source.name = 'BetExplorer'
        assert 'SOURCE_PROHIBITED' in assess(db, quote, at)['rejection_reasons']


def test_conflicts_and_provider_identity_quarantined(store):
    factory, at = store
    with factory.begin() as db:
        quote = db.scalar(select(m.Odds))
        db.add(m.Odds(fixture_id=quote.fixture_id, bookmaker=quote.bookmaker,
                      market_key=quote.market_key, outcome_key=quote.outcome_key,
                      decimal_odds=float(quote.decimal_odds)+1, observed_at=quote.observed_at))
        assert 'CONFLICTING_QUOTES' in assess(db, quote, at)['rejection_reasons']
        observation = db.get(m.Observation, db.get(m.MarketEvidence, quote.id).observation_id)
        observation.fixture_id = None
        assert 'PROVIDER_OR_FIXTURE_MISMATCH' in assess(db, quote, at)['rejection_reasons']


def test_versioned_api_pagination_validation_and_missing_quote(store, monkeypatch):
    factory, at = store
    monkeypatch.setattr(odds_routes, 'SessionLocal', factory)
    app = FastAPI(); app.include_router(odds_routes.router)
    client = TestClient(app)
    assert client.get('/api/v1/sports/odds-intelligence/observations?limit=0').status_code == 422
    assert client.get('/api/v1/sports/odds-intelligence/observations?classification=INVALID').status_code == 422
    result = client.get('/api/v1/sports/odds-intelligence/observations?limit=2').json()
    assert result['scanned'] == 2 and result['next_offset'] == 2 and result['mode'] == 'PAPER'
    assert client.get('/api/v1/sports/odds-intelligence/eligibility/missing').status_code == 404


def test_evaluation_history_only_returns_persisted_data(store):
    factory, at = store
    with factory.begin() as db:
        assert evaluation_history(db, 'active')['evaluations'] == []
        db.add(m.ModelGovernanceSnapshot(model_id='active', status='BLOCKED',
               reasons=['INSUFFICIENT_RECENT_SAMPLE'], reference={}, recent={'count': 5, 'brier': .2}, created_at=at))
    with factory() as db:
        result = evaluation_history(db, 'active')
        row = result['evaluations'][0]
        assert row['sample_size'] == 5 and row['brier_score'] == .2
        assert row['dataset'] is None and row['approval_status'] is None
        assert result['actual_deployment_status'] == 'UNVERIFIED'


def test_source_profile_cannot_override_authorization(store, monkeypatch):
    factory, at = store
    monkeypatch.setattr(odds_routes, 'SessionLocal', factory)
    monkeypatch.setenv('SPORTS_ADMIN_TOKEN', 'test-admin')
    app = FastAPI(); app.include_router(odds_routes.router)
    client = TestClient(app)
    path = '/api/v1/sports/odds-intelligence/sources/source/profile'
    payload = {'source_type': 'CSV', 'collection_method': 'PUBLISHED_CSV', 'sports': ['football'],
               'classifications': ['HISTORICAL', 'RESEARCH_SNAPSHOT'], 'expected_update_seconds': 1800}
    assert client.put(path, json=payload).status_code == 403
    headers = {'X-Admin-Token': 'test-admin'}
    assert client.put(path, json={**payload, 'permission': 'AUTHORIZED'}, headers=headers).status_code == 422
    with factory.begin() as db:
        db.get(m.Source, 'source').permission = 'PROHIBITED'
    assert client.put(path, json=payload, headers=headers).status_code == 200
    with factory() as db:
        assert db.get(m.Source, 'source').permission == 'PROHIBITED'
        assert db.scalar(select(m.AuditEvent)).payload['authorization_changed'] is False
