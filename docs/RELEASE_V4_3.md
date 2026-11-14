# Cacsms Sports 4.3 — Operations workspace integration

This release retains the entire 4.2 source tree and adds dedicated Source Intelligence and Live Operations workspaces. They read only persisted backend records from the source, source-health, acquisition-jobs, operations, incidents, and audit APIs. No demonstration data or invented status indicators are used.

Both workspaces support source switching, refresh, search, record inspection, request cancellation on navigation, empty states, errors and responsive table overflow. The UI suppresses fields that appear to contain credentials, secrets or tokens; this is defense in depth, not a substitute for backend response redaction and access control.

### Validation status
- Static route and source-preservation checks run locally.
- Frontend production compilation requires npm dependencies and has not been completed in this environment.
- PostgreSQL, Docker, full integration tests, authorized providers and real booking codes are not validated by this release.
- The platform remains PAPER-only.

### Next deployment checks
Run `npm ci && npm run build` under `apps/web`, `pytest -q apps/api/tests` and `alembic upgrade head` under a configured PostgreSQL environment, then `docker compose up --build -d` and the HTTP smoke checks. Do not claim operational readiness unless all succeed.
