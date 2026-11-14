# CACSMS Sport AI 3.1 — Browser evidence, governance and operational frontend

## Delivered
- Authorized browser screenshot capture with explicit hostname allowlist, HTTPS-only restriction, DNS/public-IP checks and redirect/subresource request restrictions. Browser capture is an administrator action and cannot submit wagers.
- Immutable screenshot hash and evidence file, with database capture session, audit record, and explicit `AWAITING_VERIFIED_INTERPRETATION` state.
- Vision extraction contract refuses unverified model outputs. **No computer-vision model/provider is connected in this release**. Screenshot capture does not equal computer vision.
- Scheduled prospective model governance with versioned snapshots, fail-closed insufficient-sample status, degradation incidents and zero automatic model activation.
- Dedicated Browser Operator, Model Intelligence and Diagnostics frontends, consuming read-only APIs.
- Alembic migration 0006, new tests, GitHub CI retained.

## Limitations
- Playwright requires installed Chromium (`python -m playwright install chromium`), allowed outbound HTTPS and an explicit `SPORTS_BROWSER_ALLOWED_HOSTS` setting. Source onboarding and authorization remain administrator-controlled.
- Do not configure an allowlist for sites whose terms prohibit automated access. The browser module intentionally does not scrape SportyBet, authenticate, create codes or place bets.
- External vision inference, verified extraction, automatic research dossier creation, comprehensive end-to-end browser integration and full model training remain incomplete.
- Governance snapshots do not change production model status. PAPER-only remains mandatory.
- PostgreSQL, full Docker stack and frontend production build must be tested in a deployment environment; they are not certified by unit tests.

## Config
`SPORTS_BROWSER_ALLOWED_HOSTS=approved.example.org` (no default), `SPORTS_EVIDENCE_ROOT=/var/lib/cacsms/evidence`, `SPORTS_ADMIN_TOKEN` (required for capture).

## APIs
`GET /api/v1/sports/browser/summary`, `GET /api/v1/sports/browser/sessions`, `POST /api/v1/sports/admin/browser/capture`, `GET /api/v1/sports/governance/summary`, `GET /api/v1/sports/governance/evaluations`.
