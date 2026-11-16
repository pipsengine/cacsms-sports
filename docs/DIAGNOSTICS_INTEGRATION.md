# Diagnostics dashboard integration

The Diagnostics & Incidents workspace at `/sports/diagnostics` adapts the supplied standalone diagnostics module and dashboard reference into the existing platform shell. It uses the existing browser, governance, incident, audit and autonomous runtime records rather than introducing a second application, database or scheduler.

`GET /api/v1/sports/diagnostics/overview` checks database connectivity and reads incidents, audit events and controller leases. Expired or missing leases report OFFLINE; active leases with consecutive errors report DEGRADED. Database failures return HTTP 503. The displayed observed-health percentage covers only these registered checks and is not uptime or comprehensive subsystem readiness.

The seven dashboard tabs provide an overview, searchable incident register, service and worker status, browser configuration diagnostics, automation boundaries, audit records and read-only configuration. Data refreshes every 30 seconds. Failed refreshes display an error alongside any retained observations and their timestamp.

No historical uptime, process performance metrics, restart automation, escalation delivery or new browser authorization is introduced. PAPER mode remains enforced. Existing source permissions and capture controls apply. No additional dependencies or database migrations are required.
