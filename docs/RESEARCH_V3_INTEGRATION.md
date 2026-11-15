# Research UI and catalogue integration (v3.0 source package)

Integrated from `cacsms-sport-ai-v3.0-integrated-update` on 15 November 2026. The supplied standalone scaffold is adapted into this repository's existing React/FastAPI/PostgreSQL application. The existing 29 routes, model governance, source acquisition, browser operator, PAPER safeguards, database connection and collapsible sidebar are preserved.

## User interface

Fixtures & Competitions, League Tables & Statistics, Deep Match Research, Match Analysis, AI Predictions, Source Intelligence and Browser & Vision Operator share a sport/country/league/season selector. Selections persist during navigation; changing a parent clears dependent selections. The optional local-time cutoff applies to standings and dossier evidence. Registration/source and browser operations retain their existing operational datasets; their shared selector establishes research context rather than claiming to filter source permissions by competition.

- Fixtures show real fixture identities and only evidence-backed full-time scores.
- Statistics prefer the latest eligible authorized standings snapshot for the exact season, scope and cutoff. Top two ranks are highlighted, with source provenance and capture/verification timestamps.
- Without a snapshot, overall football standings can be computed from verified result versions. They are explicitly unofficial. Other sports and home/away scopes require matching verified source snapshots.
- Research shows actual fixture observations, research versions, feature snapshots and stored forecasts. Source authorization is distinct from dossier verification. Match Analysis and AI Predictions retain their existing detailed workspaces below the shared fixture evidence view.
- Top-two football form and head-to-head remain available, now scoped to the selected season.

Empty data and API errors are displayed explicitly. No demonstration records were inserted into the local application database.

## Database migration

Migration `0008` adds `sports.competition_seasons`, nullable `fixtures.fixtures.season_id`, and `research.standings_snapshots`. Standings entries are validated and stored together as immutable JSON in each snapshot, avoiding the scaffold's overlapping teams/fixture tables. Snapshot source, URL, reference, content hash, capture time and verification time are retained. No legacy fixtures are assigned a season automatically.

From `apps/api`, with `DATABASE_URL` and repository `PYTHONPATH` configured:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
```

Migration 0008 was applied to the configured local database. A fresh PostgreSQL upgrade and the 0008 downgrade/upgrade path were also verified in a disposable database.

## Read API

All endpoints are under `/api/v1/sports/research/catalog`:

- `GET /sports`
- `GET /countries?sport=football`
- `GET /leagues?sport=football&country=England`
- `GET /seasons?league_id=<competition-id>`
- `GET /fixtures?league_id=<id>&season_id=<id>&limit=100` (maximum 500)
- `GET /standings?league_id=<id>&season_id=<id>&scope=overall&as_of=<timezone-aware-timestamp>`
- `GET /dossiers/<fixture-id>?as_of=<timezone-aware-timestamp>`

The existing `/api/v1/sports/competitions/{id}/top-two/research` endpoint also accepts `season_id`. Unscoped computed standings combine all available history and warn accordingly. Snapshot standings require a season selection; an all-history table is never silently replaced with a single season's source table.

## Authorized data intake

These endpoints require the configured `SPORTS_ADMIN_TOKEN` in the `X-Admin-Token` header. Credentials remain in the ignored `.env`.

1. Use existing authorized source onboarding and fixture/evidence intake to populate the catalogue.
2. `POST /api/v1/sports/admin/research/seasons` with `competition_id`, `label`, `start_date`, `end_date`, optional `country` and `is_current`. The same competition/label updates an existing season. Date changes cannot exclude assigned fixtures.
3. `POST /api/v1/sports/admin/research/seasons/{id}/fixtures` with `{"fixture_ids":["<fixture-id>"]}` to explicitly backfill membership. Every fixture must match the competition and fall within the season dates; a mixed invalid request rolls back.
4. `POST /api/v1/sports/admin/research/standings` with competition/season/source IDs, public HTTPS `source_url`, nonempty `source_reference`, timezone-aware `captured_at` and `verified_at`, optional `official`, `scope` (`overall`, `home`, `away`) and `entries`. Administrator intake attests verification; it does not fetch or independently validate a source website.

Each standings entry includes `club`, `rank`, `played`, `wins`, `draws`, `losses`, `points`, optional goal totals/difference and optional W/D/L `form`. Supplied goal totals must be internally consistent; played must equal wins/draws/losses. Points may reflect deductions, so they are not forced to 3/1/0 for source tables. Duplicate clubs/ranks are rejected. Snapshots are append-only and exact replays are deduplicated; writes are audited. Only currently authorized, enabled sources can supply or serve snapshots.

## Limits

No new source subscriptions, official standings feeds, browser automation permissions or trained models were invented. Existing fixture names remain the club identity; alias reconciliation and group-stage/competition-specific computed rules are not implemented. Dossier evidence is capped at 200 observations and bounded before kickoff and the requested cutoff. Authorized observations alone do not qualify predictions or wagers. The standalone archive's SQL schema and Docker/placeholder frontend were not copied over the working application.
