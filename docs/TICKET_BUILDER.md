# Ticket Builder

Page: `/sports/tickets` (`apps/web/src/TicketBuilder.tsx`). Betslip Preparation and Booking Codes still use `TicketWorkspace`.
API: `/api/v1/sports/tickets/builder/{overview,register,programmes}` (`app/modules/tickets/builder_routes.py`)
Service: `app/modules/tickets/builder.py`. It runs as the `ticket-builder` step of the autonomy cycle, every minute.

## How the source package was integrated

The supplied package (`cacsms-ticket-builder`) is a standalone FastAPI/Docker service. It has its own opportunity,
ticket and run tables, a scheduler that builds tickets for all five programmes, and an authenticated
qualified-feed ingestion route. In this platform the five programmes already compose tickets
(`strategies/programme_engine.py`), and a canonical ticket register already exists (`tickets.tickets`, `ticket_legs`,
`betslips`, `ticket_verifications`, `booking_codes`). The package was therefore mapped onto those parts rather than added
as a second builder:

| Package concept | Integrated as |
|---|---|
| Builds tickets for 5 programmes every 5 minutes | The programme engines compose the tickets. The builder **registers** them; it never composes its own. |
| `POST /api/internal/qualified-feed` | Not exposed. Inputs are QUALIFIED decisions only, reached through the programme engines. |
| Ticket register / ticket detail tables | The canonical `tickets.*` tables, written only through `tickets.service.prepare_paper_ticket` |
| Validation before registration | `prepare_paper_ticket` checks, at registration time, the QUALIFIED decision and its named gates, market mapping, that the fixture has not started, odds ≤ 15 min old, one leg per fixture, a single bookmaker, the programme odds ceiling, the jackpot floor and rollover band, and the shared daily exposure cap |
| Run history | Each programme run stores its registration outcomes in `StrategyRun.result['registrations']`: REGISTERED with ticket and betslip ids, or REJECTED with a reason |
| Joint probability "assuming independence" | Not used. The ticket's probability **bounds** from the optimizer are shown instead. |
| "Example Ticket (Illustrative Only)" in the design | Replaced by **Latest Registered Ticket**, which shows real data only. Until a real ticket exists, the panel shows an empty state. |

## Behaviour

- **Idempotent:** each engine ticket is processed once. A ticket whose legs were already registered (for example by
  the 12-stage pipeline's prepare stage) is **linked** to that existing ticket, not duplicated.
- **Final rejections:** a rejection is never retried or padded. For example, `ODDS_NOT_FRESH` means the price was more
  than 15 minutes old when registration was attempted.
- **Audit:** every outcome writes an `AuditEvent` correlated to its programme run.
- **Paper only:** no wagers are placed and booking codes are never generated. The lifecycle panel counts only booking
  codes recorded with a verification time.

## KPIs

- **Recorded Items:** engine tickets processed.
- **Built Tickets:** tickets REGISTERED.
- **Rejected:** tickets REJECTED.
- **Build Rate:** registered divided by processed.
- **Avg. Legs:** the average number of legs on registered tickets.

Trends compare the last 24 hours with the 24 hours before that.

## Differences from the reference image

The image's figures (1,842 items, 92.6% build rate and so on) and its illustrative example ticket are not reproduced.
"Edit" is shown as **Read-only** because the rules are defined in code.
