import pytest
from fastapi.testclient import TestClient
from app.main import app

MUTATIONS = [(method, route.path) for route in app.routes if hasattr(route, 'methods')
             for method in route.methods if method in ('POST', 'PUT', 'PATCH', 'DELETE')]


@pytest.mark.parametrize('method,path', MUTATIONS)
def test_every_mutation_requires_admin_before_body_or_database(method, path, monkeypatch):
    monkeypatch.setenv('SPORTS_ADMIN_TOKEN', 'test-only-expected-token')
    path = __import__('re').sub(r'\{[^}]+\}', 'unknown', path)
    with TestClient(app) as client:
        for headers in ({}, {'X-Admin-Token': 'invalid'}):
            response = client.request(method, path, json={}, headers=headers)
            assert response.status_code == 403, (method, path, response.text)
