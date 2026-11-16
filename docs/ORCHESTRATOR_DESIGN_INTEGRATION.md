# Engine Orchestrator design integration

The supplied `CACSMS_Engine_Orchestrator/cacsms-orchestrator` design is adapted at `/sports/orchestrator`. The existing application sidebar is preserved. No standalone scheduler, duplicate orchestrator tables, upstream placeholder collectors or browser admin-key prompt are introduced.

## Interface

The page displays execution mode, selected run, start time, recorded elapsed time (including waiting), run status, settled stages, business outcomes, blocked/failed stages, current retries and average persisted stage duration. Graph and list views render all twelve canonical stages. Run search/selection and stage selection retain deep-link context; a requested run outside the latest 30 is loaded directly instead of silently substituting another run.

Stage details provide:

- current persisted timing, versions, output reference, quality score, next stage/retry, evidence count and failure code;
- required-input/validation/output documentation, derived from the canonical engine's operations and dependency policies;
- raw recorded input/output payloads;
- resolved references actually listed on the selected run/stage;
- immutable attempts from the existing history API.

Validation-rule chips describe requirements, not proof that those requirements passed. SLA remains unconfigured because no persisted SLA policy exists. Missing references remain visibly unresolved. Payloads of observations from disabled/unauthorized sources are redacted. Source evidence resolution is batched by canonical entity type rather than querying separately for every reference.

## Execution behavior

The existing `autonomy.service` and `pipeline.runner` remain the only execution engine. The pre-match chain, independent Monitor/Reconcile stages, lease recovery, receipts, retries, invalidation rules and business outcomes are unchanged. Terminal business outcomes settle their stage and divert work to monitoring; they are not technical failures.

Refresh is a read-only reload. **Pause updates** freezes display refresh only; the autonomous background worker continues. Resume updates catches up with the current state. The interface does not create runs, execute stages, pause the engine, submit wagers or request admin credentials. It reuses the shared live-update provider and stable background-fetch hook, with no competing polling timer.

## Read endpoints

Existing endpoints reused: `/api/v1/sports/pipeline/runs`, `/runs/{id}`, `/runs/{id}/history?stage=...`, and `/api/v1/sports/autonomy/status`.

Added endpoints:

- `GET /api/v1/sports/pipeline/contracts` — twelve canonical operation definitions, real dependency policies and no fabricated SLA.
- `GET /api/v1/sports/pipeline/runs/{id}/evidence?stage=...` — references recorded on the requested stage only, with unresolved/revoked states visible.

No database migration or new package is required.

## Validation

`apps/api/tests/test_orchestrator_workspace.py` checks definition ordering/dependencies, recorded-only evidence access, source revocation/redaction and non-mutation. Existing pipeline/autonomy tests run alongside it. `python scripts/verify_orchestrator_ui.py` checks all twelve stages, graph/list mode, run/stage links, the four detail tabs, display pause/resume, background refresh stability, preserved sidebar and responsive overflow using isolated responses. The live PostgreSQL dashboard was checked separately with no browser/API errors. The mocked reference run is never installed as product data.
