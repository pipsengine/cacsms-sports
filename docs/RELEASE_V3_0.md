# Release 3.0 — Automated verified-result reconciliation

## Added
- Scheduled Celery reconciliation every five minutes and authenticated manual trigger.
- Rejects unauthorized sources, mismatched fixtures, non-final observations, invalid timestamps.
- Versioned corrected results, replay-safe observation evidence, append-only audit events.
- Automatic prediction settlements and explicit paper-only status.
- Six unit tests for evidence validation.

## Required upstream contract
Observations must be stored in `sources.observations` with `payload.section=official_result`, `payload.data.status=FINAL`, and an `outcomes` map. Existing acquisition connector currently only supports research sections and **does not yet collect official results**. Use the existing admin result ingestion endpoint or add an authorized official-results provider before expecting scheduled settlements.

## Known limitations
No live results provider configured. No browser-vision inference or genuine SportyBet booking code verification. No production deployment verification. Paper-only; no wager submission. Reconciliation scans at most the most recent 5,000 official-result observations, so production requires a dedicated indexed queue.
