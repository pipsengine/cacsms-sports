from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db import models as m
from app.modules.results.performance import analytics
from app.modules.results import routes
from test_results_workspace import seed
from test_browser_intelligence import factory

AT = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def seeded():
    Session = factory()
    with Session.begin() as db:
        seed(db)
        db.flush()
        db.get(m.Prediction, 'prediction').predicted_at = AT-timedelta(days=2)
        db.get(m.Fixture, 'fixture').kickoff_at = AT-timedelta(days=1)
        db.get(m.Result, 'v1').verified_at = AT-timedelta(hours=1)
    return Session


def test_scores_groups_calibration_and_trend_use_real_outcomes():
    Session = seeded()
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['metrics']['brier'] == .04
        assert report['metrics']['hit_rate'] == 1
        assert report['metrics']['calibration_error'] == .2
        assert report['metrics']['status'] == 'INSUFFICIENT_DATA'
        assert report['by_market'][0]['name'] == '1X2'
        assert report['by_league'][0]['name'] == 'Test League'
        assert report['models'][0]['version'] == '1'
        assert report['calibration'][0]['count'] == 1
        assert report['trend'][0]['scored'] == 1
        assert report['profitability']['roi'] is None
        assert report['learning']['automatic_deployment'] is False


def test_corrections_and_missing_current_settlements_exclude_old_win():
    Session = seeded()
    with Session.begin() as db:
        db.add(m.Result(id='v2', fixture_id='fixture', version=2, verified_at=AT, outcome={'status':'FINAL','outcomes':{'1X2':{'HOME':'LOST'}}}))
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['metrics']['wins'] == 0
        assert report['metrics']['pending'] == 1
        assert report['metrics']['hit_rate'] is None
        assert report['trend'] == []
    with Session.begin() as db:
        db.add(m.Settlement(id='new', prediction_id='prediction', result_id='v2', outcome='LOST'))
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['metrics']['losses'] == 1
        assert report['metrics']['brier'] == .64
        assert report['records'][0]['result_version'] == 2


def test_forecast_cohort_filters_old_future_and_retrospective_forecasts():
    Session = seeded()
    with Session.begin() as db:
        for key, timestamp in [('old', AT-timedelta(days=40)), ('future', AT+timedelta(days=1)), ('retrospective', AT-timedelta(hours=1))]:
            db.add(m.Prediction(id=key, fixture_id='fixture', model_id='model', feature_id='feature', market_key='1X2', outcome_key='HOME', probability=.7, predicted_at=timestamp))
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['total_forecasts'] == 1
        assert report['excluded_forecasts'] == 1
        assert len(report['records']) == 1
        assert report['period_basis'] == 'FORECAST_ISSUED_AT'
        assert analytics(db, 1, AT)['total_forecasts'] == 0


def test_void_does_not_create_accuracy_and_days_use_wat():
    Session = seeded()
    with Session.begin() as db:
        db.get(m.Settlement, 'old').outcome = 'VOID'
        db.get(m.Result, 'v1').verified_at = datetime(2026,11,16,23,30,tzinfo=timezone.utc)
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['metrics']['settled'] == 1
        assert report['metrics']['scored'] == 0
        assert report['metrics']['hit_rate'] is None
        assert report['calibration'] == []
    with Session.begin() as db:
        db.get(m.Settlement, 'old').outcome = 'WON'
    with Session() as db:
        assert analytics(db, 30, AT)['trend'][0]['date'] == '2026-11-17'


def test_programme_membership_deduplicates_forecasts_across_tickets():
    Session = seeded()
    with Session.begin() as db:
        db.add(m.Programme(id='programme', key='singles', configuration={}))
        db.add(m.Odds(id='odds', fixture_id='fixture', bookmaker='Paper', market_key='1X2', outcome_key='HOME', decimal_odds=2, observed_at=AT-timedelta(days=3)))
        db.add(m.Qualification(id='qualification', prediction_id='prediction', odds_id='odds', gates={}, decision='QUALIFIED'))
        for i in range(2):
            db.add(m.Ticket(id=f'ticket-{i}', programme_id='programme', status='PAPER_DRAFT'))
            db.add(m.TicketLeg(ticket_id=f'ticket-{i}', qualification_id='qualification'))
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['programmes'][0]['forecasts'] == 1
        assert report['programmes'][0]['wins'] == 1
        assert report['programmes'][0]['tickets'] == 2


def test_empty_and_api_date_range_validation(monkeypatch):
    Session = factory()
    with Session() as db:
        report = analytics(db, 30, AT)
        assert report['metrics']['status'] == 'NO_DATA'
        assert report['metrics']['hit_rate'] is None
        assert report['models'] == []
    monkeypatch.setattr(routes, 'SessionLocal', Session)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get('/api/v1/sports/performance/workspace?days=0').status_code == 422
        assert client.get('/api/v1/sports/performance/workspace?days=366').status_code == 422
        response = client.get('/api/v1/sports/performance/workspace?days=7')
        assert response.status_code == 200
        assert response.json()['period_days'] == 7
