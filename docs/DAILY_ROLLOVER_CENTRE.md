# Daily Rollover Centre

Page: `/sports/programmes/rollover` (`RolloverEngine` in `apps/web/src/AccumulatorEngine.tsx`)
API: `/api/v1/sports/programmes/rollover/*`, plus `/plan` (`rollover_routes.py` → shared `programme_routes.make_router`)
Engine: `apps/api/app/modules/strategies/programme_engine.py`, shared with Accumulator, Singles, Jackpot and Weekly Draw.

## How the source package was integrated

The supplied package (`CACSMS_Daily_Rollover_Centre`) is a standalone FastAPI/Docker service with its own
opportunity, run, plan, step and audit tables, an APScheduler daily job, and API-key write routes. Plans are
created by hand there (`POST /plans`), and steps are settled by an adapter (`POST /steps/{id}/settle`). Because the
platform must run with no human input, the integration keeps the package's rules but removes the manual parts:

| Package concept | Integrated as |
|---|---|
| `POST /plans` (bankroll, target 1.5 or 2.0, 30 days) | One autonomous paper plan at a time: target 1.50, a ₦1,000 nominal paper bankroll and 30 days (`SETTINGS['rollover']`). A new plan starts automatically when the previous one stops or completes. |
| Plan and step tables | Derived from `StrategyRun` history: each completed run stores `result.plan` (plan id, day, bankroll), and `rollover_state` rebuilds the current plan. No new table is needed. |
| `POST /steps/{id}/settle` | Not exposed. Settlement comes only from verified `Result` rows. |
| `POST /opportunities/ingest`, `POST /run` | Not exposed. Selections come only from QUALIFIED decisions, and runs are scheduled by the autonomy cycle. |
| Daily cron at 09:00 Africa/Lagos (`coalesce=True`) | The `rollover` step of the autonomy cycle. It runs once per daily period starting 08:00 UTC, and a missed run is caught up. |
| `validate()`: odds within target to target + 0.25, edge ≥ 1.5 pp, kick-off within 2 days, odds ≤ 15 min old | `programme_rows` (`OUTSIDE_TARGET_BAND`, `INSUFFICIENT_EDGE`, `TOO_FAR_AHEAD`) on top of the shared named-gate eligibility, plus `optimizer.PROGRAMMES['rollover']` (single leg, odds 1.45–2.10, 1 per day) |

## Sequential rules

- **One step per day:** a single selection, staked with the current paper bankroll.
- **No compounding on predicted wins:** the next step is BLOCKED (`AWAITING_SETTLEMENT`) until the previous step has a verified result.
- **Verified win:** the bankroll becomes the stake × the odds, and the plan moves to the next day. A win on day 30 completes the plan.
- **Verified loss:** the plan stops (the whole paper bankroll is lost), and a fresh plan starts on the next run.
- **Void, or no verified result 7 days after kick-off:** the day and bankroll stay the same. The 7-day rule is an
  addition, so that a postponed fixture without a result cannot block the plan forever.
- **Paper only:** no wagers, booking codes or guaranteed returns.

**Rollover Rate** is the share of settled steps that won. Void steps are excluded.

## Differences from the reference image

The image's figures (1,842 runs, 87.4% rollover rate, 3.26 average odds, 4–6 legs) are example data. A rollover
step here is a single selection, so the table shows **Plan Day** rather than legs. "Edit" is shown as
**Read-only**, and "Auto Run" is a status indicator.
