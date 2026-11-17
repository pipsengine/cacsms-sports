# API inventory

| Method | Route | Summary |
|---|---|---|
| GET | `/api/v1/sports/operations/telemetry` | Operational Telemetry |
| GET | `/api/v1/sports/diagnostics/overview` | Overview |
| GET | `/health` | Health |
| GET | `/api/v1/sports/dashboard/summary` | Summary |
| GET | `/api/v1/sports/programmes` | Programmes |
| GET | `/api/v1/sports/programmes/{key}/runs` | Programme Runs |
| GET | `/api/v1/sports/fixtures/{id}` | Fixture Detail |
| GET | `/api/v1/sports/fixtures/{id}/research` | Fixture Research |
| GET | `/api/v1/sports/fixtures/{id}/predictions` | Fixture Predictions |
| GET | `/api/v1/sports/fixtures/{id}/markets` | Fixture Markets |
| GET | `/api/v1/sports/fixtures/{id}/statistics` | Fixture Statistics |
| GET | `/api/v1/sports/predictions/{id}` | Prediction Detail |
| GET | `/api/v1/sports/research/evidence/{id}` | Research Evidence |
| GET | `/api/v1/sports/tickets/{id}` | Ticket Detail |
| GET | `/api/v1/sports/booking-codes/{id}` | Code Detail |
| GET | `/api/v1/sports/models/{id}/evaluations` | Model Evaluations |
| GET | `/api/v1/sports/sources/overview` | Source Overview |
| GET | `/api/v1/sports/sources/analytics` | Source Analytics |
| GET | `/api/v1/sports/sources/health` | Source Health |
| GET | `/api/v1/sports/sources/registry` | Source Registry |
| GET | `/api/v1/sports/missions/{id}` | Mission Detail |
| GET | `/api/v1/sports/operations/events` | Operation Events |
| GET | `/api/v1/sports/diagnostics` | Diagnostics |
| POST | `/api/v1/sports/admin/sources` | Onboard Source |
| POST | `/api/v1/sports/admin/fixtures/ingest` | Fixture Ingest |
| GET | `/api/v1/sports/workflow/stages` | Workflow Stages |
| POST | `/api/v1/sports/qualification/evaluate` | Qualification Preview |
| POST | `/api/v1/sports/admin/research/dossiers` | Research Dossier Ingest |
| POST | `/api/v1/sports/admin/missions` | Mission Create |
| POST | `/api/v1/sports/admin/missions/{mission_id}/transition` | Mission Transition |
| GET | `/api/v1/sports/research/readiness` | Research Readiness |
| POST | `/api/v1/sports/admin/research/observations` | Observation Intake |
| POST | `/api/v1/sports/admin/features/materialize` | Feature Materialize |
| GET | `/api/v1/sports/fixtures/{id}/observations` | Fixture Observations |
| GET | `/api/v1/sports/research/{id}/features` | Research Features |
| GET | `/api/v1/sports/research/evidence-coverage` | Evidence Coverage |
| POST | `/api/v1/sports/admin/acquisition/jobs` | Create Acquisition Job |
| GET | `/api/v1/sports/acquisition/jobs` | Acquisition Jobs |
| GET | `/api/v1/sports/acquisition/jobs/{job_id}` | Acquisition Job Detail |
| POST | `/api/v1/sports/admin/models/challengers` | Train Challenger |
| GET | `/api/v1/sports/models/{id}/validation` | Model Validation |
| GET | `/api/v1/sports/models/feature-contract` | Model Feature Contract |
| GET | `/api/v1/sports/models/{model_id}/preview/{feature_id}` | Model Prediction Preview |
| POST | `/api/v1/sports/admin/markets/odds` | Ingest Market Odds |
| POST | `/api/v1/sports/admin/qualification/decisions` | Create Qualification |
| GET | `/api/v1/sports/markets/summary` | Market Summary |
| POST | `/api/v1/sports/admin/programmes/{key}/run` | Run Paper Strategy |
| POST | `/api/v1/sports/admin/tickets/prepare` | Prepare |
| GET | `/api/v1/sports/tickets/{ticket_id}/detail` | Detail |
| GET | `/api/v1/sports/betslips` | Betslips |
| GET | `/api/v1/sports/booking-codes/readiness` | Booking Readiness |
| GET | `/api/v1/sports/performance/workspace` | Performance Workspace |
| GET | `/api/v1/sports/results/workspace` | Results Workspace |
| POST | `/api/v1/sports/admin/results/official` | Ingest Official Result |
| GET | `/api/v1/sports/results/verified` | Verified Results |
| GET | `/api/v1/sports/settlements/latest` | Latest Settlements |
| GET | `/api/v1/sports/performance/forecast-quality` | Forecast Quality |
| GET | `/api/v1/sports/results/automation/status` | Results Automation Status |
| POST | `/api/v1/sports/admin/results/reconcile-pending` | Reconcile Results Now |
| GET | `/api/v1/sports/models/monitoring/summary` | Monitoring Summary |
| GET | `/api/v1/sports/models/{model_id}/monitoring` | Monitoring |
| GET | `/api/v1/sports/browser/overview` | Browser Overview |
| GET | `/api/v1/sports/browser/sessions` | Browser Sessions |
| GET | `/api/v1/sports/browser/summary` | Browser Summary |
| POST | `/api/v1/sports/admin/browser/capture` | Capture Admin |
| GET | `/api/v1/sports/browser/readiness` | Browser Readiness |
| POST | `/api/v1/sports/admin/browser/{capture_id}/infer` | Infer Admin |
| GET | `/api/v1/sports/governance/reconciliation-review` | Reconciliation Review |
| GET | `/api/v1/sports/models/workspace` | Models Workspace |
| POST | `/api/v1/sports/models/{model_id}/promote` | Promote |
| GET | `/api/v1/sports/governance/summary` | Governance Summary |
| GET | `/api/v1/sports/governance/evaluations` | Governance Evaluations |
| GET | `/api/v1/sports/pipeline/definitions` | Definitions |
| GET | `/api/v1/sports/pipeline/runs` | Runs |
| POST | `/api/v1/sports/pipeline/runs` | Create Run |
| GET | `/api/v1/sports/pipeline/runs/{run_id}` | Run Detail |
| GET | `/api/v1/sports/pipeline/runs/{run_id}/history` | Run History |
| POST | `/api/v1/sports/pipeline/runs/{run_id}/execute` | Execute |
| POST | `/api/v1/sports/pipeline/runs/{run_id}/drive` | Drive |
| GET | `/api/v1/sports/pipeline/fixtures/{fixture_id}/market-monitor` | Market Monitor |
| GET | `/api/v1/sports/pipeline/events` | Events |
| GET | `/api/v1/sports/pipeline/contracts` | Workspace Contracts |
| GET | `/api/v1/sports/pipeline/runs/{run_id}/evidence` | Stage Evidence |
| GET | `/api/v1/sports/live/version` | Version |
| GET | `/api/v1/sports/live/stream` | Stream |
| GET | `/api/v1/sports/readiness` | Readiness |
| GET | `/api/v1/sports/competitions` | Competitions |
| GET | `/api/v1/sports/competitions/{competition_id}/top-two/research` | Top Two |
| GET | `/api/v1/sports/research/catalog/sports` | Sports |
| GET | `/api/v1/sports/research/catalog/countries` | Countries |
| GET | `/api/v1/sports/research/catalog/leagues` | Leagues |
| GET | `/api/v1/sports/research/catalog/seasons` | Seasons |
| GET | `/api/v1/sports/research/catalog/fixtures` | Fixtures |
| GET | `/api/v1/sports/research/catalog/standings` | Standings |
| GET | `/api/v1/sports/research/catalog/dossiers/{fixture_id}` | Dossier |
| POST | `/api/v1/sports/admin/research/seasons` | Save Season |
| POST | `/api/v1/sports/admin/research/seasons/{season_id}/fixtures` | Assign Season |
| POST | `/api/v1/sports/admin/research/standings` | Ingest Standings |
| GET | `/api/v1/sports/research/catalog/coverage` | Standings Coverage |
| GET | `/api/v1/sports/research/catalog/standings/history` | Standings History |
| GET | `/api/v1/sports/dashboard/autonomous` | Autonomous Dashboard |
| GET | `/api/v1/sports/autonomy/status` | Status |
| GET | `/api/v1/sports/pipeline/context` | Context |
| GET | `/api/v1/sports/fixture-intelligence/overview` | Fixture Overview |
| POST | `/api/v1/sports/standings/admin/competitions` | Register |
| POST | `/api/v1/sports/standings/admin/sync/{competition_id}` | Sync |
| GET | `/api/v1/sports/standings/sports` | Sports |
| GET | `/api/v1/sports/standings/countries` | Countries |
| GET | `/api/v1/sports/standings/competitions` | Competitions |
| GET | `/api/v1/sports/standings/seasons` | Seasons |
| GET | `/api/v1/sports/standings/table` | Table |
| GET | `/api/v1/sports/standings/top-two` | Top Two |
| GET | `/api/v1/sports/standings/analytics` | Analytics |
| GET | `/api/v1/sports/standings/history` | History |
| GET | `/api/v1/sports/standings/health` | Health |
| GET | `/api/v1/sports/research/workspace/{fixture_id}` | Workspace |
| GET | `/api/v1/sports/match-analysis/summary` | Get Summary |
| GET | `/api/v1/sports/match-analysis/fixtures/{fixture_id}` | Get Fixture Analysis |
| GET | `/api/v1/sports/market-scanner/catalog` | Get Catalog |
| GET | `/api/v1/sports/market-scanner/fixtures/{fixture_id}` | Get Fixture |
| GET | `/api/v1/sports/markets/catalogue` | Get Catalogue |
| GET | `/api/v1/sports/markets/categories` | Get Categories |
| GET | `/api/v1/sports/markets/sports/{sport_id}` | Get Sport |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}` | Get Fixture |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}/availability` | Get Availability |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}/odds` | Get Odds |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}/coverage` | Get Coverage |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}/evaluations` | Get Evaluations |
| GET | `/api/v1/sports/markets/fixtures/{fixture_id}/best-fit` | Get Best Fit |
| GET | `/api/v1/sports/markets/sources/health` | Get Sources Health |
| GET | `/api/v1/sports/markets/scans` | List Scans |
| POST | `/api/v1/sports/markets/scans` | Post Scan |
| GET | `/api/v1/sports/markets/scans/{scan_id}` | Get Scan |
| POST | `/api/v1/sports/markets/sync` | Post Sync |
| GET | `/api/v1/sports/market-intelligence/overview` | Get Overview |
| GET | `/api/v1/sports/market-intelligence/categories` | Get Categories |
| GET | `/api/v1/sports/market-intelligence/markets` | Get Markets |
| GET | `/api/v1/sports/market-intelligence/sports-coverage` | Get Sports Coverage |
| GET | `/api/v1/sports/market-intelligence/sync-history` | Get Sync History |
| GET | `/api/v1/sports/market-intelligence/sources` | Get Sources |
| POST | `/api/v1/sports/market-intelligence/sync` | Post Sync |
| GET | `/api/v1/sports/qualification/summary` | Get Summary |
| GET | `/api/v1/sports/qualification/decision-details` | Get Decisions |
| GET | `/api/v1/sports/qualification/rejections` | Get Rejections |
| GET | `/api/v1/sports/qualification/gates` | Get Gates |
| GET | `/api/v1/sports/qualification/history` | Get History |
| GET | `/api/v1/sports/qualification/comparison` | Get Comparison |
| GET | `/api/v1/sports/qualification/filters` | Get Filters |
| GET | `/api/v1/sports/qualification/opportunities` | Get Opportunities |
| GET | `/api/v1/sports/qualification/opportunities/{opportunity_id}/evidence` | Get Opportunity Evidence |
| GET | `/api/v1/sports/programmes/accumulator/overview` | Get Overview |
| GET | `/api/v1/sports/programmes/accumulator/configuration` | Get Configuration |
| GET | `/api/v1/sports/programmes/accumulator/candidates` | Get Candidates |
| GET | `/api/v1/sports/programmes/accumulator/run-history` | Get Runs |
| GET | `/api/v1/sports/programmes/accumulator/validation` | Get Validation |
| GET | `/api/v1/sports/programmes/accumulator/analytics` | Get Analytics |
| GET | `/api/v1/sports/programmes/singles/overview` | Get Overview |
| GET | `/api/v1/sports/programmes/singles/configuration` | Get Configuration |
| GET | `/api/v1/sports/programmes/singles/candidates` | Get Candidates |
| GET | `/api/v1/sports/programmes/singles/run-history` | Get Runs |
| GET | `/api/v1/sports/programmes/singles/tickets` | Get Tickets |
| GET | `/api/v1/sports/programmes/singles/validation` | Get Validation |
| GET | `/api/v1/sports/programmes/singles/analytics` | Get Analytics |
| GET | `/api/v1/sports/programmes/singles/health` | Get Health |
| GET | `/api/v1/sports/programmes/jackpot/overview` | Get Overview |
| GET | `/api/v1/sports/programmes/jackpot/configuration` | Get Configuration |
| GET | `/api/v1/sports/programmes/jackpot/candidates` | Get Candidates |
| GET | `/api/v1/sports/programmes/jackpot/run-history` | Get Runs |
| GET | `/api/v1/sports/programmes/jackpot/tickets` | Get Tickets |
| GET | `/api/v1/sports/programmes/jackpot/validation` | Get Validation |
| GET | `/api/v1/sports/programmes/jackpot/analytics` | Get Analytics |
| GET | `/api/v1/sports/programmes/jackpot/health` | Get Health |
| GET | `/api/v1/sports/programmes/draws/overview` | Get Overview |
| GET | `/api/v1/sports/programmes/draws/configuration` | Get Configuration |
| GET | `/api/v1/sports/programmes/draws/candidates` | Get Candidates |
| GET | `/api/v1/sports/programmes/draws/run-history` | Get Runs |
| GET | `/api/v1/sports/programmes/draws/tickets` | Get Tickets |
| GET | `/api/v1/sports/programmes/draws/validation` | Get Validation |
| GET | `/api/v1/sports/programmes/draws/analytics` | Get Analytics |
| GET | `/api/v1/sports/programmes/draws/health` | Get Health |
| GET | `/api/v1/sports/programmes/rollover/overview` | Get Overview |
| GET | `/api/v1/sports/programmes/rollover/configuration` | Get Configuration |
| GET | `/api/v1/sports/programmes/rollover/candidates` | Get Candidates |
| GET | `/api/v1/sports/programmes/rollover/run-history` | Get Runs |
| GET | `/api/v1/sports/programmes/rollover/tickets` | Get Tickets |
| GET | `/api/v1/sports/programmes/rollover/validation` | Get Validation |
| GET | `/api/v1/sports/programmes/rollover/analytics` | Get Analytics |
| GET | `/api/v1/sports/programmes/rollover/health` | Get Health |
| GET | `/api/v1/sports/programmes/rollover/plan` | Get Plan |
| GET | `/api/v1/sports/tickets/builder/overview` | Get Overview |
| GET | `/api/v1/sports/tickets/builder/register` | Get Register |
| GET | `/api/v1/sports/tickets/builder/programmes` | Get Programmes |
| GET | `/api/v1/sports/betslip-preparation/overview` | Get Overview |
| GET | `/api/v1/sports/betslip-preparation/{slip_id}` | Detail |
| GET | `/api/v1/sports/booking-workspace/overview` | Get Overview |
| GET | `/api/v1/sports/booking-workspace/tickets/{ticket_id}` | Detail |
| PUT | `/api/v1/sports/odds-intelligence/sources/{source_id}/profile` | Configure Source |
| GET | `/api/v1/sports/odds-intelligence/observations` | Observations |
| GET | `/api/v1/sports/odds-intelligence/eligibility/{odds_id}` | Eligibility |
| GET | `/api/v1/sports/odds-intelligence/sources` | Sources |
| GET | `/api/v1/sports/odds-intelligence/source-readiness` | Source Readiness |
| GET | `/api/v1/sports/odds-intelligence/quality-assessments` | Quality Assessments |
| GET | `/api/v1/sports/{resource}` | List Resource |
