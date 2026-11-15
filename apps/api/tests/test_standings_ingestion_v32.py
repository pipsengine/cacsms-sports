from datetime import datetime,timezone,timedelta
import pytest
from app.modules.league_intelligence.ingestion import validate_document,ImportValidationError,import_document

def sample():
 return {'sport':'Football','country':'England','competition':'Example League','season':'2026/27','source':'AuthorizedSource','source_url':'https://example.org/standings','as_of':'2026-11-01T18:00:00+00:00','view':'overall','entries':[
  {'club':'A','position':1,'played':2,'won':2,'drawn':0,'lost':0,'goals_for':5,'goals_against':1,'points':6},
  {'club':'B','position':2,'played':2,'won':0,'drawn':0,'lost':2,'goals_for':1,'goals_against':5,'points':0}]}

def test_valid_dry_run():
 assert import_document(None,sample(),dry_run=True)['status']=='VALID'
def test_duplicate_club_rejected():
 d=sample();d['entries'][1]['club']='a'
 with pytest.raises(ImportValidationError,match='Duplicate club'):validate_document(d)
def test_inconsistent_played_rejected():
 d=sample();d['entries'][0]['played']=4
 with pytest.raises(ImportValidationError,match='Played'):validate_document(d)
def test_future_snapshot_rejected():
 d=sample();d['as_of']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
 with pytest.raises(ImportValidationError,match='Future'):validate_document(d)
def test_approval_needs_reviewer():
 with pytest.raises(ImportValidationError,match='reviewed_by'):import_document(None,sample(),approve=True,dry_run=True)
