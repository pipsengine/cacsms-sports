# Release 3.2 — vision integration and deployment validation tools

## Implemented
- Optional real OpenAI-compatible multimodal HTTP inference against an explicitly configured HTTPS endpoint and approved public host. A live provider is not bundled; credentials are required.
- Screenshot SHA-256 verification, fixture/source identity validation, bounded structured extraction and mandatory visible-text provenance.
- Inference output is **EXTRACTED_UNVERIFIED**. It is never treated as verified research or a prediction automatically.
- Independent-review service for turning specifically reviewed observations into versioned research dossiers. This requires a separate trusted reviewer/workflow; no unverified automated approval is provided.
- Browser readiness API and live frontend readiness panel.
- API smoke script, release source checker and unit tests.

## Still NOT verified or complete
- No external vision credentials were supplied, therefore real provider calls were not exercised.
- No authorized sports research feed is configured, therefore autonomous end-to-end fixture-to-prediction execution is not demonstrated.
- No approved production model is bundled; the inference pipeline cannot manufacture calibrated predictions.
- Docker is unavailable in the build environment. Full PostgreSQL, browser and frontend runtime deployment must be tested on a Docker-capable host.
- Site is NOT publicly deployed and no GitHub remote has been configured.
- PAPER-only. No paid wager submission.

## Local deployment on a Docker host
1. Copy `.env.example` to `.env`; configure a strong POSTGRES_PASSWORD and SPORTS_ADMIN_TOKEN.
2. Configure SPORTS_BROWSER_ALLOWED_HOSTS to domains you are authorized to access.
3. Optionally configure SPORTS_VISION_ENDPOINT, SPORTS_VISION_ALLOWED_HOSTS, SPORTS_VISION_MODEL and SPORTS_VISION_API_KEY. Provider must support chat-completions with image_url and JSON response.
4. Run `docker compose up --build -d`.
5. Run `docker compose ps`, `docker compose logs --tail=100 api` and `sh scripts/smoke.sh`.
6. Open http://localhost:8080 and http://localhost:8000/docs. Confirm readiness panels show actual backend states.
7. For a full E2E test, provision authorized fixtures, sources, provider data, validated models, and independently verified evidence.

## Security notes
Do not expose admin tokens to the browser, do not publish screenshots containing private data, and do not commit `.env`. Provider endpoint URLs must be explicitly allowlisted. Vision extraction is untrusted and cannot independently qualify bets.
