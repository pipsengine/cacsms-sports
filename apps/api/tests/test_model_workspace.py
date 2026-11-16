from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.governance.workspace import workspace
from app.modules.governance import routes
from app.modules.learning.routes import model_rows
from test_performance_workspace import seeded, AT
from test_browser_intelligence import factory


def test_active_registry_state_requires_all_recorded_approval_flags():
    Session = seeded()
    with Session.begin() as db:
        model = db.get(m.ModelVersion, 'model')
        model.status = 'ACTIVE'
        model.validation = {'approved': True, 'out_of_sample': True, 'calibrated': True}
    with Session() as db:
        report = workspace(db, 30, AT)
        assert report['summary']['approved_active'] == 0
        assert report['registry'][0]['approvals']['calibration_verified'] is False
        assert report['registry'][0]['registry_status'] == 'ACTIVE'
    with Session.begin() as db:
        model = db.get(m.ModelVersion, 'model')
        model.validation = {**model.validation, 'calibration_verified': True}
    with Session() as db:
        assert workspace(db, 30, AT)['summary']['approved_active'] == 1


def test_holdout_and_prospective_metrics_are_separate_and_artifact_is_sanitized():
    Session = seeded()
    with Session.begin() as db:
        db.get(m.ModelVersion, 'model').validation = {
            'training_count': 80, 'holdout_count': 30, 'holdout_metrics': {'brier': .18, 'log_loss': .51},
            'baseline_metrics': {'brier': .24}, 'coefficients': [123], 'means': [99],
            'reliability_bins': [{'predicted': .8, 'observed': .7, 'count': 10}],
            'markets': {'1X2|HOME': {'approved': True, 'holdout': {'brier': .17}, 'reasons': []}},
        }
    with Session() as db:
        report = workspace(db, 30, AT)
        row = report['registry'][0]
        assert row['holdout']['brier'] == .18
        assert row['metrics']['brier'] == .04
        assert row['reliability'][0]['count'] == 10
        assert row['markets'][0]['approved'] is True
        assert 'coefficients' not in row and 'means' not in row
        assert report['summary']['training_artifacts'] == 1
        assert report['summary']['experiments'] is None
        assert db.get(m.ModelVersion, 'model').status == 'CHALLENGER'


def test_latest_monitoring_and_registry_approval_remain_independent():
    Session = seeded()
    with Session.begin() as db:
        db.add(m.ModelGovernanceSnapshot(id='old', model_id='model', status='MONITORED', reasons=[], reference={}, recent={}, created_at=AT-timedelta(hours=2)))
        db.add(m.ModelGovernanceSnapshot(id='new', model_id='model', status='BLOCKED', reasons=['INSUFFICIENT_RECENT_SAMPLE'], reference={'n':50}, recent={'n':1}, created_at=AT))
        db.add(m.Incident(severity='HIGH', message='MODEL_DRIFT:model review', status='OPEN'))
        db.add(m.Incident(severity='HIGH', message='Browser capture issue', status='OPEN'))
    with Session() as db:
        report = workspace(db, 30, AT)
        assert report['summary']['evaluations'] == 2
        assert report['summary']['monitoring_blocked'] == 1
        assert report['registry'][0]['history'][0]['id'] == 'new'
        assert report['registry'][0]['monitoring'] == 'BLOCKED'
        assert len(report['alerts']) == 1
        assert db.get(m.ModelVersion, 'model').status == 'CHALLENGER'


def test_correction_without_new_settlement_is_not_counted_by_model_monitoring():
    Session = seeded()
    with Session.begin() as db:
        db.add(m.Result(id='correction', fixture_id='fixture', version=2, verified_at=AT, outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':'LOST'}}}))
    with Session() as db:
        assert model_rows(db, 'model') == []
        report = workspace(db, 30, AT)
        assert report['registry'][0]['metrics']['scored'] == 0
        assert report['registry'][0]['trend'] == []


def test_empty_read_only_workspace_and_http_validation(monkeypatch):
    Session = factory()
    monkeypatch.setattr(routes, 'SessionLocal', Session)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.get('/api/v1/sports/models/workspace')
        assert response.status_code == 200
        report = response.json()
        assert report['mode'] == 'PAPER' and report['live_wagers'] is False
        assert report['registry'] == []
        assert report['boundaries']['dashboard_access'] == 'READ_ONLY'
        assert client.get('/api/v1/sports/models/workspace?days=0').status_code == 422
