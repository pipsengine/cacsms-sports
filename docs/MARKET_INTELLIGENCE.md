# Market Intelligence (cacsms-market-intelligence patch, integrated)

Source: `CACSMS_Market_Intelligence_Autonomous` (standalone FastAPI + SQLite app with its own market, fixture, odds and source tables).
Its ideas are integrated onto canonical records instead of a second database:

| Patch | Integrated as |
|---|---|
| Football-Data historical CSV importer (7 divisions, 6 seasons, opening prices stamped at midnight) | `app/modules/markets/history_import.py`: **closing** prices only, stamped at kickoff (UK local time → UTC); Bet365, Pinnacle, Betfair Exchange and the market average for 1X2, O/U 2.5 and Asian handicap; one file-level observation per CSV as evidence; idempotent per match; no per-record pipeline events |
| `ms` market registry / categories | existing catalogue (433 definitions) |
| sources incl. disabled BetExplorer / SportyBet | source registry (`BetExplorer` PROHIBITED by its terms; `SportyBet` NO_PERMITTED_FEED) |
| daily scheduler | existing autonomy cycle (`market-archive` every 2 min until backfilled; current season refreshed every 12 h) |
| overview / coverage / sync history | `app/modules/markets/intelligence.py`, `GET /api/v1/sports/market-intelligence/{overview,categories,markets,sports-coverage,sync-history,sources}`; `POST /sync` (admin token) |

Non-Bundesliga fixtures come from one provider only, so they are **price archives**: no results are verified from them and no
pipeline runs are created for them. Bundesliga archive prices attach to the existing OpenLigaDB fixtures and are never used to
create fixtures.

## Live result (16 Nov 2026)
35 season files, 10,236 fixtures, **238,664 closing prices**, 9 invalid prices rejected. Model coverage of observed outcomes 5.1%
(1X2 covered; O/U 2.5 and Asian handicap lines have no approved model). **Model vs closing market** on the market model's
378-match Bundesliga holdout: closing market Brier 0.565 vs model 0.597 (average margin 6.3%) - the closing market is sharper,
which is why qualification stays gated on positive lower-bound value with fresh prices.

Migration `0015` adds indexes on `markets.odds_snapshots` (fixture/time, market/outcome, bookmaker/market) and `odds_evidence`.
Tests: `apps/api/tests/test_market_archive_intelligence.py`.
