# CACSMS SPORTS v4.4 — Figma-quality UI foundation and Dashboard redesign

## Source review
Reviewed `apps/web/src/App.tsx`, `navigation.ts`, `style.css`, and the seven dedicated workspace components against the approved dashboard reference. All 29 sidebar destinations remain registered, in eight groups. No previous backend modules, database migrations, or frontend files are removed.

## Implemented
- A new responsive executive Dashboard with six compact color-coded KPI cards, operational connection indicator, auto-refresh toggle (60s), manual refresh, API error feedback, engine readiness, system health, horizontal 12-stage workflow, programme status, qualified opportunity list, and upcoming fixtures.
- The 12-stage overview reads the persisted pipeline API and does not mark stages completed without evidence.
- Shared design tokens, refined navigation, table, cards, tabs, modals, typography, shadows, and responsive styles across the existing 29 page routes.
- Source records and missing/failed API states are never replaced with example values from the Figma reference.

## Limitations and validation
- This is a frontend redesign pass, not a reimplementation of all 29 pages' business logic. Existing specialized workspaces remain, and some have not been individually reauthored.
- A full `npm run build` was attempted but dependency installation did not complete within the available runtime. A subsequent global TypeScript check failed to resolve React and Lucide packages because `node_modules` is absent. Production frontend compilation is therefore **not verified**.
- Docker, PostgreSQL, real browser visual QA, and external data feeds are not verified in this environment.
- Backend remains PAPER-only. No real wager submission.

## Run locally
```
cd apps/web
npm install
npm run build
npm run dev
```
Start the API and PostgreSQL using the repository's Docker Compose instructions and configure the frontend API proxy. Use browser DevTools to check requests to `/api/v1/sports/dashboard/summary` and `/api/v1/sports/pipeline/runs`.

## Next acceptance gates
1. Successful npm install and production build.
2. Automated screenshot comparisons at 390, 768, 1366, and 1920 px.
3. Verify every route and the empty/error/loading states against live API fixtures.
4. Individually redesign remaining workspace content and modal actions where backend contracts support them.
