# Match Results dashboard integration

The Match Results workspace at `/sports/results` adapts the supplied results integration and dashboard image into the existing React application. Its seven sections are Overview, Results Register, Settlement, Reconciliation, Exceptions, Learning and Audit Trail. The Performance Analytics route remains available separately.

The workspace uses `GET /api/v1/sports/results/workspace`, backed by the existing fixtures, forecasts, immutable result versions, settlements, provenance observations and audit tables. It refreshes every 30 seconds, supports record search, outcome and exception filtering, 25-row pages and evidence inspection. Times are displayed in Africa/Lagos.

## Reporting definitions

- Verified matches count the highest result version for each fixture.
- Settled forecasts count WON, LOST, VOID and PUSH settlements belonging to that current result version. Older settlements remain in storage but do not contribute to totals.
- Hit rate uses wins divided by WON plus LOST forecasts. Void, push, unresolved and pending forecasts are excluded from forecast quality scores.
- A corrected result with no corresponding new settlement reports the forecast as PENDING. It never falls back to an earlier win or loss.
- Exceptions distinguish overdue forecasts awaiting an official result, forecasts awaiting settlement against a current result and unresolved markets. Future fixtures without a result do not raise overdue alerts.
- Existing latest-settlement and forecast-quality APIs use the same current-version selection, including when the corrected result has no new settlement yet.

The existing five-minute Celery reconciliation task and administrator-controlled result intake remain in place. This integration adds no second scheduler, schema, dependencies or browser access permissions. The dashboard reports recorded source names rather than the reference image's sample provider labels.

ROI, calibration, settlement-linked odds, ticket reconciliation, scheduler heartbeat and retraining queue are unavailable where there is no supporting platform record. No ROI, source availability, automatic deployment or retraining schedule is inferred. PAPER mode remains enforced.

## Validation

Frontend production build; targeted result validation, automation and workspace tests; local PostgreSQL workspace request; browser inspection of the dashboard, register and evidence details. Correction tests cover both settled corrections and corrections still awaiting a new settlement.
