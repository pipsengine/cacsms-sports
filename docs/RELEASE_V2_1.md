# V2.1 — Evidence and Mission Control

Added evidence-bound, versioned research dossiers for seven sections, verified authorized observation references, cross-fixture rejection, auditable paper-only mission creation and state transitions, research readiness API, and PostgreSQL-backed Command Centre panels.

Admin endpoints (require SPORTS_ADMIN_TOKEN): POST /api/v1/sports/admin/research/dossiers; POST /api/v1/sports/admin/missions; POST /api/v1/sports/admin/missions/{mission_id}/transition.

Read-only endpoint: GET /api/v1/sports/research/readiness.

Not implemented: autonomous source collection, computer vision, trained prediction models, bookmaker market mapping, booking-code integration, automated worker execution, deployed site. No paid-wager pathway exists.
