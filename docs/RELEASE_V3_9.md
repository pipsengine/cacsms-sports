# Cacsms Sports v3.9 — allocation and monitoring integrity

Builds on v3.8. This release hardens the already connected automatic PAPER allocation, ticket preparation, persisted-market monitoring, and result reconciliation components.

## Changes
- PostgreSQL transaction-scoped advisory locks serialize allocation per programme; callers must commit/rollback the transaction. This is a PostgreSQL-specific guarantee, not a SQLite concurrency guarantee.
- Daily programme caps now use a UTC day start **and end** boundary.
- Ticket preparation enforces programme-specific maximum combined odds; jackpot and rollover have additional strategy-specific constraints. It remains PAPER-only.
- Market monitoring normalizes naive persisted timestamps to UTC, retaining explicit `monitoring_verified: false` because stored price changes are not external live evidence.
- Existing authorized official-result observation reconciliation is retained, including duplicate-evidence detection and versioned result records.

## Limitations
This does not establish live SportyBet integration, genuine booking codes, or independent provider monitoring. A configured official-result feed is required. A real PostgreSQL instance, Docker deployment, frontend build and complete end-to-end integration tests have not been run in this build environment.

## Tests
`DATABASE_URL=sqlite:////tmp/cacsms_v39_tests.db PYTHONPATH=apps/api:. pytest -q apps/api/tests/test_v39_integrity.py apps/api/tests/test_v38_allocation_monitoring.py`
