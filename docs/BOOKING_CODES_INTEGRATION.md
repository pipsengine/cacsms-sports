# Booking Codes dashboard integration

The supplied `CACSMS_Booking_Codes_Module/cacsms_booking` is integrated into `/sports/booking-codes` using the existing portal shell. Sidebar markup/styles and other ticket routes are unchanged.

## Interface

The reference-style layout includes five metrics, a six-step pipeline, six tabs (Overview, Booking Register, Verification Rules, Booking History, Failed Items, Programme Analytics), configuration, recent code records, readiness, recorded check rates, a 30-day outcomes chart, system status and the five-part lifecycle strip. Tickets/codes open a read-only evidence and audit dialog. Search filters the register. Missing integrations remain explicitly unavailable rather than displaying the reference image's illustrative green statuses or numbers.

Background updates reuse the existing live-update provider and stable fetch hook. No extra polling timer, sync button, second scheduler, duplicate ticket/code database or browser API key is introduced.

## Canonical API

- `GET /api/v1/sports/booking-workspace/overview`
- `GET /api/v1/sports/booking-workspace/tickets/{ticket_id}`

The adapter reads Ticket, Betslip, BookingCode, Programme, TicketVerification and AuditEvent records. A displayed code must be non-empty, have a verification timestamp no later than the viewing time and a HTTPS evidence URL. Future, empty and unsupported-evidence records are withheld. These checks establish eligibility of canonical recorded metadata; this dashboard does not independently contact an external provider or prove fresh external validity. Evidence links and audit records remain inspectable.

Prepared paper slips do not become codes. Booked metrics count distinct tickets with eligible code records. Success rates use code entries and logged `booking.verification_failed` / `booking.verification_rejected` events; these denominators are described in the interface. Failed/blocked paper slips and actual verification failures are distinguished from unavailable integrations. Thirty-day averages use recorded slips linked to eligible code records. Paper ROI stays unmeasured because no suitable return/stake ledger exists. Rates and system statuses do not fabricate live provider health.

## External-provider boundary

The supplied provider `/verify` contract is an adapter interface, not a genuine SportyBet endpoint. No bookmaker submission, external verification, retry queue, auto-booking or programme notification adapter is currently configured. Consequently booking readiness is blocked, next booking time is absent and the corresponding pipeline/lifecycle states stay unavailable. The autonomy badge reports the existing platform worker heartbeat; it does not imply that auto-booking is enabled.

No standalone `API_KEY`, `VITE_API_KEY`, `PROVIDER_VERIFY_URL`, default secret, upstream duplicate ingestion or APScheduler instance was installed. No new code is generated or sent to a bookmaker, and there is no paid-wager submission action. A future permitted provider adapter must use server-side authentication, canonical ticket checks, matched external confirmation and immutable evidence before accepting a new code. No schema migration or dependency installation is required for this dashboard.

## Checks

`apps/api/tests/test_booking_workspace.py` covers empty/unconfigured states, prepared-versus-booked separation, eligible verification metadata, withheld future/unsupported codes, failure history and read-only endpoints. Existing betslip tests run alongside it. `python scripts/verify_booking_ui.py` checks all six tabs, evidence dialogs, search, failures, charts, lifecycle, stable refresh, mobile/desktop overflow and exact sidebar preservation with isolated test responses. The live PostgreSQL page was checked separately with no browser/API errors.
