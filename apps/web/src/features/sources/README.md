# Source Intelligence

Autonomous discovery, authorization, collection and sync of authorized sources.

Data sources: `GET /api/v1/sports/sources/overview`, `/sources/registry`, `/sources/analytics`, `/sources/health`, `/acquisition/jobs`.

Operational metrics: Active sources, queued/completed acquisition jobs, healthy / degraded / prohibited counts, auto-discovered sports/countries/competitions, sync schedule, verified observations.

The page is read-only and self-updating via the live feed / autonomous controller. Manual catalogue filters are optional inspection only and do not start acquisition. PAPER mode; prohibited hosts remain disabled unless express written consent is recorded.
