"""Explicit source-backed prices for controlled qualification test scenarios."""
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc


def attach_price_evidence(db, source_id='source', exclude=()):
    db.flush()
    for quote in db.scalars(select(m.Odds)):
        if quote.id in exclude: continue
        existing=db.get(m.MarketEvidence,quote.id)
        if existing:
            original=db.get(m.Observation,existing.observation_id)
            if original and original.source_url=='https://provider.example/test-price':continue
        observation = m.Observation(source_id=source_id, fixture_id=quote.fixture_id,
            content_hash=quote.id.ljust(64, '0')[:64], observed_at=quote.observed_at,
            source_url='https://provider.example/test-price',
            payload={'section': 'market_odds', 'data': {'prices' if quote.market_key=='1X2' else 'other_prices': [{
                'bookmaker': quote.bookmaker, 'market_key': quote.market_key,
                'outcome_key': quote.outcome_key, 'decimal_odds': float(quote.decimal_odds),
                'observed_at': utc(quote.observed_at).isoformat()}]}})
        db.add(observation); db.flush()
        proof = db.get(m.MarketEvidence, quote.id)
        if proof: proof.observation_id = observation.id
        else: db.add(m.MarketEvidence(odds_id=quote.id, observation_id=observation.id, source_id=source_id))
