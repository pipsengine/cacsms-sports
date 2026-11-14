#!/bin/sh
set -eu
API="${API_URL:-http://localhost:8000}"
WEB="${WEB_URL:-http://localhost:8080}"
printf 'Checking API liveness...\n'
curl --fail --silent --show-error "$API/health"
printf '\nChecking readiness gates...\n'
curl --fail --silent --show-error "$API/api/v1/sports/readiness"
printf '\nChecking frontend...\n'
curl --fail --silent --show-error "$WEB/" >/dev/null
printf 'Frontend and API reachable. Verify database readiness and run integration tests separately.\n'
