# Jackpot Engine

Page: `/sports/programmes/jackpot` (`JackpotEngine` in `apps/web/src/AccumulatorEngine.tsx`)
API: `/api/v1/sports/programmes/jackpot/*` (`jackpot_routes.py` → shared `programme_routes.make_router`)
Engine: `apps/api/app/modules/strategies/programme_engine.py`. Accumulator and Automatic Singles use the same engine.

## How the source package was integrated

The supplied package (`CACSMS_Jackpot_Engine`) is a standalone FastAPI/Docker service. It has its own
`jackpot_opportunities`, `jackpot_runs` and `jackpot_tickets` tables, a thread-based scheduler and a write API.
Its own README asks for it to be wired to the existing qualified-opportunities service rather than copied in,
and that is how it was integrated:

| Package concept | Integrated as |
|---|---|
| `jackpot_opportunities` and `POST /internal/opportunities` | `QualificationDecision` rows with status `QUALIFIED` only. There is no ingestion route. |
| Interval worker (`JACKPOT_INTERVAL_SECONDS=900`) | The `jackpot` step of the autonomy cycle, idempotent per 15-minute bucket |
| `jackpot_runs` / `jackpot_tickets` | `StrategyRun` with `programme_key='jackpot'`; the ticket is stored in `result.tickets` |
| Settings (2–30 legs, max odds 100M, cap 5, 15-min age) | `optimizer.PROGRAMMES['jackpot']` and the engine's 15-minute freshness rule |
| `PUT /settings`, `POST /run` | Not exposed. The policy is defined in code and runs are scheduled autonomously. |
| Greedy build with an independence product | The existing `select_tickets` bounded search. It records probability **bounds**, never an independence product. |

## Rules

- Each leg is a fresh QUALIFIED decision that passed every named gate. It must come from an ACTIVE, approved model,
  be for an upcoming fixture and have positive EV. Each fixture appears at most once per ticket.
- The ticket's combined odds must be between **2,000,000** (`optimizer.JACKPOT_MIN_COMBINED_ODDS`) and 100,000,000.
- **Screen step:** before any combination search, the engine computes the highest odds that can be reached from
  the 20-candidate search pool. If that is below the floor, the run is BLOCKED with `JACKPOT_ODDS_UNREACHABLE`
  and the reachable figure is recorded. Tickets are never padded.
- **Cap and schedule:** at most one ticket per run and 5 completed runs per UTC day. Every run is recorded,
  including BLOCKED runs and their reasons.
- **Paper only:** no stake, wager or booking code.
- **Success rate and ROI:** these count only tickets where every leg has a verified result. ROI uses 1 unit per ticket.

## Known limitation

`select_tickets` searches only the 20 best-EV candidates, so a ticket can have at most 20 legs even though the
policy allows 30. Allowing 30 legs would need a different search strategy, because the number of combinations
grows exponentially.

## Differences from the reference image

The image's figures (248 runs, 87.4% success rate, 4.21M average odds, +14.2% ROI) are example data, and the page
does not reproduce them. It shows what is actually recorded. With no qualified opportunities yet, that means
BLOCKED runs and "—" for the rest. "Edit" is shown as **Read-only** because the policy is defined in code.
"Auto Run" is a status indicator, not a toggle.
