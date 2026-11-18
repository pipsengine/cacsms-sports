# Autonomous operation and current limitations

The autonomous controller runs locally using `app.modules.acquisition.dev_scheduler`, or in Docker using Celery
beat and the acquisition worker. With `SPORTS_FIXTURE_DISCOVERY_ENABLED=1`, `SPORTS_OPENLIGADB_ENABLED=1` and
`SPORTS_THESPORTSDB_ENABLED=1`, the existing durable queue can collect fixture data from both APIs independently.
TheSportsDB's public key `123` is for development; the application rejects it in production. Provider coverage is
limited, and an extracted fixture is not independently verified until two authorized sources agree. OpenLigaDB
requires attribution and compliance with its [ODbL licence](https://www.openligadb.de/en/license) and
[API terms](https://www.openligadb.de/en/terms-of-use); TheSportsDB's
[terms](https://www.thesportsdb.com/docs_terms_of_use.php) apply to its API and prohibit scraping its website.
TheSportsDB documents a free-tier limit of 30 requests per minute. Configure a meaningful OpenLigaDB user agent
including a way to contact the operator.

TheSportsDB fixture discovery requests football, basketball, ice hockey, tennis and table tennis. Availability
depends on the provider and API tier; a sport is shown in the catalogue only when actual data is available.
The fixture page also displays configured discovery targets without registered competitions, labelled as targets
rather than acquired sports; these are not selectable until a competition has been discovered.
Ice hockey, tennis and table tennis events without two named participants, a kickoff time or a supported status
are rejected rather than fabricated. An
empty response does not imply the sport or competition is completely covered. Existing football-specific
standings, research and prediction logic is not automatically supported for the other sports.

The target research requirements include match history, team statistics, form at 5/10/20 matches with
home/away splits, head-to-head, standings, formations, lineups, player statistics, injuries and suspensions,
team news, tactical and advanced statistics, schedule context, market intelligence, weather/venue and
multi-season trends. The existing dossier has sections for standings, form, head-to-head, news, lineups,
injuries and match statistics, and the market pipeline accepts separately sourced odds. These sections do not
guarantee every requested field or window. Fixture discovery does not acquire the full research requirements,
and absent data must remain missing or unavailable rather than being inferred as fact. OpenLigaDB's
football history path and existing evidence gates do not establish complete global or multi-sport coverage.

The browser capture endpoint is **administrator initiated**, not an autonomous browser worker. It records
screenshots for authorized, allowlisted sources, but does not discover competition links or extract fixtures.
Screenshot capture is not vision verification. Do not treat controller activity or API fixture acquisition as
evidence that browser navigation, vision interpretation or prediction succeeded.
Completed manual navigations record their HTTP status, page title, duration and screenshot hash in the capture
audit event. Non-2xx responses and missing navigation responses are failures, even when a screenshot was saved;
failed captures cannot be sent for vision interpretation. Navigation errors before a screenshot is available
are recorded as failures without a screenshot.

The table below describes the historical OpenLigaDB/Football-Data pipeline; it is not a claim that the full
pipeline is currently operating. Football-Data.co.uk is prohibited for this autonomous application without
written consent. With durable fixture discovery enabled, the older OpenLigaDB collector is not run by the
controller. Durable discovery now derives a provisional Bundesliga table from its existing OpenLigaDB season
response, without additional provider requests. It rejects malformed final scores and duplicate fixtures, and
does not publish a ranking when no completed matches are available. The table is not an official or independently
verified standings snapshot, does not cover basketball or every competition, and shows a warning after 24 hours.
The general controller's online status does not establish that a standings source exists for a selected league.

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

The configured development fallback is OpenLigaDB and TheSportsDB, subject to their respective terms and coverage.
These structured APIs supplement rather than implement or replace the missing autonomous browser workflow.
