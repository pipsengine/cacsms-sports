# Standings API integration

The supplied `cacsms-standings-api` reference package is integrated into the existing API and League Tables & Statistics page. The sidebar is unchanged. No standalone app, SQLite database, duplicate `cs_` tables, separate admin key or second scheduler is created.

## Data and scheduling

- Canonical sports, competitions, seasons and fixtures remain in the existing schemas.
- Football-Data source registrations and sync leases use `ProviderSyncState`; immutable CSV captures use `Observation`; sync runs use `AuditEvent`.
- Authorized sources are checked by the existing autonomous worker every cycle. Downloads run when due (six hours after success), with bounded retries and a five-minute acquisition lease.
- HTTPS host/path/season/division validation, no redirects, streaming 8 MB limit, score/result checks and strict atomic imports are enforced. Invalid/conflicting rows fail the whole import. Identical duplicates are ignored.
- Date-only rows are included only after their UTC day has elapsed. CSV-derived fixture timestamps have date precision; midnight is a storage convention, not a claimed kickoff time.
- Identical captures do not republish standings updates. Corrections, including A-to-B-to-A changes, create immutable captures and durable `standings.updated` events. Pipeline invalidation is restricted to the affected competition.
- Overall, home and away tables, form and analytics remain computed/unofficial. They do not become verified results, reviewed standings or eligible prediction evidence. Official deductions and competition-specific tie-breakers are excluded.
- Historical cutoffs use captured knowledge, not just match dates; unavailable past knowledge stays unavailable. Revoked sources are hidden and no longer collected.

## API

Prefix: `/api/v1/sports/standings`.

Read endpoints: `/sports`, `/countries?sport=Football`, `/competitions?sport=Football&country=England`, `/seasons?competition_id=...`, `/table`, `/top-two`, `/analytics`, `/history`, `/health`.

Table parameters: `competition_id`, `season` (canonical season ID, `YYYY/YYYY`, or `YYYY/YY`), `mode=overall|home|away`, optional timezone-aware `as_of`, `page`, `page_size` (1–100). Competition IDs may be canonical IDs or registered external aliases. The response preserves package table aliases (`P/W/D/L/GF/GA/GD/Pts`) alongside canonical field names and an explicit provenance `classification`.

Analytics distinguish date trends from matchday trends. Health reports recorded syncs, next scheduled check, authorization and failures; current source reachability and data-quality scores remain unknown unless actually measured. History shows CSV synchronization runs; the page also retains existing reviewed-snapshot history.

## Register an authorized source

Use the existing `SPORTS_ADMIN_TOKEN` and `X-Admin-Token` header. The reference package's separate `CACSMS_ADMIN_KEY` / `X-Admin-Key` is not used. Never put an admin token in frontend code.

`POST /api/v1/sports/standings/admin/competitions`:

```json
{
  "id": "eng-e0",
  "sport": "Football",
  "country": "England",
  "name": "Premier League",
  "division_code": "E0",
  "source_url": "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
  "authorized": true,
  "points_win": 3
}
```

This example targets **2025/2026**, not the current season. Register the intended season's URL and confirm authorization for that source. Registration alone does not download data unless authorized. The existing worker will collect due sources. To request immediate acquisition, use `POST /api/v1/sports/standings/admin/sync/eng-e0` with `{"season":"2025/2026"}` and the same admin header.

No Football-Data source is silently authorized or downloaded by installing this integration. Existing OpenLigaDB collection continues independently. No new dependencies or schema migration are required.

## Verification

Backend coverage includes URL restrictions, authorization, season mismatch, malformed/conflicting CSVs, idempotence, corrections, historical knowledge, revocation, failure preservation, scheduler caching, API pagination and analytics. `scripts/verify_league_ui.py` checks the sidebar, selectors, scopes, tabs, search, pagination, error states and responsive overflow using isolated browser test responses. The live PostgreSQL/OpenLigaDB page was checked separately. Football-Data downloads were tested with controlled CSV responses, not a live third-party feed.
