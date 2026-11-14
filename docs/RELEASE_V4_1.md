# Cacsms Sports v4.1 — Archive parity and evidence workspaces

## Archive audit
The v4.0 archive contains all 237 non-directory files from v3.9 and two additional files. v3.9 uncompressed 353,891 bytes, v4.0 uncompressed 360,115 bytes. ZIP archive size differences are not evidence of omitted source.

## Frontend changes
Dedicated API-backed domain workspaces for Fixtures, League Tables, Match Analysis, AI Predictions, Market Intelligence, AI Qualification and Qualified Opportunities. Each has domain-specific dataset tabs, search, filters, responsive record views, detailed evidence modal, quality gate and no mock data. ResearchCoverage remains the dedicated Deep Research workspace. Existing routes preserved.

## Constraints
The workspaces are read-only. They do not create or certify source evidence. No live provider or production website was verified by this release. Missing API data is displayed as missing, not simulated.

## Build
From apps/web run `npm ci` (or npm install if no lockfile) then `npm run build`. Verify API response schemas, Postgres and Docker separately.
