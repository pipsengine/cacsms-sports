# CACSMS Sport AI 2.4 — Challenger model validation

Adds pure-Python logistic-regression binary challenger training, six-feature typed contract, chronological 70/30 holdout, train-only standardization, baseline Brier/log-loss comparison, reliability bins, prospective governance boundaries and read-only validation/preview endpoints.

## Endpoints
- POST /api/v1/sports/admin/models/challengers (admin token required)
- GET /api/v1/sports/models/{id}/validation
- GET /api/v1/sports/models/feature-contract
- GET /api/v1/sports/models/{model_id}/preview/{feature_id}

## Important limitations
This is a research-grade binary baseline, **not a validated sports prediction system**. It cannot train without genuine, independently labeled historical examples. It does not generate data, scrape sources, activate models, claim a betting edge or place bets. Model previews require ACTIVE status, and this release deliberately provides **no model-activation endpoint**. Independent forward testing, model approval, sport/market-specific outcomes, richer features and calibration remain necessary.

## Testing
`cd apps/api && python -m pytest tests/test_prediction_pipeline.py -q`
