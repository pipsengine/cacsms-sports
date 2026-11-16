# Fully autonomous operation (no human input)

With `SPORTS_OPENLIGADB_ENABLED=1`, the autonomy cycle (every 5 s, `app.modules.acquisition.dev_scheduler` locally or Celery beat)
now runs the whole pre-match chain unattended for the Bundesliga:

| Step | Module | Cadence | Rule |
|---|---|---|---|
| Fixtures | `autonomy/openligadb.py` | change-driven | OpenLigaDB current season |
| History cache | `autonomy/open_intelligence.refresh_history` | current season hourly; past seasons once | last `SPORTS_HISTORY_SEASONS` seasons from **OpenLigaDB** and **Football-Data.co.uk** |
| Verified results | `corroborate_results` | every minute (backfill 500/run) | `official_result` from **both** providers only when final scores agree; existing reconciler settles |
| Research evidence | `produce_evidence` | every 10 min | each provider independently computes form, scoring/conceding rates, H2H and standings up to the latest date **both** have published; research quorum verifies only identical values |
| Uncovered sections | `pipeline/operations.research` | each run | team news / lineups / injuries → `UNAVAILABLE` (`NO_SOURCE_COVERAGE`) while no authorized source supplies them |
| Model | `autonomy/modelling.train_if_due` | hourly check; weekly retrain or while backfilling | challenger from corroborated results (features from earlier matches only), promoted **only** by `governance.promotion` gates (beats baseline Brier and log-loss out of sample, ECE ≤ `SPORTS_MODEL_MAX_ECE`) |
| Predictions | existing `predict` stage | each run | ACTIVE model, verified dossier, pre-kickoff cutoff |
| Odds | `collect_odds` | every 30 min | Football-Data `fixtures.csv` (1X2, O/U 2.5, Asian handicap per bookmaker), stamped with the file's Last-Modified time |

Measured on live data (dry run, 16 Nov 2026): 1,305 corroborated results (0 disagreements), challenger promoted automatically
(holdout Brier 0.222 vs baseline 0.248, n=378, calibration error 0.048), 9/9 upcoming fixtures verified → features → predictions.

Limits, by design:
- **Football-Data odds are indicative**: published a few times a week, so the 15-minute freshness gate keeps `evaluate`/`qualify`
  at `NO_FRESH_MARKET`; no paper tickets are created from stale prices.
- **No SportyBet data**: no permitted feed exists; nothing scrapes it.
- **Home-win model only** (existing feature/model contract); Draw/Away are shown as not modelled.
- Disable with `SPORTS_FOOTBALL_DATA_ENABLED=0`. Tests: `apps/api/tests/test_open_intelligence.py`.

## BetExplorer: prohibited source (checked 2026-11-16)

BetExplorer (Livesport s.r.o.) was evaluated for autonomous browser acquisition and **rejected**. Its Terms of Service
(https://www.betexplorer.com/terms-of-service.php) state:

- "you are not permitted to use our content available on the Website by embedding, aggregating, scraping or recreating it without our express consent"
- "no extraction (copying) or exploitation … of the Database Content or of a qualitatively or quantitatively substantial part thereof is permitted without our express consent"
- "You must not burden our server on which the Website is hosted with automated requests"

robots.txt alone would allow some paths, but the terms govern. No BetExplorer navigation test or extraction was run, because
that test would itself be the prohibited activity.

Enforcement (`app/modules/acquisition/source_policy.py`):
- Browser & Vision capture (`vision/security.validate_destination`) and feed/collector URLs (`acquisition/jobs.validate_feed_url`)
  refuse `betexplorer.com` and subdomains, even if a host is added to an allowlist.
- The autonomy cycle registers BetExplorer as a disabled `PROHIBITED` source with an audit event; any `AUTHORIZED` row is downgraded.
- Source Intelligence → *Source registry & sync* (`GET /api/v1/sports/sources/registry`) and Browser & Vision Operator readiness show the restriction.
- Only a recorded express written consent lifts it: `SPORTS_SOURCE_CONSENT=betexplorer.com=<consent reference>`.

Authorized alternative in use: OpenLigaDB + Football-Data.co.uk (above). These are structured, permitted feeds, so no
browser automation is needed for acquisition.
