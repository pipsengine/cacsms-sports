# Version 2.5 — Market Intelligence and Qualification

## Implemented
- Decimal-precision bookmaker odds intake with administrator token, fixture FK and future timestamp rejection.
- Server-side market identity, freshness, evidence, temporal, approved-model, calibration and value gates.
- Immutable database-backed qualification decisions linked to forecast and exact odds snapshot.
- Read-only market summary.
- Eight isolated unit tests, including negative and future data cases.

## Important boundaries
- Odds are only recorded from an authenticated upstream caller; **no direct bookmaker connector or verified external price source is provided**.
- An ACTIVE status and validation metadata can be stored by legacy administration processes; independent validation of model activation governance is not yet fully implemented.
- This module does not execute bets or issue booking codes. PAPER mode only.
- Production Postgres and frontend build require environment verification.
