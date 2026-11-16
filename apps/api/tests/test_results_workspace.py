from datetime import datetime, timedelta, timezone
from app.db import models as m
from app.modules.results.workspace import workspace, latest_settlement_rows
from test_browser_intelligence import factory


def seed(db):
    now = datetime.now(timezone.utc)
    db.add(m.Sport(id='sport', name='Football'))
    db.add(m.Competition(id='league', sport_id='sport', name='Test League'))
    db.add(m.Fixture(id='fixture', competition_id='league', home_name='Home', away_name='Away', kickoff_at=now-timedelta(hours=4), status='FINAL'))
    db.add(m.ModelVersion(id='model', sport_id='sport', name='Model', version='1', validation={}))
    db.add(m.Research(id='research', fixture_id='fixture', version=1, status='VERIFIED', sections={}, evidence_ids=[]))
    db.add(m.Feature(id='feature', research_id='research', cutoff_at=now-timedelta(hours=5), features={}))
    db.add(m.Prediction(id='prediction', fixture_id='fixture', feature_id='feature', model_id='model', market_key='1X2', outcome_key='HOME', probability=.8))
    db.add(m.Result(id='v1', fixture_id='fixture', version=1, verified_at=now-timedelta(hours=1), outcome={'status':'FINAL','score':{'home':2,'away':0},'outcomes':{'1X2':{'HOME':'WON'}}}))
    db.add(m.Settlement(id='old', prediction_id='prediction', result_id='v1', outcome='WON'))


def test_correction_counts_only_current_result_and_preserves_history():
    Session = factory()
    with Session.begin() as db:
        seed(db)
        db.add(m.Result(id='v2', fixture_id='fixture', version=2, verified_at=datetime.now(timezone.utc), outcome={'status':'FINAL','score':{'home':0,'away':1},'outcomes':{'1X2':{'HOME':'LOST'}}}))
        db.add(m.Settlement(id='new', prediction_id='prediction', result_id='v2', outcome='LOST'))
    with Session() as db:
        report = workspace(db)
        assert report['summary']['wins'] == 0
        assert report['summary']['losses'] == 1
        assert report['summary']['verified_matches'] == 1
        assert report['summary']['corrected_matches'] == 1
        assert report['summary']['quality']['hit_rate'] == 0
        assert report['register'][0]['score'] == '0 – 1'
        assert report['register'][0]['fixture'] == 'Home vs Away'
        assert len(latest_settlement_rows(db)) == 1
        assert db.get(m.Settlement, 'old') is not None


def test_new_version_without_settlement_never_falls_back_to_old_win():
    Session = factory()
    with Session.begin() as db:
        seed(db)
        db.add(m.Result(id='v2', fixture_id='fixture', version=2, verified_at=datetime.now(timezone.utc), outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':'LOST'}}}))
    with Session() as db:
        report = workspace(db)
        assert report['summary']['settled_forecasts'] == 0
        assert report['summary']['pending'] == 1
        assert report['summary']['quality']['hit_rate'] is None
        assert report['settlements'][0]['outcome'] == 'PENDING'
        assert report['exceptions'][0]['reason'] == 'AWAITING_SETTLEMENT'
        assert report['reconciliation']['missing_current_settlements'] == 1


def test_empty_workspace_and_future_forecasts_do_not_invent_results():
    Session = factory()
    with Session() as db:
        report = workspace(db)
        assert report['register'] == []
        assert report['summary']['roi'] is None
        assert report['summary']['quality']['brier'] is None
        assert report['learning']['automatic_deployment'] is False
    with Session.begin() as db:
        seed(db)
        db.add(m.Fixture(id='future', competition_id='league', home_name='Future', away_name='Next', kickoff_at=datetime.now(timezone.utc)+timedelta(days=1)))
        db.add(m.Prediction(id='future-pred', fixture_id='future', feature_id='feature', model_id='model', market_key='1X2', outcome_key='HOME', probability=.6))
    with Session() as db:
        report = workspace(db)
        assert report['summary']['pending'] == 1
        assert report['exceptions'] == []


def test_voids_and_pushes_are_excluded_from_hit_rate():
    Session = factory()
    with Session.begin() as db:
        seed(db)
        db.add(m.Prediction(id='void-pred', fixture_id='fixture', feature_id='feature', model_id='model', market_key='TOTAL', outcome_key='OVER', probability=.7))
        db.add(m.Settlement(id='void', prediction_id='void-pred', result_id='v1', outcome='VOID'))
        db.add(m.Prediction(id='push-pred', fixture_id='fixture', feature_id='feature', model_id='model', market_key='HANDICAP', outcome_key='HOME', probability=.5))
        db.add(m.Settlement(id='push', prediction_id='push-pred', result_id='v1', outcome='PUSH'))
    with Session() as db:
        report = workspace(db)
        assert report['summary']['settled_forecasts'] == 3
        assert report['summary']['wins'] == 1
        assert report['summary']['quality']['settled_forecasts'] == 1
        assert report['summary']['quality']['hit_rate'] == 1


def test_workspace_exposes_source_provenance_and_result_audit_only():
    Session = factory()
    with Session.begin() as db:
        seed(db)
        db.add(m.Source(id='source', name='Authorized Feed', enabled=True, permission='AUTHORIZED'))
        db.add(m.Observation(id='observation', source_id='source', fixture_id='fixture', source_url='https://example.org/result', content_hash='a'*64, payload={}, observed_at=datetime.now(timezone.utc)))
        db.add(m.ResultEvidence(result_id='v1', source_id='source', observation_id='observation'))
        db.add(m.AuditEvent(actor='system', action='result.automatic_reconciliation', correlation_id='v1', payload={'version':1}))
        db.add(m.AuditEvent(actor='system', action='browser.capture', correlation_id='capture', payload={}))
    with Session() as db:
        report = workspace(db)
        assert report['acquisition']['sources'] == ['Authorized Feed']
        assert report['register'][0]['evidence'][0]['sha256'] == 'a'*64
        assert report['reconciliation']['results_with_evidence'] == 1
        assert len(report['audit']) == 1
        assert report['audit'][0]['event'] == 'result.automatic_reconciliation'
