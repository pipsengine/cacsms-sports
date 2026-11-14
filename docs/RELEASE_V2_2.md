# V2.2 — Authorized observation acquisition and feature integrity

This release adds **actual API and service code** for manual/connector-fed, authorized structured research evidence, plus materialized feature snapshots. It does **not** claim live automated web acquisition, screenshot interpretation, predictive modelling, or bookmaker integration.

## New endpoints
- `POST /api/v1/sports/admin/research/observations` — administrator-only, authorized-source evidence ingestion, section, fixture, URL, observed timestamp and nonempty structured payload required. Deduplicates by SHA-256 canonical observation hash.
- `GET /api/v1/sports/fixtures/{id}/observations` — read provenance records.
- `POST /api/v1/sports/admin/features/materialize` — verifies each required research section, authorized evidence, section/fixture match and that observations precede the feature cutoff and kickoff.
- `GET /api/v1/sports/research/{id}/features` — view feature snapshot provenance.
- `GET /api/v1/sports/research/evidence-coverage` — count stored observations by section; **not** a verified-research indicator.

## Safety and limitations
- `SPORTS_ADMIN_TOKEN` must be configured before mutations work.
- Existing `sources.providers` entries must be authorized and enabled by the administrator.
- This endpoint is for structured data supplied by authorized connectors; it does not fetch arbitrary URLs, preventing server-side request forgery.
- Feature snapshots contain verified *observations*, not engineered numeric sports predictors. They cannot authorize model activation.
- No live wagers or booking-code claims.
- API generic catchall route moved to the end to avoid masking the new named endpoints.

## Next increment
Authorized scheduled connector adapters with provider-specific schemas, durable job leasing, source rate limits and observed fixture reconciliation. No paid or unauthorized scraping sources should be assumed.
