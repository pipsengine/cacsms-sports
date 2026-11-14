# CACSMS SPORTS v4.5 — Dashboard code

Editable React/TypeScript and CSS: `apps/web/src/FigmaDashboard.tsx`, `FigmaDashboard.css`. Wired to `/sports/dashboard` in `App.tsx`.

Six KPIs, readiness, system health, evidence-gated pipeline, programme allocation, sport distribution, odds bands, model records, opportunities and fixtures. All figures from API; unavailable data is displayed as unavailable.

Endpoints: `/api/v1/sports/dashboard/summary`, `pipeline/runs`, `programmes`, `opportunities`, `fixtures`, `models`.

Period selector is not wired to date-scoped API: interface explicitly discloses this. Workers and models are not declared ready without independent verification. PAPER mode retained.

Build: `cd apps/web && npm install && npm run build`. This is source code, not a native .fig file.
