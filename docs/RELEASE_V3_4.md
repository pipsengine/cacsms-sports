# V3.4 — Twelve-stage operational workflow

Added durable operations.pipeline_runs and operations.pipeline_stages, migration 0007, authenticated PAPER-mode run creation, read endpoints, stage evaluation ledger, and a responsive workflow dashboard on Dashboard, Command Centre and Engine Orchestrator.

## Endpoints
- GET `/api/v1/sports/pipeline/definitions`
- GET `/api/v1/sports/pipeline/runs`
- GET `/api/v1/sports/pipeline/runs/{id}`
- POST `/api/v1/sports/pipeline/runs` (X-Admin-Token)
- POST `/api/v1/sports/pipeline/runs/{id}/evaluate` (X-Admin-Token)

## Important limitations
Evidence IDs supplied by an API client are untrusted. The evaluate endpoint records submitted claims for inspection but **never marks a stage VERIFIED based on those claims**. True automatic advancement requires server-side adapters to verify source observations, approved models, market prices and official results against PostgreSQL and their original providers. This release does not invent such evidence or fabricate a successful run. No real-money execution is available. Docker/PostgreSQL/frontend startup are not verified by the isolated test environment.

## Acceptance criteria
- All twelve stages have persistent input, output, evidence, timing, retry and error fields.
- Failed or missing upstream evidence stops downstream progression.
- Status colors and expanded details are visible on desktop and mobile.
- API routes precede the generic catchall.
- No client-supplied evidence can mark a stage verified.
