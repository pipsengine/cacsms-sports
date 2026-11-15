# Research scaffold integration

Adapted from `cacsms-sport-ai-v2.9-expanded` supplied on 15 November 2026.

The existing platform has a newer, incompatible schema and already provides permission-gated acquisition, raw observation hashes, evidence ingestion, odds, predictions and settlement. Its schema, deployment configuration, source authentication and model approval gates are retained. The archive is not copied over the application.

## Added

- Research page: select a football competition and optional season start / historical cutoff, then view computed top two, points, W/D/L, goals difference, recent form and head-to-head.
- `GET /api/v1/sports/competitions` lists competition IDs.
- `GET /api/v1/sports/competitions/{id}/top-two/research?recent=5&as_of=2026-11-15T11:00:00Z&since=2026-08-01T00:00:00Z` uses timezone-aware cutoffs. `recent` is 1?20.
- Existing official result intake accepts optional `score: {"home": 2, "away": 0}` alongside required FINAL status and market outcomes. Scores persist in existing JSON; no schema migration is needed.
- Standings use the latest result version verified by the cutoff, matching fixture/source observations and current authorized, enabled sources. Missing scores or evidence are excluded; superseded scores never replace an invalid correction.
- The supplied Poisson arithmetic is retained as an isolated research utility, without model registration or qualification.

## Data and limitations

Use existing administrator-controlled fixture, observation and official-result intake to populate real evidence. Existing results without explicit full-time scores cannot produce standings. No data or source permissions were invented. Standings use 3/1/0 points, goal difference and goals scored, then club name for deterministic ordering. They are not official; club aliases, deductions and competition rules are not resolved. Without `since`, all available history is included. Source permission changes can alter historical reports.

## Archive components retained through existing services

The scaffold's standalone source API, raw SQL tables, Docker deployment and CSV importer are not installed over the existing equivalents. Its CSV importer writes unverified `final` fixtures while its league query expects verified `finished` fixtures; it cannot safely populate this project's evidence-backed results. Import historical data through the existing evidence workflow. The uncalibrated fixture baseline is not connected to predictions or market qualification.
