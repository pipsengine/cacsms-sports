# Automatic Singles

Page: `/sports/programmes/singles` (`SinglesEngine` in `apps/web/src/AccumulatorEngine.tsx`)
API: `/api/v1/sports/programmes/singles/*` (`apps/api/app/modules/strategies/singles_routes.py`)
Engine: `apps/api/app/modules/strategies/programme_engine.py`. The Accumulator Engine uses the same engine.

## How the source package was integrated

The supplied package (`CACSMS_Automatic_Singles_Engine/cacsms_singles`) is a standalone FastAPI/Docker
service with its own `singles_candidates` table and its own scheduler. It was **not** copied in. Its
behaviour was mapped onto canonical records instead:

| Package concept | Integrated as |
|---|---|
| `singles_candidates` table | `QualificationDecision` rows with status `QUALIFIED` (no new table) |
| Its scheduler | The `singles` step in the autonomy cycle (`open_intelligence.collect`), every 5 min |
| Run records | `StrategyRun` with `programme_key='singles'`, idempotent per 5-minute bucket |
| Policy (legs, odds, cap) | `optimizer.PROGRAMMES['singles']`: 1 leg, max odds 1000, daily cap 25 |

## Rules

- Each paper single comes from one QUALIFIED decision. That decision must pass the named gates
  (research, model, calibration, odds_freshness ≤ 15 min, market_mapping and value). The
  uncertainty and market_risk gates must also pass whenever they are present.
- **The daily cap counts tickets, not runs.** The cap is 25 paper singles per UTC day.
- **One fixture per day:** a fixture or decision already used today is excluded with
  `ALREADY_SELECTED_TODAY`.
- **Paper stake:** a nominal ₦100 per single, used only for the potential-return and paper ROI
  figures. Mode is always PAPER. There are no live wagers and no booking codes.
- **Blocked runs:** every run is recorded, including BLOCKED ones, with reasons such as
  `INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES` or `DAILY_CAP_REACHED`.
- **Success rate and ROI:** these use only tickets whose fixture has a verified `Result`.

## Endpoints

`overview`, `configuration`, `candidates`, `run-history`, `tickets`, `validation`, `analytics` and `health`.

## Differences from the reference image

The figures in the reference image (1,842 runs, an 87.4% success rate and so on) are example data,
and the page does not reproduce them. It shows what is actually recorded. Until qualified
opportunities exist, that means BLOCKED runs and "—" for success rate and odds. The configuration
panel is read-only; its policy comes from `optimizer.PROGRAMMES`. "Auto Run" is a status indicator,
not a toggle.
