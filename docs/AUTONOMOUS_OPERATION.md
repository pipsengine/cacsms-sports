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

The durable discovery queue also requests TheSportsDB's documented `eventslast` endpoint for provider-mapped
participants in upcoming fixtures. It stores valid prior final scores as single-source, partial observations
visible under Deep Match Research → Form. The free tier documents a limit of one home event per team, so these
records do not establish last-5/10/20 form or full history. Empty, invalid and unavailable responses are not
fabricated. They do not satisfy research corroboration, verify fixture identity, or enable predictions. The
same provider rate budget, retry and permission controls used by fixture discovery apply to these requests.
This is not a guarantee of data for every sport, fixture or time.
The research stage can compile a `PARTIAL` dossier referencing the latest eligible fixture-linked observations;
this is not a completed or verified research stage and does not unlock analysis or predictions. The workspace
distinguishes recorded evidence from dossier links and provisional league-table context. Verified coverage uses
the seven pre-match dossier sections, not post-match results. Form observations are marked stale when their latest
underlying result is more than 30 days old; an observation's capture time is not the event date, and a recent
result does not establish a complete form window. Revoked sources cannot support verified workspace sections.
Fixtures & Competitions indicates when authorized, pre-kickoff partial form evidence is available for either
participant. The pipeline may still show `WAITING_FOR_DATA`: partial single-source observations do not meet
the independent research verification requirement. Absent odds and forecasts remain unavailable.

For provider-mapped upcoming fixtures in any supported sport or country, the queue also checks TheSportsDB's
documented `eventsseason` endpoint once per league and season per day. Only final, pre-capture events with
matching league, season, sport and participant IDs are attached as partial single-source Form evidence.
The free tier returns at most 15 events for the whole season, and these may be the oldest rather than the
latest matches. The returned list is not a complete or necessarily recent last-5/10/20 form window; empty
responses and unmatched participants provide no evidence. The development-key and shared rate limits apply.

For the German `bl1`, `bl2` and `bl3` feeds, the existing season refresh also records up to 20
prior finished league matches per mapped upcoming participant as partial, single-source Form evidence.
It matches provider team IDs, checks final scores and competition identity, and excludes results at or
after capture. It covers only the available league season, not other competitions or guaranteed complete
5/10/20-match windows. It does not create verified research, results or predictions.

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
controller. Durable discovery derives provisional Bundesliga, 2. Bundesliga and 3. Liga tables from their existing
OpenLigaDB season responses, without additional provider requests. It rejects malformed final scores and duplicate
fixtures, and does not publish a ranking when no completed matches are available. These are not official or
independently verified standings snapshots, do not cover basketball or every competition, and show a warning after
24 hours. These tables are computed from available community results; their latest included result is shown and
neither a complete season feed nor current results can be guaranteed.
OpenLigaDB `pl` and `la1` table captures from the November 18, 2026 investigation are quarantined:
the `la1` feed contained Dutch clubs and the `pl` table disagreed with TheSportsDB. These captures remain in
the database for audit but cannot be displayed as standings. Related `pl` and `la1` 2026 fixture mappings are
also quarantined pending review: no further jobs for those feed seasons are dispatched, and affected fixtures
are excluded from the Fixtures & Competitions list and fixture identity verification, even if another provider
also mapped them. Records remain in the database for audit. This does not remove previously created records or
guarantee that every other screen excludes them; do not rely on affected records downstream. Fixture identities
in the community feeds are not proof that competition membership or scores are correct.
The general controller's online status does not establish that a standings source exists for a selected league.

For discovered football competitions with a mapped provider season, the queue also requests TheSportsDB's
documented `lookuptable` endpoint once per day. Its free tier returns at most five rows for featured soccer
leagues; returned rows are shown as a partial, single-source overall table, never as a complete or verified
table. Home and away splits and match-based analytics cannot be inferred from these rows. Unsupported or empty
responses remain unavailable. Captured and provider update times are distinct, and old data is flagged. The
development-key restriction, source permissions and shared rate budget remain in force.

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

## SportyBet: automated collection not authorized (checked 2026-11-19)

SportyBet's Nigerian [intellectual property terms](https://www.sportybet.com/ng/m/help/about/terms-and-conditions/our-intellectual-property-rights)
restrict copying or storing website content without prior written consent, with an exception for use required to place bets;
they also prohibit commercial use of the website or its content. A robots.txt allowance is not permission to collect or reuse content.
No authorized SportyBet fixture or odds feed is configured in this application. A locally created authorization record in another
application is not evidence of SportyBet's consent. Do not enable automated collection or import its content until the intended
collection, storage and use are covered by documented permission.

`acquisition/sportybet_snapshot.py` is an offline parser for the previous application's snapshot shape; it does not fetch,
schedule, store or authorize anything. It produces unverified fixture candidates and only unambiguous active football 1X2
prices, with explicit rejection reasons. Tests use synthetic data and the existing observation and odds gates in an isolated
database. Fixture identity reconciliation, a permitted acquisition worker, other markets and live provider validation are
not implemented; this parser does not populate the production fixture page.

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

## League-window corroboration (football-data.org, API-Football, paid TheSportsDB, optional BetExplorer)

Any two enabled providers whose computations are identical verify a section; a disagreeing third provider is named
in the readiness note and emits nothing. If only one provider has usable data, its sections are stored as
`SINGLE_SOURCE` provisional evidence and the research stage ends with `INSUFFICIENT_DATA`; analysis and predictions
still require a verified dossier. If a second provider later agrees, the evidence is promoted to cross-source
corroboration. **football-data.org** registers when `SPORTS_FOOTBALL_DATA_ORG_KEY` is set
(free tier: PL, ELC, PD, SA, FL1, DED, PPL, BSA; requests spaced 7 s). **TheSportsDB** takes part only with a paid
`SPORTS_THESPORTSDB_KEY`; the public key truncates seasons and is never used, and the key never appears in stored URLs.
Competition names with a season suffix (e.g. "Premier League 2026/2027") map to their league.

`app/modules/autonomy/window_corroboration.py` verifies `recent_form`, `match_statistics` and `head_to_head` for
mapped leagues (Belgian Pro League, Premier League, Championship, La Liga, Serie A, Ligue 1, Eredivisie, Scottish
Premiership, Greek Super League, Allsvenskan, Eliteserien, Brazilian Serie A; extend with
`SPORTS_CORROBORATION_LEAGUES_JSON`). Each provider's complete current and previous league-season results are cached;
each provider computes the sections independently, and observations are emitted for both (independence groups
`api-football` and `betexplorer`) only when the computations are identical. A lagging provider, a score disagreement
or an unresolved team name yields no evidence; the per-fixture outcome appears in the research readiness message.

- **API-Football** registers as AUTHORIZED when `SPORTS_APIFOOTBALL_KEY` is set (two requests per league, refreshed
  every 6 h for the current season and 7 d for the previous). Plan errors are recorded, never treated as empty data.
- **BetExplorer** remains PROHIBITED and every request is refused unless `SPORTS_SOURCE_CONSENT=betexplorer.com=<ref>`
  is recorded. Its absence is informational: permitted providers continue independently, with single-source
  evidence kept provisional rather than blocked or treated as verified. With consent it is authorized with an
  audit event carrying the reference, fetches only league
  `/results/` pages, checks robots.txt, spaces requests by 30 s and refreshes each page at most every 6 h. Removing
  the consent downgrades it to PROHIBITED on the next cycle. The HTML parser is tested against representative markup;
  validate it against the live page once consent exists.
- **Corroborated history.** Finished matches on which both providers agree (team identity, date within a day, score)
  are recorded as `official_result` evidence and versioned Results, mapped onto stored team names where unambiguous.
  This is the per-league history the market model is validated on; disagreements record nothing.

## Per-competition model scope

A model forecasts only competitions it was validated on (`validation.competition_ids`, checked in
`prediction/prospective.eligible`). Models created before this field existed were trained solely on the Bundesliga
and are scoped to it. `autonomy/modelling.train_market_model_if_due` validates a separate Poisson/direct market model
for every football competition with at least 300 corroborated results; retraining retires only the model of the same
competition.

## Competition countries

Competitions without a provider country (mostly OpenLigaDB community feeds) get one only from unambiguous name rules
(`autonomy/competition_country.py`, e.g. UEFA → Europe, Regionalliga → Germany, ÖBL → Austria), with an audit event per
change; test and unidentifiable feeds stay unspecified. The qualification filters list every country and competition
with upcoming fixtures, with fixture and forecast counts, and explain empty selections.
