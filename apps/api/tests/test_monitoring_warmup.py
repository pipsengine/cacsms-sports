from types import SimpleNamespace
from app.db import models as m
from app.modules.governance.policy import assess_model
from app.modules.governance.service import evaluate_models, monitoring_status
from test_performance_workspace import seeded


def active():
    return SimpleNamespace(status='ACTIVE', validation={k:True for k in ('approved','out_of_sample','calibrated','calibration_verified')})


def test_waiting_is_not_monitoring_clearance_or_a_validation_failure():
    decision = assess_model(None, None)
    assert decision.status == 'BLOCKED'  # Sample gate still fails closed.
    assert monitoring_status(active(), decision, 0) == 'AWAITING_OUTCOMES'
    assert monitoring_status(active(), decision, 30) == 'WARMING_UP'
    assert monitoring_status(SimpleNamespace(status='CHALLENGER',validation={}), decision, 0) == 'BLOCKED'


def test_complete_windows_still_require_calibration_and_drift_checks():
    reference = {'n':50,'brier':.15,'ece':.02}
    passing = assess_model(reference, {'n':50,'brier':.16,'ece':.03})
    assert monitoring_status(active(), passing, 100) == 'MONITORED'
    failing = assess_model(reference, {'n':50,'brier':.25,'ece':.03})
    assert monitoring_status(active(), failing, 100) == 'BLOCKED'
    assert 'BRIER_DEGRADATION' in failing.reasons


def test_bad_recent_calibration_is_blocked_even_without_reference_window():
    decision = assess_model(None, {'n':50,'brier':.15,'ece':.3})
    assert 'CALIBRATION_DRIFT' in decision.reasons
    assert monitoring_status(active(), decision, 50) == 'BLOCKED'


def test_scheduler_persists_progress_without_reusing_holdout_or_promoting():
    Session = seeded()
    with Session.begin() as db:
        model = db.get(m.ModelVersion,'model')
        model.status = 'ACTIVE'
        model.validation = {**active().validation,'holdout_count':378,'training_count':879}
        db.delete(db.get(m.Settlement,'old'))
    with Session.begin() as db:
        report = evaluate_models(db)
        row = report[0]
        assert row['status'] == 'AWAITING_OUTCOMES'
        assert row['monitoring_ready'] is False
        assert row['sample_progress']['scored_outcomes'] == 0
        assert row['sample_progress']['required_total'] == 100
        assert row['sample_progress']['pending_forecasts'] == 1
        assert row['sample_progress']['missing_recent'] == 50
        assert row['sample_progress']['missing_reference'] == 50
    with Session() as db:
        from sqlalchemy import select
        snapshot = db.scalar(select(m.ModelGovernanceSnapshot))
        assert snapshot.status == 'AWAITING_OUTCOMES'
        assert snapshot.recent['monitoring_progress']['samples_ready'] is False
        assert db.get(m.ModelVersion,'model').status == 'ACTIVE'
