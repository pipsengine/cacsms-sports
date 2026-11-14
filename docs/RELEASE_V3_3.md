# Cacsms Sport AI 3.3 — Integration and readiness hardening

## Changes
- Repaired the Alembic revision chain: 0003 now correctly points to 0002.
- Prevented the baseline migration from creating result-evidence, browser-capture and governance tables reserved for later migrations.
- Added an explicit fail-closed `/api/v1/sports/readiness` endpoint, distinct from API liveness.
- Added a live readiness panel to the Dashboard.
- Propagated Redis and PAPER execution mode to the API and worker services.
- Added GitHub CI PostgreSQL migration execution and idempotent migration check.
- Added offline release-integrity tests and a deployment HTTP verification script.

## Known limitations (do not mark as complete)
- Docker and PostgreSQL startup have NOT been verified in the authoring environment.
- Authorized live data sources and vision credentials are not configured.
- Actual vision inference, trained independently approved models and end-to-end prediction/booking remain unverified.
- The readiness endpoint intentionally returns `ready_for_autonomous_predictions=false` until independently established. It does not treat a model registry entry as approval.
- This is a stabilization increment, not a verified production release.

## Run
`docker compose up --build -d`
`sh scripts/verify_release.sh`
`cd apps/api && alembic upgrade head`
`pytest -q tests/test_release_integrity.py`

## Security
No paid wager submission was introduced. Do not use default development credentials in a public deployment.
