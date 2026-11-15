from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,func
from app.db import models as m
from app.modules.league_intelligence.ingestion import import_document,ImportValidationError
from app.modules.research import catalog
from test_research_catalogue import store,NOW


def document():
    return dict(sport='Football',country='England',competition='League',season='2026',source='Authorized Provider',
        source_url='https://provider.example/table',as_of=NOW.isoformat(),view='overall',entries=[
            dict(club='Imported A',position=1,played=1,won=1,drawn=0,lost=0,goals_for=2,goals_against=0,points=3),
            dict(club='Imported B',position=2,played=1,won=0,drawn=0,lost=1,goals_for=0,goals_against=2,points=0)])


def test_pending_hidden_replay_cannot_promote(store):
    doc=document()
    result=import_document(store,doc)
    store.commit()
    snap=store.get(m.StandingsSnapshot,result['snapshot_id'])
    assert snap.review_status=='PENDING_REVIEW' and snap.verified_at is None
    assert catalog.standings(store,'league','current')['mode']=='computed_unofficial'
    coverage=catalog.standings_coverage(store,'league','current')
    assert coverage['views']['overall']['status']=='PENDING_REVIEW'
    assert catalog.standings_history(store,'league','current')==[]
    replay=import_document(store,dict(doc,reviewed_by='Review Operator'),approve=True)
    assert replay['status']=='EXISTS' and replay['approved'] is False
    assert store.scalar(select(func.count()).select_from(m.StandingsSnapshot))==1
    assert store.scalar(select(func.count()).select_from(m.Sport))==1


def test_approved_csv_remains_provisional_and_review_cutoff_enforced(store):
    doc=dict(document(),reviewed_by='Review Operator',official=True,provenance={'status':'UNVERIFIED_COMPUTED','completed_matches':1})
    result=import_document(store,doc,approve=True)
    store.commit()
    report=catalog.standings(store,'league','current')
    assert report['mode']=='source_snapshot' and report['rows'][0]['club']=='Imported A'
    assert not report['source']['official'] and 'provisional' in report['warning']
    assert report['source']['reviewed_by']=='Review Operator'
    # Results dated October were only reviewed now; older cutoffs cannot see the imported table.
    assert catalog.standings(store,'league','current',NOW)['mode']=='computed_unofficial'
    assert len(catalog.standings_history(store,'league','current'))==1
    store.get(m.Source,'source').enabled=False
    store.commit()
    assert catalog.standings_history(store,'league','current')==[]
    assert catalog.standings_coverage(store,'league','current')['views']['overall']['status']=='MISSING'
    with pytest.raises(ImportValidationError,match='AUTHORIZED'):
        import_document(store,doc)


def test_explicit_new_season_dates_and_csv_date_bounds(store):
    doc=dict(document(),season='2027',season_start='2027-01-01',season_end='2027-12-31')
    result=import_document(store,doc)
    store.commit()
    assert store.get(m.CompetitionSeason,result['season_id']).label=='2027'
    assert store.get(m.StandingsSnapshot,result['snapshot_id']).review_status=='PENDING_REVIEW'
    bad=dict(document(),season='Unknown')
    with pytest.raises(ImportValidationError,match='dates are never guessed'):
        import_document(store,bad)
    store.rollback()
    bad=dict(document(),provenance={'first_match_date':'2025-01-01','last_match_date':'2026-01-01'})
    with pytest.raises(ImportValidationError,match='outside registered season'):
        import_document(store,bad)
    store.rollback()


def test_real_import_rejects_unregistered_source_and_dry_run_writes_nothing(store):
    doc=dict(document(),source='Unregistered')
    assert import_document(None,doc,dry_run=True)['status']=='VALID'
    with pytest.raises(ImportValidationError,match='AUTHORIZED'):
        import_document(store,doc)
    assert store.scalar(select(func.count()).select_from(m.StandingsSnapshot))==0
