# Cacsms Sport AI: twelve-stage PAPER pipeline

The dashboard and all existing 29 sidebar destinations remain in place. A single server-owned runner ([runner.py](../apps/api/app/modules/pipeline/runner.py)) executes actual operations ([operations.py](../apps/api/app/modules/pipeline/operations.py)), writes immutable receipts and stage history, and publishes progress through PostgreSQL-backed APIs and one shared frontend SSE connection. It does not depend on the dashboard remaining open.

## Stages, outputs and completion gates

| Stage | Page | Validated output | Completion gate |
|---|---|---|---|
| 01 Discover | Fixtures & Competitions | Canonical fixture, competition, country, sport and **canonical team IDs** (`sports.teams`, `sports.countries`) | Identity, competition, distinct participants and scheduled time validated; authorized provenance exists |
| 02 Acquire | Browser & Vision Operator | Authorized observations, durable acquisition jobs, per-team `research.team_statistics`, per-section freshness and coverage | Required evidence collected, traceable and dated |
| 03 Research | Deep Match Research | Versioned dossier, completeness score, missing-data report | Every dimension VERIFIED or explicitly UNAVAILABLE |
| 04 Analyse | Match Analysis | Feature snapshot + expected scores, scoring distributions, 1X2/over 2.5/BTTS probabilities, matchup assessment | All evidence observed before the cutoff and kickoff (no leakage) |
| 05 Predict | AI Predictions | Forecasts with 95% uncertainty interval and per-feature explanation | Approved, promoted model; probability in (0,1) |
| 06 Evaluate | Market Intelligence | Implied/fair probability, bookmaker margin, expected value, edge, quote age per market | Complete, source-backed, fresh (≤15 min) same-bookmaker market |
| 07 Qualify | AI Qualification | Qualified/rejected decisions with reason codes, metrics and gates | Statistical, uncertainty, value and policy gates passed |
| 08 Allocate | Betting Programmes | Programme assignments (`strategies.runs`) with correlation and exposure checks | Daily caps and Fréchet-bounded dependence satisfied |
| 09 Prepare | Ticket Builder | PAPER singles/accumulators, combined odds, probability bound, risk summary | Legs valid, compatible, consistent |
| 10 Verify | Betslip Preparation | Verified or rejected betslips, rechecked prices, **expiry timestamp** | Fixture, selection, odds and market revalidated |
| 11 Monitor | Live Operations | Alerts, notices, revalidation triggers, paper suspension, incidents | Scheduled checks registered; monitoring continues |
| 12 Reconcile | Match Results | Win/loss/void/push/unresolved classifications, performance and model-learning feedback | Verified FINAL result with authorized provenance |

### Business outcomes are not failures

A stage settles with either `VERIFIED` (a validated output receipt) or an explicit terminal business outcome, persisted as its own receipt:

- `NO_OPPORTUNITY`: e.g. no fresh market passes margin/model checks, or no programme allocation fits the constraints.
- `INSUFFICIENT_DATA`: e.g. a feature-critical research dimension is unavailable, or the pre-match window closed before the stage could complete.
- `REJECTED`: e.g. every market fails qualification, every ticket or betslip is rejected, or the fixture is cancelled.

Stages after a business outcome become `NOT_APPLICABLE` (also a receipt). `WAITING_FOR_DATA` and `BLOCKED` are unsettled; `FAILED` is a technical failure after five attempts and opens an incident. A run is `MONITORING` once stages 1–10 have settled and `COMPLETED` once all twelve have settled. The run's `outcome` records whether the betting path produced a verified paper betslip or which stage ended it, for example `REJECTED:QUALIFY`.

Monitor and Reconcile run on every pass for every fixture, so non-qualifying fixtures are still monitored and reconciled against verified final results. When kickoff passes, unsettled pre-match stages (Research–Verify) are closed as `INSUFFICIENT_DATA`, or `REJECTED` if they were blocked. If no verified result arrives within seven days of kickoff, Reconcile ends with `INSUFFICIENT_DATA` and the run completes. A late result or correction re-opens Reconcile.

## Standard data contract

Each stage exposes the contract below on `GET /runs/{id}` (`stages[].contract`), and every attempt that changes state is appended to `operations.pipeline_stage_runs`, which is immutable (`GET /runs/{id}/history`):

```json
{"pipeline_run_id":"uuid","fixture_id":"uuid","stage":"RESEARCH","status":"VERIFIED",
 "input_version":1,"output_version":1,"started_at":"ISO-8601","completed_at":"ISO-8601",
 "evidence_ids":[],"output_reference":"stage_record_id","quality_score":1.0,
 "failure_code":null,"failure_reason":null,"next_stage":"ANALYSE"}
```

`operations.pipeline_stages` holds the latest state for efficient dashboard queries. `output_reference` points to the immutable receipt in `operations.stage_records`, whose details link to the domain record (dossier, feature, prediction, ticket, result).

## Orchestrator rules

1. **Idempotency.** Receipts are keyed by a digest of their inputs and output. Fixtures, teams, dossiers, features, predictions, qualifications, allocations, tickets and settlements are reused for the same inputs.
2. **Dependency control.** Each chain stage stores the upstream `output_version` it consumed. A stage never runs on an unverified upstream, and it re-runs whenever the upstream version moves.
3. **Automatic recovery.** Exceptions retry with exponential backoff (30 s up to 15 min). After five attempts the stage is `FAILED` and a HIGH incident opens. Exceptions are logged with tracebacks, and their class and message are stored as `failure_code` and `failure_reason`.
4. **Change propagation.** Every outbox event names the earliest affected stage:

   | Change | Stage re-run |
   |---|---|
   | Odds or `market_odds` observation | Evaluate |
   | Result or `official_result` observation | Reconcile |
   | Model | Predict |
   | Research observation | Research |
   | Fixture or source | Discover |

   Only that stage is re-executed. If its receipt is unchanged, its version stays the same and nothing downstream runs. Writes made by the runner itself are not re-published. An event is de-duplicated only against undelivered events, so a return to an earlier state (A→B→A) still wakes the runner.
5. **Continuous monitoring.** Monitor runs for every fixture, with or without tickets. It records checks at most every 10 minutes unless its alerts change. When an evaluation goes stale it requests revalidation of Evaluate, and when a fixture is cancelled it requests revalidation of Discover. When a paper ticket is at risk, it suspends the ticket and opens an incident.
6. **Result-driven reconciliation.** Reconcile is independent of the betting path.
7. **Model governance.** Learning creates `CHALLENGER` models and never sets approval flags. `POST /api/v1/sports/models/{id}/promote` ([promotion.py](../apps/api/app/modules/governance/promotion.py)) promotes a challenger only if:
   - its chronological holdout beats the baseline on both Brier score and log loss,
   - the holdout has at least 24 matches,
   - its expected calibration error is ≤ `SPORTS_MODEL_MAX_ECE` (default 0.08).

   Only then does it compute `approved`, `out_of_sample`, `calibrated` and `calibration_verified`, retire the previous active model for the sport and record a governance snapshot. Reconcile records per-prediction Brier and log-loss feedback.

## Required records → tables

Existing tables are reused instead of being duplicated:

| Spec record | Table |
|---|---|
| pipeline_runs / pipeline_stage_runs / pipeline_events | `operations.pipeline_runs`, `operations.pipeline_stage_runs` (history) + `operations.pipeline_stages` (latest), `operations.pipeline_events` |
| sports, countries, competitions, competition_seasons, teams | `sports.sports`, `sports.countries`, `sports.competitions`, `sports.competition_seasons`, `sports.teams` |
| fixtures | `fixtures.fixtures` (`home_team_id`, `away_team_id`) |
| source_evidence | `sources.observations` (+ `markets.odds_evidence`, `results.result_evidence`) |
| standings_snapshots, team_statistics | `research.standings_snapshots`, `research.team_statistics` |
| research_dossiers, match_analyses | `research.dossiers`, `features.snapshots` (`features.analysis`) |
| model_predictions, odds_snapshots | `predictions.forecasts` (`details`: interval, explanation), `markets.odds_snapshots` |
| market_evaluations, monitoring_events | Evaluate and Monitor receipts in `operations.stage_records` |
| qualification_decisions, programme_allocations | `qualification.decisions`, `strategies.runs` |
| proposed_tickets, ticket_verifications | `tickets.tickets` / `tickets.ticket_legs` / `tickets.betslips`, `tickets.ticket_verifications` |
| verified_results, settlements, audit_logs | `results.official_results`, `results.settlements`, `audit.events` |

Preparation writes a `PAPER_PREPARED` record with scope `PREPARATION`. Only Verify writes `PAPER_VERIFIED` with scope `PAPER_BETSLIP`.

## Live source configuration

The local installation enables OpenLigaDB fixture discovery under its published ODbL licence, with attribution, central caching, change checks, jitter and backoff. Its community-maintained fixture facts are **not** promoted to independently verified research, official results, bookmaker prices or predictions. Other installations can opt in with `SPORTS_OPENLIGADB_ENABLED=1`; the example environment defaults to disabled.

```text
SPORTS_DISCOVERY_FEEDS_JSON={"registered-source-id":"https://licensed-provider.example/fixtures"}
SPORTS_SOURCE_FEEDS_JSON={"registered-source-id":{"recent_form":"https://licensed-provider.example/fixtures/{fixture_id}/form","market_odds":"https://licensed-provider.example/fixtures/{fixture_id}/prices","official_result":"https://licensed-provider.example/fixtures/{fixture_id}/result"}}
SPORTS_RESEARCH_QUORUM_JSON={"source-a":{"reviewed":true,"independence_group":"provider-a"},"source-b":{"reviewed":true,"independence_group":"provider-b"}}
SPORTS_RESEARCH_DEADLINE_MINUTES=60
SPORTS_MODEL_MAX_ECE=0.08
```

Feeds are server-side and fetched only over public HTTPS. The registered source must stay enabled and AUTHORIZED.

A research dimension is VERIFIED by explicit independent review, or when two distinct configured independence groups agree on the content. It can be marked UNAVAILABLE in two ways:

- a corroborated declaration `{"availability":"UNAVAILABLE","reason":"..."}`, or
- for the optional dimensions (standings, head-to-head, team news, line-ups, injuries) only, when the pre-kickoff research deadline passes without corroborated or conflicting evidence.

`recent_form` and `match_statistics` feed the numeric model, so they can never be assumed unavailable. If they are unavailable, Analyse ends with `INSUFFICIENT_DATA`. No missing value is filled with a default.

- `recent_form.data`: `home_form`, `away_form`.
- `match_statistics.data`: `home_scoring_rate`, `away_scoring_rate`, `home_conceding_rate`, `away_conceding_rate` (finite, 0..10). Keys prefixed `home_`/`away_` are also stored per canonical team.
- `market_odds.data.prices`: `bookmaker`, `market_key` (`1X2`), `outcome_key` (`HOME`/`DRAW`/`AWAY`), `decimal_odds`, timezone-aware `observed_at`. Overround must be 0.90..1.25.

## Paper mode

No real-money submission is implemented or enabled. Verify refers to the independently rechecked **paper betslip**. Monitoring is scoped as internal PAPER risk monitoring and does not claim to be an external bookmaker monitoring service. Final results require source-linked provenance and a validated FINAL outcome map. Corrections create new result versions and keep settlement history.

## APIs

- `GET /api/v1/sports/pipeline/runs`, `/runs/{run_id}`, `/runs/{run_id}/history?stage=<key>`
- `GET /api/v1/sports/pipeline/context?run_id=<id>&fixture_id=<id>` (includes teams, team statistics and history)
- `GET /api/v1/sports/pipeline/events?fixture_id=<id>&status=<status>`
- `POST /api/v1/sports/pipeline/runs`, `/runs/{id}/execute`, `/runs/{id}/drive` (admin token)
- `POST /api/v1/sports/models/{id}/promote` (admin token)

The legacy `POST /runs/{id}/evaluate` endpoint was removed. It accepted client-supplied evidence IDs, and no endpoint may set stage completion.

## Migrations

`0011` (events, receipts, quote provenance) and `0012` (data contract columns, stage history, countries, teams, team statistics, forecast details, event content hashes) use explicit, idempotent DDL. They do not depend on the current ORM models.

## Run and verify

```powershell
$env:PYTHONPATH='apps/api;.'
$env:SPORTS_TEST_DATABASE_URL='<PostgreSQL URL for an account permitted to create disposable test databases>'
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests tests -q
npm run build
$env:CACSMS_BROWSER_CHANNEL='msedge'
apps/api/.venv/Scripts/python.exe scripts/verify_workflow_ui.py
```

The PostgreSQL acceptance tests create and drop their own databases and run the real migrations, including a downgrade and re-upgrade cycle. They cover:

- the full twelve stages,
- a non-qualifying fixture that is monitored and reconciled to completion,
- kickoff closing pre-match stages,
- selective, versioned invalidation and stage history,
- events not lost on A→B→A changes, and no self-wakeup from the runner's own writes,
- canonical teams and team statistics,
- research dimensions marked unavailable at the deadline,
- model promotion gates,
- tampering, source revocation, stale prices, result corrections and multi-fixture allocation.

## Current live limits

OpenLigaDB supplies fixtures, but not the independently corroborated research dimensions, promoted model artifacts or licensed odds feeds. Without those inputs, fixtures end at the corresponding business outcome or blocker and are still monitored and reconciled. Final results are accepted from a single authorized source with validated provenance; requiring a second source would be a policy change. Analysis and markets currently cover football 1X2.
