# Research data remediation — 19 November 2026

Fixture discovery was succeeding while research still showed a generic waiting
message. Discovery's team histories were stored as side-specific observations,
but were not assembled into research sections. TheSportsDB also had no built-in
research independence group. Some fixtures, including the women's fixture shown
in the report, have fixture identity evidence without either team's history.

## Implemented

- Added a discovery-history research bridge for authorized OpenLigaDB and
  TheSportsDB data. It validates successful collector jobs, fixture/team mappings,
  competition and season scope, timestamps, score types and duplicate matches.
- Both teams' histories produce provisional form and scoring/conceding sample
  metrics, with original match dates and parent observation references. Repeated
  pipeline runs reuse the same derived observations. Capture timestamps use the
  later parent capture, when both inputs became available.
- Registered provider independence groups with section/producer restrictions.
  Existing open-intelligence source policy remains compatible; explicit reviewed
  configuration still overrides built-in policy.
- Development histories remain partial, even with ten returned matches. These
  collectors do not establish complete recent-match windows. Their derived
  samples cannot satisfy research quorum or feed verified model features.
- Added per-provider and per-team readiness to the research workspace and pipeline
  failure details. Managed fixtures without histories now retain a partial dossier
  and a specific missing-data explanation.
- Stale, revoked, failed-job and changed-mapping parents cannot supply current
  derived sections. A stale team's result dates remain stale in the UI even when
  the other team's results or the capture date are recent.
- Fixed three PostgreSQL tests that committed test records outside the shared
  transaction and contaminated later tests. Existing working-tree changes were
  backed up before this work and preserved.

## Genuine live outcome

The local PAPER stack was restarted with the integration. At the initial live
check, the worker had generated 20 provisional observations across nine fixtures
from 768 stored history observations. These are real local records, not test data.

For **Austria Wien (Women) vs FC Bayern München Frauen**, the refreshed pipeline
records: OpenLigaDB has no collected completed-match history for either team;
TheSportsDB has no mapping for this fixture. The research page shows both
limitations, and the dossier remains partial. Refreshing cannot create missing
provider coverage. An independent review or sufficient complete histories from
independent permitted sources is still required. Fresh market prices remain a
separate requirement; this change does not relax their 15-minute freshness gate.

## Validation

- Full backend suite, including disposable PostgreSQL integration: 432 passed.
- After the final capture/freshness adjustment: 20 focused bridge/workspace tests
  passed, including stale-team dates and use of the later parent capture.
- TypeScript and production frontend build passed.
- Desktop (1440px) and mobile (390px) research coverage checks passed, with no
  JavaScript errors or document horizontal overflow.
- All 29 application pages passed navigation checks, with no API or JavaScript
  errors; responsive checks passed at 390, 768, 1280 and 1920px. An initial run
  timed out on market requests; the subsequent complete run passed.
- Evidence and screenshots: `artifacts/research-integration/`.

The work is on `fix/2026-11-19-research-evidence`. Existing uncommitted work remains
uncommitted; a baseline backup is in `artifacts/research-integration/baseline/`.
