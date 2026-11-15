# CACSMS SPORTS

A runnable **paper-only foundation** for the proposed sports intelligence platform. Includes 29 responsive navigation pages, React/Vite frontend, FastAPI read-only API, PostgreSQL schemas and Alembic migration, qualification gate tests, Docker Compose and engine/worker contracts. **Not a completed autonomous research/prediction/booking implementation.** See `docs/IMPLEMENTATION_STATUS.md` for explicit gaps.

## Quick start (Docker required)
1. Install Docker Engine/Desktop and Docker Compose v2.
2. Copy `.env.example` to `.env` and change `POSTGRES_PASSWORD`.
3. Run `docker compose up --build -d` from repository root.
4. Open **http://localhost:8080** (web), **http://localhost:8000/docs** (API), and **http://localhost:8000/health** (status).
5. If migration fails, inspect `docker compose logs api postgres`. No historical data is imported.

## Local development
- Start PostgreSQL 17 and create database/user, set `DATABASE_URL` appropriately.
- API: `cd apps/api && pip install -r requirements.txt && alembic upgrade head && uvicorn app.main:app --reload`
- Web: `cd apps/web && npm install && npm run dev`; open http://localhost:5173
- API tests: `cd apps/api && PYTHONPATH=. pytest -q`
- Qualification tests: from repository root, `python -m pytest tests -q`

## Safety and truthfulness
- This release does not include any paid-wager submission endpoint, betting credentials, or active background betting workers.
- Operational data remains empty until actual integrations are implemented. There are no fabricated results or model probabilities.
- Source permissions, official data contracts, browser integrations and prospective model validation must be established before enabling engines.
- The old SQLite database and application are not modified or migrated.
- The included PostgreSQL password default is only for isolated local development. Change it before exposure.

## Structure
`apps/web` responsive portal; `apps/api` FastAPI and SQLAlchemy; `engines` domain boundaries; `workers` adapters; `connectors` permission-gated source interfaces; `ml` model registry placeholders; `packages/contracts` JSON Schemas; `infrastructure/docker` deployment; `tests` safety tests.


## V2 implementation status (14 November 2026)

- 29 registered routes; 22 dedicated domain workspaces with search, filtering, drilldown modal, responsive cards, evidence/readiness panel, and API-backed datasets; dashboard and command centre have dedicated views; five programme routes have paper-only views.
- PostgreSQL models and Alembic migrations, FastAPI read endpoints, verified provenance ingestion and fail-closed qualification preview.
- New admin endpoints are disabled until `SPORTS_ADMIN_TOKEN` is set. Use `X-Admin-Token` for explicit authorized source onboarding and evidence-backed fixture ingestion.
- No automatic third-party website scraping, no computer-vision inference service, no trained models, no SportyBet login, no genuine booking-code generation, and no paid-wager execution. Those require external integrations, permission, data and validation.
- The existing platform is NOT connected or modified. The app is a local Docker deployment template, not a verified production deployment.

### Evidence-backed fixture ingestion

1. Set a strong `SPORTS_ADMIN_TOKEN` for the API container.
2. POST `/api/v1/sports/admin/sources` with `{"name":"Licensed Provider","permission":"AUTHORIZED","enabled":true}` and `X-Admin-Token` header. Only enable sources for which you actually have authorization.
3. POST `/api/v1/sports/admin/fixtures/ingest` with source name, sport name, competition name, teams, timezone-aware kickoff, source URL, and `evidence.source_reference`.
4. Observe verified source records on the Fixtures page. No predictions or qualifications are invented.

### Tests

From `apps/api`: `PYTHONPATH=. python -m pytest -q tests`.
Frontend: `npm ci && npm run build` from `apps/web` (requires package registry access).

### Limitations

This archive is an expanded implementation, not a complete autonomous research/prediction/booking system. The delivery status is explicitly documented so that placeholder engine directories are not mistaken for finished integrations.

## V2.1 incremental release
See docs/RELEASE_V2_1.md for evidence and mission APIs, scope and limitations.


## V2.2 — Research evidence acquisition and temporal integrity

See `docs/RELEASE_V2_2.md`. This increment adds authorized structured observation ingestion, deterministic deduplication, feature snapshot materialization with as-of validation, and a live research-coverage view. This is **not** an automated source collector or trained model. PAPER mode remains enforced.


## V2.3 acquisition worker
See `docs/RELEASE_V2_3.md` for source feed configuration, Celery worker, scheduler, and operational limitations.


## V2.5 Market Intelligence
See `docs/RELEASE_V2_5.md`. Includes admin-only odds intake and evidence-bound qualification decisions.


## V2.6 strategy allocation
See docs/RELEASE_V2_6.md. Strategy runs are PAPER-only and require actual QUALIFIED decisions with all gates passing.


## Release 2.7
Paper ticket lifecycle and responsive Ticket/Betslip/Booking Codes workspaces are implemented. Database migration `0004` creates betslips and verification history and seeds five programme identities. No real booking codes or wagers are generated. See `docs/RELEASE_V2_7.md`.


## Version 2.8
See `docs/RELEASE_V2_8.md` for versioned results, settlement and forecast-quality workspaces.


## V2.9 model monitoring and GitHub

See `docs/RELEASE_V2_9.md` and `docs/GITHUB_SETUP.md`. GitHub workflows are provided but no remote repository is created. Monitoring is read-only; no model activation.


## Version 3.0 — Scheduled official-result reconciliation

See `docs/RELEASE_V3_0.md`. Includes a five-minute Celery reconciliation task, paper-only administrator endpoint `/api/v1/sports/admin/results/reconcile-pending`, source/evidence validation and versioned forecast settlement. An authorized official-results provider must be connected separately.


## Version 3.3 integration hardening
See `docs/RELEASE_V3_3.md`. Live readiness: `GET /api/v1/sports/readiness`. PAPER-only. No claim of full production readiness.

## Version 3.7
See `docs/RELEASE_V3_7.md` for naming and prospective approved-model inference.

## Top-two club research integration

The supplied 2.9 research scaffold is adapted to the existing evidence-backed API and Research workspace. See [integration details](docs/RESEARCH_SCAFFOLD_INTEGRATION.md) for endpoints, score intake, scope and limitations.

### Windows development setup

From the repository root, create the API environment once:

```powershell
python -m venv apps/api/.venv
apps/api/.venv/Scripts/python.exe -m pip install -r apps/api/requirements.txt
npm --prefix apps/web ci
```

Set `DATABASE_URL` in the root `.env` for your local PostgreSQL database. Percent-encode special characters in the URL password (for example, `@` becomes `%40`). Then run `npm run dev` from the repository root; it starts the API, local scheduler and frontend together. The `.env` and `.venv` are ignored by Git.

On this workstation, the API virtual environment reuses the already installed Python packages (`--system-site-packages`); `pip check` confirms their dependencies are compatible.

## Integrated v3.0 research catalogue

Shared sport/country/league/season filters, season-aware fixtures and league tables, source standings snapshots, and fixture evidence dossiers are integrated into the existing workspaces. See [setup and API details](docs/RESEARCH_V3_INTEGRATION.md). Migration `0008` is required on other installations.

## v3.3 CSV research update

Authorized football CSV conversion, pending-review standings imports, source coverage, approved snapshot history, and club search are integrated into the current catalogue. See [CSV workflow and migration 0009](docs/CSV_RESEARCH_V3_3.md).
