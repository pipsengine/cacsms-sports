# Version 3.5 — Evidence-backed pipeline execution

## Added
- `pipeline/executor.py`: read-only resolver that checks actual PostgreSQL fixture, authorized source, observation, verified dossier, cutoff-safe feature, approved model, prediction, fresh market, qualification, programme, ticket, booking-code and official result records.
- `POST /api/v1/sports/pipeline/runs/{run_id}/execute`: authenticated, PAPER-only evidence-derived evaluation.
- Celery beat `pipeline.recheck` every 60 seconds; scans up to 50 waiting runs with database row locks and re-evaluates only persisted evidence.
- Audit event per execution; status and timings per stage.

## Important limitations
- Evidence presence is not independent model quality validation. The pipeline checks the existing approval fields, which require independent governance processes.
- No authorized external fixture provider, actual vision inference, bookmaker code verification adapter or independent monitoring service is configured by this release.
- The pipeline stops at the first missing mandatory input; later stages cannot be green by assertion.
- The legacy `/evaluate` route records untrusted client claims but cannot use them to verify evidence.
- This is not a verified live production deployment.

## Usage
1. Configure PostgreSQL, Redis and PAPER mode, and run migrations.
2. Create a pipeline run with an actual fixture ID.
3. Trigger `POST /api/v1/sports/pipeline/runs/{id}/execute` using `x-admin-token`.
4. Inspect `GET /api/v1/sports/pipeline/runs/{id}` for evidence, stage status and errors.
5. Run Celery worker and beat for 60-second periodic rechecks.

## Security
No paid wager submission exists in this module. Do not use pipeline status as a guarantee of predictive accuracy or bookmaker acceptance.
