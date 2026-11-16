# Weekly Draw Centre

Page: `/sports/programmes/draws` (`DrawsEngine` in `apps/web/src/AccumulatorEngine.tsx`)
API: `/api/v1/sports/programmes/draws/*` (`draws_routes.py` → shared `programme_routes.make_router`)
Engine: `apps/api/app/modules/strategies/programme_engine.py`, shared with Accumulator, Automatic Singles and Jackpot.

## How the source package was integrated

The supplied package (`CACSMS_Weekly_Draw_Centre`) is a standalone FastAPI/Docker service. It has its own
opportunity, run, ticket and audit tables, an APScheduler cron job, and API-key write routes. Its rules were
mapped onto canonical records:

| Package concept | Integrated as |
|---|---|
| `POST /api/draws/opportunities/ingest` (`X-API-Key`) | Not exposed. Legs come only from `QUALIFIED` decisions that pass every named gate. |
| APScheduler cron: Saturday 09:00 Africa/Lagos | The `draws` step of the autonomy cycle. It runs once per weekly period starting Saturday 08:00 UTC (09:00 WAT). A run missed during downtime is caught up on the first cycle of the period, matching the package's `coalesce=True`. |
| `POST /api/draws/run` | Not exposed. Runs are scheduled autonomously and are idempotent per weekly period. |
| Runs, tickets and audit tables | `StrategyRun` with `programme_key='draws'` (tickets in `result.tickets`), plus `AuditEvent` |
| `validate()`: full-time 1X2 draw, edge ≥ 1.5 pp, odds ≤ 15 min, approved model, research evidence | `programme_rows` (`NOT_FULL_TIME_DRAW`, `INSUFFICIENT_EDGE`) on top of the shared named-gate eligibility |
| One ticket per leg target (2, 5, 8, 10), at most 5 tickets, max odds 1000, no reused opportunity | `optimizer.select_tickets(..., 'draws', draw_legs=target)` per target, excluding selections already used in the run |
| Joint probability as a "proxy" product | Not stored. The engine records probability **bounds** only. |

## KPIs

- **Draw Rate:** the share of settled draw legs whose verified result was a draw. Legs without a verified result
  are excluded, and it shows "—" until at least one leg has settled.
- **Avg. Odds:** the mean total odds of the paper tickets.
- **Est. ROI (paper):** 1 unit per ticket, counting only tickets where every leg has a verified result.

## Behaviour to be aware of

A run that is BLOCKED because no qualified draw selections exist is the run for that week. The next attempt is
the following Saturday at 09:00 WAT, as in the package. Every run is recorded with its reasons. There are no
wagers or booking codes.

## Differences from the reference image

The image's figures (248 runs, 18.4% draw rate, 8.76 average odds, +14.2% ROI) are example data, and the page
does not reproduce them. "Edit" is shown as **Read-only** because the policy is defined in code
(`optimizer.PROGRAMMES` and `programme_engine.SETTINGS`). "Auto Run" is a status indicator, not a toggle.
