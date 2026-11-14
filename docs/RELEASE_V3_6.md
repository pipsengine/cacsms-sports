# Cacsms Sport AI 3.6 — Real engine connections (PAPER-only)

## Implemented
- `pipeline/engine.py` orchestrates existing authorized feed acquisition jobs, research dossiers, feature snapshots, and persisted qualification evaluations. It does not create synthetic fixtures, scores, forecasts, prices, betting codes, or result evidence.
- `POST /api/v1/sports/pipeline/runs/{id}/drive` requires administrator authorization and PAPER mode; locks the run, calls existing services, re-evaluates evidence-derived gates, writes audit events, and dispatches durable acquisition jobs after committing.
- `pipeline.drive` scheduled Celery task processes up to 25 waiting runs every 120 seconds. Existing `pipeline.recheck` remains scheduled every 60 seconds.
- Missing sections can enqueue authorized JSON feed acquisition jobs only when `SPORTS_SOURCE_FEEDS_JSON` contains an explicit source ID and section mapping. No unrestricted scraping is introduced.
- Automatic research dossiers are PARTIAL, never independently VERIFIED. Existing verified dossiers can produce cutoff-safe feature snapshots.
- Market qualifications use the existing server-side qualification engine, approved active models, matching market keys, and odds no older than 15 minutes. Repeated decisions are not duplicated for the same prediction/price pair.
- Evidence resolver now checks model status `ACTIVE` with explicit independent approval/calibration fields, consistent with the market service, and evaluates only the six mandatory qualification gates (not diagnostic metadata).
- Every missing external capability is reported as blocked/waiting; downstream stages stay unverified.

## How to operate
1. Configure PostgreSQL and Redis and apply Alembic migrations.
2. Set `EXECUTION_MODE=PAPER`, `ADMIN_API_TOKEN`, and `SPORTS_SOURCE_FEEDS_JSON` for administrator-approved source/section endpoints. The feed response must contain the exact fixture ID and research section.
3. Create a run with `POST /api/v1/sports/pipeline/runs`, passing an existing fixture ID.
4. Trigger `POST /api/v1/sports/pipeline/runs/{id}/drive` with `x-admin-token`; review `engine_report`, including queued jobs and explicit blockers.
5. Start Celery worker and beat to process acquisition and retry waiting runs.
6. Review `GET /api/v1/sports/pipeline/runs/{id}` and audit events. Never interpret missing stages as passed.

## Not yet proven / not implemented
- No real PostgreSQL instance, Docker, frontend build or production website was available for integration validation in this environment.
- No autonomous fixture discovery connector has been authorized/configured.
- No independently approved prediction inference adapter is wired to generate new model forecasts. Predictions are only read from existing persisted evidence.
- No genuine bookmaker booking-code creation or verification connector, external monitoring evidence provider or official results provider is connected.
- Automatic dossiers intentionally require independent verification before downstream model use.
- No real-money betting or account automation is included.

## Local validation
- Python compilation passed.
- 18 selected tests passed (4 new workflow tests + 14 existing prediction/market tests).
- Full suite collection blocked by missing `psycopg` driver; live PostgreSQL migrations and browser smoke tests not run.
