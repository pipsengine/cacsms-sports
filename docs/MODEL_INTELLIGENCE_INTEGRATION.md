# Model Intelligence & Governance Centre

The model dashboard at `/sports/models` adapts the supplied integration module and reference image into the existing application. The sidebar and shared navigation styles are unchanged. Six sections cover the registry, training evidence, validation and calibration, comparisons, drift monitoring, and governance/deployment records.

`GET /api/v1/sports/models/workspace?days=30` accepts 1–365 days and aggregates the existing model registry, artifact metadata, current-version forecast settlements, governance snapshots, training controller states, audit records and model incidents. The dashboard refreshes every 60 seconds and supports model selection, cohort periods, searchable tables and record details. No additional dependencies, database tables or migrations are introduced.

Registry state, recorded approval flags, monitoring decisions, chronological holdout scores and prospective scores are displayed separately. An ACTIVE model counts as active and approved only when all existing inference approval flags are true. A BLOCKED monitoring snapshot does not rewrite registry state. This dashboard performs no promotion, evaluation, training or deployment mutations.

Holdout reliability charts use stored reliability bins. Prospective Brier/log-loss trends use current-version settled forecasts in the selected pre-match forecast cohort. Unsupported or unrecorded metrics remain unavailable. Market models expose their per-outcome validation results instead of inventing a single aggregate holdout score.

Training artifacts are counted as recorded artifacts, not running experiments. Training controller next-check times are eligibility checks, not promised retraining schedules. No standalone experiment queue, PSI measurement, feature SLA or coverage percentage is inferred. Existing lifecycle workers and server-side validation gates remain authoritative. PAPER mode is retained.

The existing model monitoring service also uses current-result settlement selection, preventing superseded outcomes from being counted while a correction awaits a new settlement.

Validation: production web build; targeted workspace, learning-monitoring, governance and performance tests; read-only local PostgreSQL endpoint check. No model state was changed by the dashboard integration.
