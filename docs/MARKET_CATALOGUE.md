# Bookmaker market catalogue, availability discovery and AI market scanning

## Three separate layers (never conflated)

| Layer | Table(s) | Source | Shown as |
|---|---|---|---|
| Registered definitions | `markets.market_categories`, `market_definitions`, `market_outcomes` | `app/modules/markets/catalogue_data.py` (433 definitions, 16 sports + 14 discovery-only sports), seeded idempotently by the autonomy cycle and on first API read | `REGISTERED` - the platform understands the market type. **Not** a claim that any bookmaker offers it. |
| Observed availability | `bookmaker_market_availability` (+ existing `odds_snapshots`, `odds_evidence`) | only authorized, evidence-backed odds snapshots | `AVAILABLE` / `FRESH` (≤15 min) / `STALE`; `UNAVAILABLE` when a market disappears from a bookmaker's newer batch; unknown source keys become `DISCOVERED` definitions |
| AI evaluation | `market_model_capabilities`, `market_scan_runs`, `market_scan_results` | existing gates: `market_scanner.service.evaluate` → `markets.service.evaluate_market`, plus lower-bound EV | `MODEL_SUPPORTED`, `EVALUATED`, `QUALIFIED`, `UNSUPPORTED` |

Source market keys map to canonical definitions through `bookmaker_market_mappings` (`1X2`, `OU_<line>`, `AH_<line>`, `BTTS`, `DC`, `DNB`, `CS`, `HT1X2`, `HTFT`, `EH_<line>`, ...). Source-specific keys are preserved on availability rows.

## Pipeline integration (no new orchestrator)

- **Discover/Acquire**: odds collectors (currently Football-Data.co.uk) store snapshots + evidence; availability is synchronised from them.
- **Evaluate** (`pipeline/operations.evaluate`): runs `catalogue.scan` for the fixture in an isolated savepoint, throttled to once per 5 minutes unless odds changed.
- **Qualify** and later stages are unchanged: approval, calibration, freshness and research gates still decide.

Probabilities are attached only where an ACTIVE, approved model has a recorded capability for that exact market/outcome/line
(today: Full Time Result → HOME from the binary home-win model). Every other offered market is `UNSUPPORTED` with reason
`NO_APPROVED_MODEL_FOR_MARKET`; no forecast is invented. Ranking (best-fit): qualified first, then probability lower bound,
lower-bound expected value and probability; a high probability at a negative-EV price never qualifies. Outcomes qualifying
in the same fixture are flagged with a `correlation_group`.

## API (`/api/v1/sports/markets`)

`GET catalogue`, `categories`, `sports/{sport_id}`, `fixtures/{id}`, `fixtures/{id}/availability`, `/odds`, `/coverage`,
`/evaluations`, `/best-fit`, `sources/health`, `scans`, `scans/{scan_id}`; `POST scans` and `POST sync` require `X-Admin-Token`.

## Limits

- No SportyBet feed is permitted, so no market is shown as offered by SportyBet. BetExplorer remains prohibited by its terms (see AUTONOMOUS_OPERATION.md).
- Player markets are registered definitions only: no permitted player-level source exists, so no `players` table is populated.
- Live markets are registered but not collected (no permitted live feed).

Tests: `apps/api/tests/test_market_catalogue.py`; UI: `scripts/verify_predictions_ui.py`.
