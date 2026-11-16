# AI Predictions & Market Scanner (cacsms-market-scanner patch, integrated)

Source: `cacsms-market-scanner` (standalone FastAPI app + React preview with its own `ms_*` tables).
Per that patch's own guidance ("mount within the existing shell", "no duplicate pipeline"), it was adapted onto
canonical records instead of shipping a second database/app:

| Patch concept | Canonical implementation |
|---|---|
| `ms_markets` catalogue | distinct `markets.odds_snapshots` market keys per bookmaker, grouped into families |
| `ms_quotes` | `markets.odds_snapshots` (+ `markets.odds_evidence`), ingested via existing admin odds intake |
| `ms_estimates` | `predictions.forecasts` of `ACTIVE` models; interval from `details.interval` |
| `/evaluate` | existing `markets.service.evaluate_market` gates + patch's lower-bound EV and ranking (read-only, not persisted) |
| `ingest` with token | not duplicated; existing `POST /api/v1/sports/admin/markets/odds` (admin token) |

No SportyBet scraper, account automation or bet placement is included.

## API
- `GET /api/v1/sports/market-scanner/catalog?bookmaker=`
- `GET /api/v1/sports/market-scanner/fixtures/{fixture_id}?as_of=&bookmaker=`

## Page (`/sports/predictions`)
Discovered catalogue (categories, search, per-viewer market selection), fixture banner, Match Outcome (1X2),
Top Model Selections, Key Metrics, AI Insight & Verdict; tabs for markets, probability analysis, models,
evidence and history.

Deliberate differences from the design image:
- "Market Coverage 100%" → **Modelled Coverage** (share of discovered selections with an ACTIVE-model forecast); bookmaker inventory completeness is unverified.
- "Model Accuracy" → **Model Brier (Holdout)**; models store holdout Brier/log-loss, not accuracy.
- "Recommended Selections" → **Top Model Selections** with qualified/rejected status; qualification is a paper-review flag, not betting advice.
- KPI deltas ("↑ +327") omitted: no historical KPI series is stored.
- Today the prospective model writes only `1X2/HOME`; other markets show once a model publishes them.

Tests: `apps/api/tests/test_market_scanner.py`; UI: `scripts/verify_predictions_ui.py` (mocked responses).
