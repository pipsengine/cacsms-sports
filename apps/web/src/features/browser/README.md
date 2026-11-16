# Browser & Vision Operator

Autonomous authorized browsing, screenshot evidence and computer-vision readiness.

Data sources: `GET /api/v1/sports/browser/overview`, `/browser/sessions`, `/browser/summary`, `/browser/readiness`.

Operational metrics: Browser sessions, captured evidence, vision-verified, in progress, failed, authorized / prohibited sources, system health.

Capture is gated by hostname allowlist and explicit source authorization. Screenshots are not vision-verified research until independent review. Prohibited hosts (e.g. BetExplorer without written consent) remain blocked. PAPER mode.
