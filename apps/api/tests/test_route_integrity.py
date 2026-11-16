"""Every static API route must be reachable: no duplicate registrations and no earlier parameterised route that captures it."""
from starlette.routing import Match
from fastapi.testclient import TestClient
from app.main import app

# Identical copy kept in an in-flight module edit; tracked in docs/AUDIT_2026-11-17.md (D-07).
# booking-codes/readiness is captured by /booking-codes/{id}, which delegates to it (behaviour asserted below).
KNOWN={('GET','/api/v1/sports/models/monitoring/summary'),('GET','/api/v1/sports/booking-codes/readiness')}


def unreachable():
 routes=[r for r in app.router.routes if hasattr(r,'path_regex')]
 found=set()
 for index,route in enumerate(routes):
  if '{' in route.path:continue
  for method in route.methods or ():
   scope={'type':'http','path':route.path,'method':method}
   if any(prior.matches(scope)[0]==Match.FULL for prior in routes[:index]):found.add((method,route.path))
 return found


def test_no_static_route_is_shadowed_or_duplicated():
 assert unreachable()-KNOWN==set()


def test_workflow_stages_are_the_canonical_twelve():
 rows=TestClient(app).get('/api/v1/sports/workflow/stages').json()
 assert [r['key'] for r in rows]==['discover','acquire','research','analyse','predict','evaluate','qualify','allocate','prepare','verify','monitor','reconcile']
 assert all('state' not in r for r in rows) and [r['key'] for r in rows if r['independent']]==['monitor','reconcile']


def test_booking_code_readiness_is_served_and_paper_only():
 body=TestClient(app).get('/api/v1/sports/booking-codes/readiness').json()
 assert body['mode']=='PAPER' and body['paid_wager_submission']=='DISABLED' and body['booking_code_verification']=='UNAVAILABLE'
