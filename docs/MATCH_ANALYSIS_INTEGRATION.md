# Match Analysis (v3.6 patch, integrated)

Source: `CACSMS_Sports_AI_v3_6_REDOWNLOAD` (full v3.5-based snapshot). Only the Match Analysis feature was taken;
the rest of that snapshot predates current work (e.g. its `0008_league_intelligence` migration conflicts) and was not copied.

## Files
- `apps/api/app/modules/match_analysis/service.py`, `routes.py`: adapted from the patch; builds on the Deep Match Research workspace.
- `apps/web/src/MatchAnalysis.tsx`, `MatchAnalysis.css`: Figma-style page at `/sports/match-analysis` (shares `.dmr` styles).
- Tests: `apps/api/tests/test_match_analysis.py`, UI: `scripts/verify_match_analysis_ui.py` (mocked responses).

## API
- `GET /api/v1/sports/match-analysis/summary`
- `GET /api/v1/sports/match-analysis/fixtures/{fixture_id}?as_of=` (404 unknown fixture, 422 invalid cutoff)

## Data rules (nothing simulated)
| UI element | Source |
|---|---|
| Win/Draw probabilities | latest `1X2` forecasts from an `ACTIVE` model, predicted before cutoff |
| Expected goals, xG/xGA, Feature Comparison | feature snapshot (top-level or `metrics` key, `{home, away, unit?, evidence_ids?}`) linked to a `VERIFIED` dossier; every cited evidence id must be authorized and pre-cutoff |
| Goals per match / conceded / clean sheets | verified results before cutoff (marked "Computed") unless the snapshot supplies them |
| Analysis Summary | `VERIFIED` research sections or snapshot metrics; `COMPUTED` = derived from verified results only |
| Research Evidence counts | authorized observations by section; External Sources = authorized providers |

Currently the prospective model writes only `1X2/HOME`; Draw and Away show "—" until a model publishes them.
