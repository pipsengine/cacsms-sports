# Betslip Preparation integration

The supplied `CACSMS_Betslip_Preparation_Module/cacsms-betslip` is adapted into the existing portal at `/sports/betslip`. The shared sidebar, Ticket Builder and Booking Codes routes are preserved.

## Page

The reference-style page has metric cards, the six-step pipeline, Overview / Betslip List / Verification Rules / Preparation History / Programme Analytics tabs, configuration, preparation readiness, recorded risk-check rates, recent preparations, a recorded-betslip paper preview and system status. Ticket identifiers open a read-only details/audit dialog. The paper stake calculator estimates a hypothetical return from a persisted betslip; it submits nothing.

The page uses the existing shared live-update and stable background-fetch mechanisms. There is no refresh/sync button or competing polling timer. It preserves visible records during background refresh. Missing records, quality measurements, schedule information and external integrations are shown as missing, not populated with the example image's numbers.

## Backend

New read-only endpoints:

- `GET /api/v1/sports/betslip-preparation/overview`
- `GET /api/v1/sports/betslip-preparation/{slip_id}`

These use the canonical Ticket, TicketLeg, Betslip, TicketVerification, Programme, AuditEvent and PipelineStageRun models. No duplicate paper-ticket tables, separate SQLAlchemy engine, APScheduler instance, external upstream credential or schema migration is introduced. The existing autonomous engine and `tickets.service.prepare_paper_ticket` remain the writers. Configuration comes from the canonical programme policies; displayed configuration is read-only. Programme selection in Verification Rules changes the displayed rules, not engine settings.

Metrics count actual slips and distinguish prepared, rejected and paper-verified states. The latest 200 slips and 100 preparation/verification events are available in this workspace. Audit preparation receipts are included because canonical tickets may also be registered by Ticket Builder outside a fixture-stage attempt. Check percentages describe recorded receipts in the sample, rather than live data quality.

Current paper readiness requires an unexpired paper verification receipt, a currently eligible canonical qualification for every leg, matching canonical ticket legs and selections, and matching prices/combined odds. Rejected qualifications, stale prices, expired receipts and tampering do not result in a ready claim. External booking and paid submission remain unavailable. Source/formatter statuses describe recorded data, not fabricated live health. Next controller cycle is not a guaranteed preparation completion time.

## Verification

`apps/api/tests/test_betslip_workspace.py` covers empty states, preparation versus verification, expiry, changed qualifications, tampering, audit access and read-only behavior. Existing Ticket Builder tests run alongside it. `python scripts/verify_betslip_ui.py` uses isolated browser responses to check sidebar preservation, all five tabs, details, the paper calculator, search, programme rules, history, slow background refresh and desktop/mobile overflow. A separate live-database browser check verifies the real route and API.
