"""Shared, fail-closed classification over canonical odds and immutable source evidence.

Collection time never refreshes a provider price. Existing provider, observation,
catalogue and snapshot tables remain the system of record.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from sqlalchemy import select
from app.db import models as m
from app.modules.acquisition.source_policy import prohibition
from app.modules.research.league import utc

FRESHNESS = timedelta(minutes=15)
CLASSIFICATIONS = ('HISTORICAL', 'RESEARCH_SNAPSHOT', 'FRESH_MARKET')


def record_assessment(db, quote, at=None):
    result = assess(db, quote, at)
    db.add(m.OddsQualityAssessment(odds_id=quote.id, observation_id=result['observation_id'],
        assessed_at=at or datetime.now(timezone.utc), classification=result['classification'],
        eligible=result['eligible'], reasons=result['rejection_reasons']))
    return result


def assess(db, quote, at=None):
    at = utc(at or datetime.now(timezone.utc))
    stamp = utc(quote.observed_at)
    age = (at - stamp).total_seconds()
    fixture = db.get(m.Fixture, quote.fixture_id)
    proof = db.get(m.MarketEvidence, quote.id)
    observation = db.get(m.Observation, proof.observation_id) if proof else None
    source = db.get(m.Source, proof.source_id) if proof else None
    reasons = []
    payload = observation.payload or {} if observation else {}
    data = payload.get('data') if isinstance(payload.get('data'),dict) else {}
    declared = payload.get('classification') or data.get('classification')
    historical = payload.get('section') == 'market_odds_archive' or declared == 'HISTORICAL' or (fixture is not None and utc(fixture.kickoff_at) <= at)
    if historical: reasons.append('HISTORICAL_PRICE')
    if declared == 'RESEARCH_SNAPSHOT': reasons.append('RESEARCH_ONLY_PRICE')
    if source is None or source.permission != 'AUTHORIZED' or not source.enabled:
        reasons.append('SOURCE_NOT_AUTHORIZED')
    if source and (source.name.casefold() == 'betexplorer' and prohibition('betexplorer.com')):
        reasons.append('SOURCE_PROHIBITED')
    if observation and prohibition(urlsplit(observation.source_url or '').hostname):
        reasons.append('SOURCE_PROHIBITED')
    if observation is None:
        reasons.append('MISSING_PROVENANCE')
    elif observation.source_id != proof.source_id or observation.fixture_id != quote.fixture_id:
        reasons.append('PROVIDER_OR_FIXTURE_MISMATCH')
    elif stamp > utc(observation.observed_at):
        reasons.append('PRICE_AFTER_SOURCE_OBSERVATION')
    if fixture is None: reasons.append('FIXTURE_UNMAPPED')
    if age < 0: reasons.append('FUTURE_PRICE')
    elif age > FRESHNESS.total_seconds(): reasons.append('STALE_PRICE')
    display_price = None
    try:
        price = Decimal(str(quote.decimal_odds))
        if price.is_finite(): display_price = float(price)
        if not price.is_finite() or not 1 < price <= 1000: raise ValueError()
    except (InvalidOperation, ValueError, TypeError): reasons.append('INVALID_DECIMAL_ODDS')
    # A source's exact market/outcome observation verifies mapping, without inferring
    # that a free fixture/results feed supplies any odds.
    prices = []
    for key in ('prices','other_prices'):
        if isinstance(data.get(key),list):prices.extend(data[key])
    matching = [row for row in prices if isinstance(row, dict) and row.get('bookmaker') == quote.bookmaker and
               row.get('market_key') == quote.market_key and row.get('outcome_key') == quote.outcome_key
               ]
    if not matching:
        reasons.append('MARKET_MAPPING_UNVERIFIED')
    else:
        verified = False
        for row in matching:
            try:
                provider_stamp = datetime.fromisoformat(row['observed_at'].replace('Z', '+00:00'))
                if provider_stamp.tzinfo is not None and utc(provider_stamp) == stamp and Decimal(str(row['decimal_odds'])) == Decimal(str(quote.decimal_odds)):
                    verified = True
            except (KeyError, ValueError, TypeError, InvalidOperation):
                pass
        if not verified: reasons.append('PROVIDER_PRICE_OR_TIMESTAMP_MISMATCH')
    conflict = db.scalar(select(m.Odds.id).where(
        m.Odds.fixture_id == quote.fixture_id, m.Odds.bookmaker == quote.bookmaker,
        m.Odds.market_key == quote.market_key, m.Odds.outcome_key == quote.outcome_key,
        m.Odds.observed_at == quote.observed_at, m.Odds.decimal_odds != quote.decimal_odds).limit(1))
    if conflict: reasons.append('CONFLICTING_QUOTES')
    classification = 'HISTORICAL' if historical else 'FRESH_MARKET' if not reasons else 'RESEARCH_SNAPSHOT'
    return {'odds_id': quote.id, 'fixture_id': quote.fixture_id, 'bookmaker': quote.bookmaker,
            'market_key': quote.market_key, 'outcome_key': quote.outcome_key,
            'decimal_odds': display_price, 'classification': classification,
            'eligible': not reasons, 'rejection_reasons': list(dict.fromkeys(reasons)),
            'observed_at': stamp, 'age_seconds': age, 'freshness_limit_seconds': 900,
            'source_id': source.id if source else None, 'provider': source.name if source else None,
            'observation_id': observation.id if observation else None,
            'source_url': observation.source_url if observation else None, 'mode': 'PAPER'}
