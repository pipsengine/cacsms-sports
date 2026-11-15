# Cacsms Sport AI: twelve-stage PAPER pipeline

The dashboard and all existing 29 sidebar destinations remain in place. A single server-owned runner executes actual operations, creates durable evidence receipts and publishes progress through PostgreSQL-backed APIs and one shared frontend SSE connection. It does not depend on the dashboard remaining open.

## Stage contract and destinations

| Stage | Existing page | Actual operation / success evidence |
|---|---|---|
| Discover | Fixtures & Competitions | Canonical fixture, competition and currently authorized source provenance |
| Acquire | Browser & Vision Operator | Durable acquisition jobs and persisted authorized observations; existing reviewed browser evidence remains supported |
| Research | Deep Match Research | Seven independently reviewed or independently corroborated research sections, with source/evidence IDs |
| Analyse | Match Analysis | Timestamp-valid feature snapshot containing the six validated numeric features |
| Predict | AI Predictions | Real inference using an ACTIVE, approved, out-of-sample and calibration-verified model artifact |
| Evaluate | Market Intelligence | Source-backed, complete fresh 1X2 quotes, exact mapping, probability/model checks and bounded overround |
| Qualify | AI Qualification | Existing server-side qualification service plus persisted market-risk evidence |
| Allocate | Betting Programmes | Existing programme optimizer over the shared qualified pool, constrained by caps, same-bookmaker identity and conservative dependence bounds |
| Prepare | Ticket Builder | Actual PAPER tickets, leg records and betslips; duplicate signatures are reused |
| Verify | Betslip Preparation | Recalculated leg/selection identity, bookmaker, quote, combined odds and risk proof; internal PAPER verification only |
| Monitor | Live Operations | Persisted repeated risk checks, stale/revoked input alerts, incidents and paper suspension |
| Reconcile | Match Results | Verified source-linked FINAL results and versioned forecast settlement; corrections retain prior results |

Every dashboard card and orchestrator card opens its assigned page with `run_id`, `fixture_id` and stage context. The shared context panel displays stage status, percentage, timestamps, retry count, recorded inputs/outputs, operation receipts and fixture-specific datasets. Stage evidence can be inspected without inventing missing data. Betting Programmes initially opens the singles page and provides contextual links to all five programme workspaces.

## Scheduling, dependencies and recovery

- `autonomy.cycle` checks the transactional event queue every five seconds; a thirty-second sweep is the fallback. The existing pipeline recheck/drive tasks are retained as compatibility entry points but are no longer separately scheduled.
- ORM mutations to fixtures, observations, quotes, source permissions, models, research, features, results and ticket records publish an outbox event in the same database transaction. A rollback also rolls back its event. Raw SQL writers are covered by scheduled reconciliation/sweeps rather than falsely claimed ORM events.
- A persisted runtime lease prevents concurrent controllers from doing the same work. PostgreSQL row locks protect runs, and advisory locks protect programme exposure and result version assignment.
- One canonical PAPER run is automatically created per fixture within the planning window. Existing runs are adopted rather than duplicated; authenticated API run creation also reuses an existing fixture run.
- Event delivery has leases, acknowledgments, bounded retries and dead-letter status. Fan-out retains undelivered run IDs across batches rather than losing events after the first 25 runs.
- Each stage has measured execution time, error/wait reason, retry count and next retry time. Unexpected operation errors back off and become FAILED after five attempts. New committed input and server-configuration-change events trigger gated recovery; they cannot assert completion.
- Missing evidence yields WAITING_FOR_DATA; policy/data rejection yields BLOCKED. Neither is reported as successful execution.
- Acquisition and monitoring keep running through the same runner. A run with the first eleven stages complete remains MONITORING until a verified final result can be reconciled. Final-result processing is also permitted independently of an unqualified betting path: the result page may update even when prediction gates are blocked. A run is COMPLETED only when all twelve actual operations have evidence.
- Legacy VERIFIED stage labels are revalidated when they lack a matching server-created operation receipt.

## Live source configuration

The local installation enables OpenLigaDB fixture discovery under its published ODbL licence, with attribution, central caching, change checks, jitter and backoff. Its community-maintained fixture facts are **not** promoted to independently verified research, official results, bookmaker prices or predictions. Other installations can opt in with `SPORTS_OPENLIGADB_ENABLED=1`; the example environment defaults to disabled.

For licensed structured research feeds:

```text
SPORTS_DISCOVERY_FEEDS_JSON={"registered-source-id":"https://licensed-provider.example/fixtures"}
SPORTS_SOURCE_FEEDS_JSON={"registered-source-id":{"recent_form":"https://licensed-provider.example/fixtures/{fixture_id}/form","market_odds":"https://licensed-provider.example/fixtures/{fixture_id}/prices","official_result":"https://licensed-provider.example/fixtures/{fixture_id}/result"}}
```

Feed configuration is server-side. `{fixture_id}` is URL-encoded before use. Only configured public HTTPS feeds are fetched, and the registered source must remain enabled and AUTHORIZED. Existing acquisition response-size limits, redirect/private-address restrictions, job leases and retry budgets apply. The response envelope includes the canonical `fixture_id`, `section` and structured `data`. All seven research sections are needed for a verified dossier.

Research quorum is opt-in and does not treat source authorization as independent verification:

```text
SPORTS_RESEARCH_QUORUM_JSON={"source-a":{"reviewed":true,"independence_group":"provider-a"},"source-b":{"reviewed":true,"independence_group":"provider-b"}}
```

Independence groups must be assessed when configuring sources. Two distinct configured groups must agree on the section's actual structured content. Disagreement or missing sections stops the stage. Existing explicit independent-review evidence remains accepted. No OCR/model output self-certifies its truth.

The numeric feature contract is unchanged:

- `recent_form.data`: `home_form`, `away_form`.
- `match_statistics.data`: `home_scoring_rate`, `away_scoring_rate`, `home_conceding_rate`, `away_conceding_rate`.

Values must be finite numbers in 0..10, corroborated by the verified dossier and known before kickoff. Missing values are not filled with defaults. Models must already carry independently reviewed approval/calibration metadata and a valid artifact; registering a name or having an API connection is insufficient.

`market_odds.data.prices` contains source-provided `bookmaker`, `market_key` (`1X2`), `outcome_key` (`HOME`, `DRAW`, `AWAY`), `decimal_odds` and timezone-aware `observed_at`. Quote evidence is linked through `markets.odds_evidence`. All three same-bookmaker outcomes must be current; overround must be 0.90..1.25 and quotes must be at most fifteen minutes old. Existing model, calibration, mapping and value gates are recomputed by the qualification service. Multi-leg PAPER allocations use the optimizer's Frechet lower probability bound and require a positive conservative return bound; independence is never assumed.

## Paper mode and verification

No real-money submission is implemented or enabled. Verify refers to the independently rechecked **paper betslip**, as requested; it no longer waits for an unrelated external booking-code provider. The separate Booking Codes page remains genuine-code-only and does not fabricate provider confirmations.

Monitoring records state their scope as internal PAPER risk monitoring. They do not claim to be an external bookmaker monitoring service. Revoked source/model approval or stale input suspends paper tickets and opens an incident. Final results still require valid source-linked provenance and a validated FINAL outcome map. Result corrections create new versions and settlement history.

## APIs and persistence

Migration `0010` stores controller/provider heartbeat and caching. Migration `0011` adds:

- `operations.pipeline_events`: transactional event queue, leases, attempts and acknowledgments.
- `operations.stage_records`: immutable operation receipts with evidence and scope.
- `markets.odds_evidence`: source observation provenance for quotes.
- Stage operation keys and next-retry timestamps.

Key read APIs:

- `GET /api/v1/sports/dashboard/autonomous?hours=24|72|168`
- `GET /api/v1/sports/autonomy/status`
- `GET /api/v1/sports/pipeline/runs` and `/runs/{run_id}`
- `GET /api/v1/sports/pipeline/context?run_id=<id>&fixture_id=<id>`
- `GET /api/v1/sports/pipeline/events?fixture_id=<id>&status=<status>`

Source setup and administrator mutations remain authenticated. The pipeline uses `SPORTS_ADMIN_TOKEN`, with the older `ADMIN_API_TOKEN` accepted for compatibility. Client context and supplied IDs never replace backend evidence.

## Run and verify

Run `npm run dev` from the repository root after applying migrations. This starts one API, one local scheduler/worker and the frontend. Docker uses the existing worker/beat deployment and the same task registry. PostgreSQL connection parts are passed separately in Docker, avoiding URL parsing errors with special password characters.

Full automated validation:

```powershell
$env:PYTHONPATH='apps/api;.'
$env:SPORTS_TEST_DATABASE_URL='<PostgreSQL URL for an account permitted to create disposable test databases>'
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests tests -q
npm run build
$env:CACSMS_BROWSER_CHANNEL='msedge'
apps/api/.venv/Scripts/python.exe scripts/verify_workflow_ui.py
```

PostgreSQL acceptance tests create and remove their own databases. They execute the actual discovery/provenance, research, feature, inference, market evaluation, qualification, allocation, ticket, verification, monitoring and settlement services without mocking those operations. Controlled test inputs and an approved test artifact are confined to test databases; they are never seeded into the user's application database. Tests also cover event rollback/fan-out/recovery, conflicting evidence, calibration rejection, stale prices, tampering, source revocation, duplicate prevention, multi-fixture allocation and final-result corrections. GitHub Actions runs the full backend suite, fresh migrations, frontend build and Docker validation/build.

The browser verifier uses the real running API, checks all twelve stage destinations and all 29 pages, preserves context, and verifies desktop/tablet/mobile layouts. It does not substitute mock dashboard records.

## Current live limits

The code can execute the full paper workflow when its contracts and approvals are satisfied. OpenLigaDB supplies fixtures but not the seven independently corroborated research sections, calibrated model artifacts or licensed odds feeds. Those missing inputs are shown as live blockers. A test reaching twelve verified stages is not represented as a production prediction or a claim that an unconfigured provider exists.
