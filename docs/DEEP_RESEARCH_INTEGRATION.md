# Deep Match Research design/API integration

The supplied Deep Match Research Figma/API package is adapted into `/sports/research` without changing the sidebar or other page routes. The page uses the existing shared research selectors, live updates and background worker. It adds no manual sync/research button, separate timer or acquisition engine. Background refresh keeps the selected fixture, filters and visible data intact.

## Components and API

- `apps/web/src/DeepMatchResearch.tsx` and `.css`: reference-inspired metric cards, pipeline strip, cascading selectors, fixture banner, eight tabs, intelligence summary, top-two comparison, recent H2H, coverage and evidence panels. Header autonomy status reflects the recorded worker heartbeat.
- `apps/api/app/modules/research/deep_workspace_routes.py`: `GET /api/v1/sports/research/workspace/{fixture_id}`, optionally `as_of` with a timezone-aware timestamp.
- Catalogue endpoints use the project's existing `/api/v1/sports/research/catalog/` namespace. Fixture selection respects the selected season and supports `?fixture_id=...` workflow links.

## Evidence rules

The endpoint uses existing canonical fixture, season, research, observation, source, result and pipeline records. No schema migration or new package is needed. Illustrative reference-image numbers, team logos, rankings and coverage percentages are not installed as product data. Team initials are used where no licensed crest asset is available.

The pre-match research cutoff is the earlier of the requested/current time and fixture kickoff. Later evidence, dossiers, standings captures and result corrections cannot leak into that view. Coverage requires a verified section with explicit section-specific and dossier evidence links, the correct fixture and section, an enabled authorized provider, and an eligible observation timestamp. Canonical snake-case section names and the supplied human-readable aliases are mapped consistently. An unavailable section stays explicitly unavailable; it is not shown as verified evidence. Raw authorized observations remain labelled as recorded observations, with their payloads and source links available in the appropriate tabs.

League comparisons use only standings available at that cutoff and preserve their provenance warnings. H2H, average goals and clean sheets require verified result evidence. Missing statistics remain missing. Source authorization counts do not imply current source reachability. The next controller cycle is not represented as a guaranteed next research completion time. Evidence is bounded to the latest 500 eligible observations and metrics are database counts, not simulated figures.

## Validation

`apps/api/tests/test_deep_workspace.py` covers section-name mapping, source revocation, fixture/section links, cutoff isolation and read-only endpoint behavior. `python scripts/verify_deep_research_ui.py` checks all eight tabs, filters, deep links, populated evidence, slow automatic refresh, desktop/mobile layouts and browser errors with isolated test responses. The live PostgreSQL page is checked separately; incomplete evidence remains incomplete.
