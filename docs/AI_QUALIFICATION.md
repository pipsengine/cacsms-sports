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

## Qualified Opportunities (cacsms-qualified module, integrated)

Source: `CACSMS_Qualified_Opportunities_Module` (standalone FastAPI + Docker app with its own `market_observations`,
`model_forecasts` and `qualification_decisions` tables and scheduler). Integrated without a second database or scheduler:
opportunities **are** `qualification.decisions` rows with decision QUALIFIED. The module's policy thresholds (minimum
probability, minimum EV) became the page's **Confidence ≥** and **Min. EV ≥** filters on top of the qualification gates.

API: `GET /api/v1/sports/qualification/opportunities?only_qualified=&min_probability=&min_ev=&...` and
`GET /api/v1/sports/qualification/opportunities/{id}/evidence` (decision or `pending:<prediction_id>`): fixture, research
sections and sources, model validation (holdout Brier vs base rate, calibration error, skill), 95% range, all gates and a
rationale generated from those stored facts. Page: `/sports/opportunities`; market comparison, gate inspector, rejection
intelligence and history are shared with AI Qualification (`QualificationSecondaryTab`).
