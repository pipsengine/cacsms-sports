# Cacsms Sport AI 2.3 — Durable Authorized Acquisition

## Implemented
- PostgreSQL acquisition job queue with idempotent enqueue keys, bounded retry, leases, audit and incidents.
- Celery worker and 30-second recovery scheduler.
- Authorized source and fixture validation; configured source/section feed endpoints only.
- HTTPS-only JSON research feeds with public-host validation, disabled redirects/proxies, bounded response size, fixture/section matching.
- Evidence persisted through the existing observation ingestion service.
- Administrator-only job enqueue endpoint; read-only job status endpoints.

## Configuration
Set `SPORTS_SOURCE_FEEDS_JSON` to a JSON object mapping authorized provider IDs to research section URLs. The feed must return a JSON object containing `fixture_id` and `section` matching the job. The provider must already exist, be enabled, and have permission `AUTHORIZED`. This connector is for expressly permitted data feeds, not arbitrary website scraping.

POST /api/v1/sports/admin/acquisition/jobs with administrator token and `source_id`, `fixture_id`, `section`, `period_key`. The scheduler dispatches jobs every 30 seconds.

## Not implemented / not verified
- No public sports feed is preconfigured; there is no real sports research until the operator configures an authorized provider.
- No computer vision, predictions, bookmaker code generation, paid wagers or deployed website.
- Worker process, PostgreSQL and frontend Docker startup require verification on a Docker-capable host.
- Production deployments require egress firewall/DNS pinning, secret management, RBAC and stronger authorization than the current admin-token development control.
