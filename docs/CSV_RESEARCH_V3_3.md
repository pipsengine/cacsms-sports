# v3.3 CSV research integration

The supplied `cacsms-sports-v3.3-csv-research` update is integrated into the existing research catalogue. The archive's second migration 0008 and parallel standings schema were adapted into migration **0009** on the existing `research.standings_snapshots` table. Shared filters, fixture dossiers, top-two form, source permissions and the collapsible sidebar remain available.

## Added

- Operator-supplied authorized football CSV to provisional standings JSON.
- Structural JSON validation, dry-run mode, permission-gated import, immutable deduplication and pending/verified review status.
- Review attribution, import timestamps, SHA-256 document and CSV hashes, methodology and audit records.
- Overall/home/away source coverage and approved snapshot history in League Tables & Statistics, plus club-name search and form.
- Existing administrative verified standings intake remains supported. Historical reads require both capture and verification by the cutoff, and current source authorization.

## Prepare authorized data

Register a source through the existing source registry only when you have permission to use the dataset. Obtain an authorized local CSV with these columns:

```text
Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
```

Dates support `DD/MM/YYYY` and `DD/MM/YY`. FTR must be H, D or A and agree with the scores. Case-only club variations are merged; duplicate fixtures use parsed dates and normalized names. This does not resolve aliases, e.g. shortened vs full club names.

A date-only CSV does not establish when the final result or later corrections became known. The builder excludes the entire cutoff day until the next UTC midnight and marks all output provisional. No network requests, scraping or automatic approval occur.

From `apps/api` in PowerShell:

```powershell
.venv/Scripts/python.exe scripts/build_standings_from_csv.py C:/data/league.csv --country England --competition "Premier League" --season "2025/26" --source "Authorized CSV" --source-url "https://provider.example/permitted" --as-of "2026-06-01T00:00:00Z" --confirm-authorized --output C:/data/standings.json
.venv/Scripts/python.exe scripts/import_standings.py C:/data/standings.json --dry-run
```

Use a real authorized source name and evidence URL. These command values are illustrative. The JSON example in `docs/standings_import_example.json` is also illustrative and is never automatically ingested.

## Seasons and database import

The builder accepts `--season-start YYYY-MM-DD --season-end YYYY-MM-DD` to include explicit season boundaries. Otherwise register the season first through the existing `/api/v1/sports/admin/research/seasons` endpoint. Season dates are never inferred from a label; imported CSV match dates must fit the registered boundaries. A JSON import may create a competition and season when explicit dates are supplied. Existing fixtures are not automatically backfilled or modified.

```powershell
.venv/Scripts/python.exe scripts/import_standings.py C:/data/standings.json
```

Actual import loads the root Git-ignored `.env` and respects an existing `DATABASE_URL`. The source must already be registered, enabled and AUTHORIZED. Imports default to **PENDING_REVIEW**. Pending rankings are excluded from standings, top-two source data and approved history; their presence is visible in coverage. Dry-run validates structure only and never queries the database or asserts source authorization.

For an independently reviewed **new** snapshot document, populate `reviewed_by` and use `--approve`. The actual verification time is the import time, so a table reviewed in November cannot appear in an October cutoff query. CSV-derived tables remain explicitly provisional and nonofficial even after review.

Exact re-import returns EXISTS. Adding review metadata to a pending document does not promote it. No pending-record promotion endpoint is included; this follows the supplied update's immutable review behavior. Do not change metadata merely to circumvent review. A distinct reviewed revision requires a genuine new source/content reference. Caller-owned transactions prevent partial imports on validation failure.

## Read endpoints

New APIs use the existing catalogue namespace:

- `GET /api/v1/sports/research/catalog/coverage?league_id=<id>&season_id=<id>&as_of=<optional-offset-aware-cutoff>`
- `GET /api/v1/sports/research/catalog/standings/history?league_id=<id>&season_id=<id>&scope=overall&before=<optional-offset-aware-cutoff>&limit=20`

All source-table views require current enabled AUTHORIZED sources. Coverage counts verified and pending snapshots by exact scope; an older verified table can remain available while a newer revision awaits review. Approved history is limited to 100 snapshots. Computed fixture standings remain separate from source-snapshot coverage.

## Migration and validation

Migration 0009 was applied to the configured local database. Existing verified snapshots retain their status. It adds nullable verification for pending imports, review attribution, provenance and import time. Downgrade refuses to discard pending evidence; resolve pending records through an explicit archival/review workflow before rolling back.

Validation covers the supplied adapter tests, CSV date and club normalization, cutoff-day exclusion, permission checks, dry-run behavior, pending visibility, immutable replays, source revocation, season boundaries and approval-time integrity. Fresh PostgreSQL migration and downgrade/upgrade were tested. The complete CSV-to-JSON-to-import pipeline was also exercised in a disposable PostgreSQL database; no example sports data was imported into the user's application database.
