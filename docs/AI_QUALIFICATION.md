# AI Qualification (v3.7 qualification patch, integrated)

Source: `CACSMS_Sports_AI_Qualification_v3_7_Integrated` (full v3.5-based snapshot). Only the qualification feature was taken
(`qualification/autonomous.py`, routes, page); the rest of the snapshot predates current work and was not copied.

| Patch | Integrated as |
|---|---|
| Separate `qualification_worker.py` process | `qualification` step of the existing autonomy cycle (every 2 min) - no second scheduler |
| 200 newest forecasts × one price | every ACTIVE-model forecast of an **upcoming** fixture × the latest evidence-backed price of **each** bookmaker for that market/outcome (one coherent model per market) |
| `evaluate_market` gates | same gates (research, model, calibration, odds freshness ≤15 min, market mapping, value) **plus** `uncertainty` (positive EV at the probability lower bound) and `market_risk` (complete outcome set from one bookmaker, overround 0.90-1.25) - exactly what the pipeline Evaluate stage requires, so the pipeline Qualify stage can reuse these decisions consistently |
| "Pending = forecasts − decisions" approximation | Pending = forecasts of upcoming fixtures with no source-backed price for their market/outcome |
| Gate summary "requirements only" | pass rates computed from stored decision gates |

One immutable decision per (prediction, odds snapshot); a new price creates a new snapshot and a new decision. Paper only.

API (`/api/v1/sports/qualification`): `summary`, `decision-details` (status/search/sport/country/competition/category/paging),
`rejections` (primary-category breakdown + reason codes), `gates`, `history`, `comparison`, `filters`.

Live state (16 Nov 2026): 2 approved models, 288 forecasts for 9 upcoming fixtures, research verified, **0 decisions / 270 pending**
because no source-backed prices exist yet for upcoming fixtures (Football-Data publishes them a few days before kickoff; they will
also be stale against the 15-minute freshness gate, so they are expected to be recorded as rejections, not qualifications).

Tests: `apps/api/tests/test_qualification_autonomous.py`.
