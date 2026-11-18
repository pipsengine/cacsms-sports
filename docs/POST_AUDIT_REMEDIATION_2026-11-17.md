# Post-audit remediation — 17 November 2026

## Outcome and scope

Implemented in the existing repository on `remediation/2026-11-17-odds-intelligence`,
starting from clean `main` at `7914a97`. The attachment's branch and commit were not
the checked-out baseline. No existing changes were discarded. No application was
replaced, and no historical fixtures, prices or source observations were deleted.

**PAPER research operation is running. Production readiness is not asserted.**
There is still no verified authorized current price feed covering the upcoming
Bundesliga fixtures. The existing public read API also needs a deployment-specific
access boundary before exposure outside a trusted environment.

## Baseline and verification

| Check | Before | After |
|---|---|---|
| PostgreSQL | Read-only connection confirmed, `0015` | `0017` applied by normal development startup |
| Regression suite | 264 passed, 19 PostgreSQL tests skipped without test URL | 331 API tests plus 32 repository tests passed; none skipped; includes disposable PostgreSQL |
| Migration lifecycle | Existing audit evidence only | Fresh install, downgrade to `0010`, upgrade to head tested on disposable PostgreSQL |
| Frontend | Type check/build passed; 743.66 kB main JS chunk | Type check/build passed; 422.71 kB main JS chunk; route chunks; no size warning |
| UI inventory | Attachment said 30 | Actual navigation contains 29 pages; all covered by the Playwright harness |
| npm audit | Re-run | Zero known vulnerabilities |
| Python requirements audit | Re-run | Resolved requirements graph: zero known vulnerabilities |
| Shared Python environment | Includes global system packages | Initial audit found 147 advisories in 13 packages; not a clean deployment environment |

The backend suite emits deprecation warnings from the older installed pytest/asyncio
plugin combination; these are not suppressed in the saved evidence, except the
console warning summary. They remain maintenance work. The requirements resolution
audit is distinct from an audit of installed host packages.

## Before-and-after defect register

| Finding | Remediation | Status |
|---|---|---|
| D-01 browser redirect bypass | Existing per-hop policy retained; new CDN tests also enforce it | Tested |
| D-02 research coverage | Existing reviewed-source coverage retained | Regression tested |
| D-03 booking readiness shadowing | Existing delegation retained | Regression tested |
| D-04 duplicate main routes | Existing fix retained; all method/path pairs now checked | Tested |
| D-05 workflow stage list | Canonical twelve stages retained | Tested |
| D-06 legacy model labels | Reviewed and audited correction of one legacy artifact; registry status and approval flags preserved | Fixed/tested |
| D-07 duplicate learning summary | Removed redundant declaration and route-test exemption | Fixed/tested |
| D-08 empty evaluation endpoint | Returns persisted, paginated per-model history, actual metrics and explicit unavailable fields | Fixed/tested |
| D-09 CDN/capture permission coupling | Separate `SPORTS_BROWSER_SUBRESOURCE_HOSTS`; does not grant navigation permission | Fixed/tested |
| D-10 large frontend chunk | Lazy page imports with a loading boundary | Fixed/build tested |
| R-01 source-free qualification paths | Shared source/provenance/classification checks in scanner, qualification, allocation, programme and ticket paths | Fixed/tested |
| R-02 missing provider timestamp | Acquisition no longer substitutes import time or clips a future timestamp | Fixed/tested |
| R-03 route-local mutation permissions | Application-wide administrator boundary before body processing; every mutation tested without/with invalid credentials | Fixed/tested |
| R-04 price duplication/quality history | Exact-price identity index; conflicting values retained and quarantined; immutable quality assessments | Implemented/PostgreSQL tested |

## Central odds intelligence

The common classifier checks source authorization, source prohibition, fixture and
provider identity, source observation linkage, original provider price/time equality,
decimal range, future/stale timestamps, historical/research declarations and
same-bookmaker conflicts. It retains the 900-second ceiling. Import time never
refreshes a price. Archived closing-price observations remain historical even if
their fixture is subsequently rescheduled.

`FRESH_MARKET` eligibility is an evidence check, not a promise of an executable
bookmaker account or authorization to wager. All operation remains PAPER.

Configurable source profiles record coverage, classification capabilities, collection
method, expected update interval, priority, fallback sources, limitations and policy
references. Updating a profile cannot update provider permission or enable collection.
Fallbacks must reference enabled authorized sources, and only installed adapters can
run. Unconfigured capabilities and unmeasured reliability remain unavailable.

Canonical storage is reused rather than duplicating the same records under eleven
new table names:

| Requested logical record | Actual storage |
|---|---|
| Odds source registry | `sources.providers`, new `sources.odds_sources` |
| Source permissions | Existing provider permission/enabled fields and source-policy audit events |
| Market catalogue | Existing market definitions, categories, outcomes and bookmaker mappings |
| Fixture/market mapping | Existing canonical fixtures, bookmaker availability and odds evidence |
| Odds observations | `sources.observations` plus market evidence |
| Odds snapshots | Existing `markets.odds_snapshots` |
| Acquisition jobs | Existing durable `operations.acquisition_jobs` |
| Quality assessments | New `markets.odds_quality_assessments` |
| Source health | Existing provider synchronization state, job history and registry health |
| Conflicts | Persisted quality assessment reason `CONFLICTING_QUOTES`; conflicting quotes are retained |
| Odds audit events | Existing `audit` event ledger plus append-only quality history |

Quality assessments cannot be updated/deleted through ordinary SQL: migration `0016`
installs a PostgreSQL trigger. Retention defaults to preserving provenance and history;
no automatic deletion policy is enabled. An approved archival/export retention policy
is still required before applying storage caps in a long-lived deployment.

Observation pagination is explicitly over scanned source rows. Classification filters
apply to the current page; follow `next_offset` for additional results. This bounds
expensive archive classification and does not imply that an empty page means the
entire database has no matching observation.

## Authorized adapters and live data evidence

The provider boundary in `markets/providers.py` integrates the existing Football-Data
collector into the autonomous scheduler. New licensed adapters implement the same
interface. Priority/fallback traversal is bounded by the configured installed provider
set. Existing source permissions are checked before collection.

Live probes on this date returned:

- Football-Data upcoming CSV: 51 rows, publication time **2026-11-13 14:16:25 UTC**, zero
  Bundesliga rows. It cannot supply the required upcoming fresh markets at present.
- OpenLigaDB: nine fixtures from its existing documented match-data endpoint. It does
  not supply bookmaker odds; no odds adapter was fabricated for it.
- BetExplorer: remains prohibited. No sports-page extraction, alternative domain,
  undocumented endpoint or proxy bypass was attempted.

Stored counts before the local stack restart: 10,461 fixtures, 238,664 prices,
13,178 source observations and nine pipeline runs. Those counts remained unchanged
in the subsequent live evidence capture. The running governance scheduler legitimately
appended new monitoring evaluations; it did not rewrite previous evaluations.

## Model governance

Evaluation history exposes model/version, timestamp, persisted dataset/window/sample
and scoring fields, governance decision/reasons and evidence where actually stored.
Older snapshots without those fields return null; an unevaluated known model gets an
empty collection with an explanation, and an unknown model gets 404. Future monitoring
stores log loss and window boundaries; future promotion snapshots retain holdout
calibration and approval metadata.

Registry status, current approval flags, computed deployment eligibility and actual
deployment verification are separate response fields. Deployment status is explicitly
UNVERIFIED where no deployment evidence exists. The read API creates review proposals only. The explicit reconciliation CLI rechecks
current validation and matching original promotion audit evidence under a row lock,
and preserves original labels in a new audit event. One previously approved ACTIVE
model received this reviewed cosmetic correction; its registry status and four approval
flags did not change. See [the governance verification](MODEL_GOVERNANCE_VERIFICATION_2026-11-18.md).
Missing approvals must go through the existing promotion gate. No model was activated.

## Autonomous workflow and operational monitoring

The canonical twelve-stage runner, stage receipts, independent Monitor/Reconcile,
durable jobs, worker leases, transactional outbox, retries and restart recovery were
retained and exercised in PostgreSQL tests. Research and prediction precede market
evaluation. Lack of prices produces `NO_FRESH_MARKET` and does not terminate the
independent background tasks. Ticket preparation and programme allocation recheck
source/classification eligibility even for earlier qualified records. Ticket preparation
also rechecks current model status and all four approval flags, so revocation after
qualification blocks a new ticket.

The local stack was restarted after verification. The scheduler resumed, processed
nine runs, reported no cycle errors and correctly waited for fresh markets and
future kickoff. This is a controlled local restart, not evidence of multi-host
production failover or a prolonged unattended soak.

New per-process telemetry measures API response-header latency/errors by route,
PostgreSQL query time/errors, CPU time, resident memory and uptime. Existing diagnostics
continue to expose scheduler/worker/queue/source/stage state. Telemetry resets after
process restart and is not an external monitoring/alerting deployment.

## API and UI deliverables

See [API inventory](REMEDIATION_API_INVENTORY.md) for every operation. OpenAPI includes
administrator API-key requirements on mutations and explicit odds response schemas.
New odds routes expose source profiles, observations, individual eligibility, source
readiness and paginated quality assessments. Existing job, fixture, worker, incident,
audit and stage APIs remain available. Read-only reconciliation and telemetry routes
are also added.

The existing Market Intelligence page gains a backend-connected evidence panel with
historical/research/fresh classifications, original observation time, age, provider,
price and rejection reasons. Other page designs/navigation are preserved. Route code
splitting has a real loading state. The UI harness visits the actual navigation, tests
classification requests, records JavaScript/API failures and captures the market page
at 390, 768, 1280 and 1920 pixels.

The additional interaction harness passed 124 available tab interactions and verified
loading and network-failure states for the new panel. These checks are not a complete
test of every filter, modal, authentication flow,
error state and ticket lifecycle at every viewport. Existing dedicated workflow/UI
scripts and backend ticket/settlement tests remain available; expanding that complete
cross-product is pending work, rather than a claimed acceptance result.

## Deployment and rollback

1. Back up PostgreSQL using the established operator procedure; retain the backup
   outside the source ZIP. Keep `.env`, credentials and browser evidence private.
2. Create a clean Python environment **without** `--system-site-packages`; install
   `apps/api/requirements.txt`. The current shared development environment is not
   a production dependency baseline. Run dependency auditing against the resulting
   installed environment as well as the requirements graph.
3. With existing database credentials in the process environment, run
   `python -m alembic upgrade head` from `apps/api`. Head is `0017`.
4. Run `apps/api/.venv/Scripts/python scripts/run_remediation_checks.py` from the
   repository root. It reads local credentials privately but uses disposable
   databases for PostgreSQL tests and an unavailable ordinary app connection.
5. Run `npm --prefix apps/web run build`; restart API and workers together. The local
   `npm run dev` launcher applies migrations before starting either component.
6. Run `scripts/verify_all_pages.py` with `CACSMS_UI_URL` and optional `CACSMS_API_URL`.
   Inspect `/health`, worker heartbeat, telemetry, quality history and blocked-stage
   reasons. Use HTTPS and a reviewed access boundary for any external deployment.

For rollback, stop the API and workers before changing code/schema. Prefer rolling
back code while retaining additive tables and their evidence. A deliberate schema
rollback to `0015` removes the new source profile and quality tables (and therefore
their newly accumulated history): export those records first. Disposable test
databases verified downgrade/upgrade; no live schema downgrade was performed.

## Remaining blocked or pending work

- **Blocked externally:** an authorized, sufficiently frequent provider covering the
  actual upcoming fixtures/markets; BetExplorer requires verified written permission.
- **Pending review:** source profile coverage/licensing references for any new provider.
  The identified legacy model labels have been reconciled against original promotion
  evidence with an append-only audit record. No automatic activation occurred.
- **Pending production operations:** isolated installed-environment audit, deployment
  access controls, external metrics/alerting, archival retention policy, sustained
  scheduler soak and multi-host failover exercise.
- **Pending QA expansion:** complete UI state/action coverage beyond the documented
  navigation, rendering, 124 tab interactions, loading/network failure, price classification
  and market responsiveness checks.

The source ZIP, commits, migration files, API inventory, automated tests, saved test
logs, live evidence, dependency audit JSON and screenshots distinguish delivered
implementation from these unverified integrations. None of the latter is represented
as production-ready functionality.
