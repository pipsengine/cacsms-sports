# Cacsms Sports v3.8 — Programme allocation, PAPER tickets, monitoring and results

## Actual connections

- `app.modules.strategies.automation.allocate_paper`: uses only persisted `QUALIFIED` decisions with six PASS gates, approved/calibrated models, future fixtures and odds at most 15 minutes old. Calls the existing deterministic optimizer and `prepare_paper_ticket` transactionally; enforces programme daily caps and existing signatures. Runs in the `pipeline.drive` worker through `connect_engines`.
- `app.modules.tickets.service.prepare_paper_ticket`: persists tickets, ticket legs, betslips and internal PAPER verification. No real money and no bookmaker booking-code claim.
- `app.modules.markets.monitoring.inspect_market`: compares latest persisted bookmaker odds by fixture/market/outcome, identifies stale prices and changed prices. Read-only endpoint: `GET /api/v1/sports/pipeline/fixtures/{fixture_id}/market-monitor`. Monitoring is explicitly **not externally verified**; it does not satisfy the workflow's independent monitor gate.
- `app.modules.acquisition`: allows `official_result` only as a separately validated post-kickoff observation. The feed must be explicitly configured in `SPORTS_SOURCE_FEEDS_JSON`, source authorized, fixture ID exact, JSON envelope `section=official_result`, and `data` containing `status=FINAL` and market outcomes. Existing `results.reconcile` Celery task converts observations to versioned results and prediction settlements.
- `connect_engines` queues final-result acquisition for post-kickoff fixtures, and calls `reconcile_pending`. Prior to kickoff, it runs qualification, allocation, PAPER preparation and market inspection.

## Critical operating constraints

1. No official source feed is bundled. Configure a permitted, independent source; do not infer official results from prices or fixtures.
2. No real SportyBet booking-code provider is bundled. The Verify stage remains WAITING_FOR_DATA until genuine provider-backed evidence exists.
3. Market inspection is based on stored odds only, not an independently authenticated continuous monitoring feed; the Monitor stage remains WAITING_FOR_DATA.
4. The sequential 12-stage ledger therefore cannot be reported as fully VERIFIED without these integrations. Post-event reconciliation can occur independently of the ledger's earlier missing booking-code stage.
5. Accumulator/draw/jackpot generation may legitimately return zero proposals. Multi-leg probability correlation remains unverified; no guaranteed returns.
6. Existing approved-model and independently verified dossier prerequisites remain mandatory. No invented fixture, prediction, odds or results.

## Testing

20 selected tests pass with `DATABASE_URL=sqlite+pysqlite:///:memory:`; this validates pure and mocked behavior only. PostgreSQL migration, Docker, frontend build, live source acquisition, production scheduling and end-to-end deployment have **not** been verified in this environment. A live PostgreSQL integration test is required before production readiness can be claimed.

## Deployment

See README and previous release notes. Configure `.env`, authorized source IDs and HTTPS feed URLs, run migrations, start API/worker/beat/PostgreSQL/Redis, then run smoke checks. Keep `EXECUTION_MODE=PAPER`.
