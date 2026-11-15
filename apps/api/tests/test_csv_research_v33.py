from datetime import datetime,timezone
import pytest
from app.modules.league_intelligence.csv_research import build_standings,CSVResearchError
from app.modules.league_intelligence.ingestion import validate_document

META=dict(sport='Football',country='England',competition='Test League',season='2025/26',source='Authorized CSV',source_url='https://example.org/permitted',as_of='2026-06-01T00:00:00+00:00')

def test_permission_required(tmp_path):
    p=tmp_path/'games.csv';p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,H\n')
    with pytest.raises(CSVResearchError,match='permission'):
        build_standings(p,**META)

def test_standings_and_cutoff(tmp_path):
    p=tmp_path/'games.csv'
    p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,H\n02/01/2026,B,A,0,0,D\n01/07/2026,B,A,9,0,H\n')
    doc=build_standings(p,permitted=True,**META)
    assert doc['provenance']['completed_matches']==2
    assert doc['entries'][0]['club']=='A'
    assert doc['entries'][0]['points']==4
    assert validate_document(doc)['entries'][0]['position']==1

def test_reject_inconsistent_result(tmp_path):
    p=tmp_path/'games.csv';p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,A\n')
    with pytest.raises(CSVResearchError,match='inconsistent'):
        build_standings(p,permitted=True,**META)


def test_normalized_date_duplicate_and_case_identity(tmp_path):
    p=tmp_path/'games.csv'
    p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,H\n02/01/26,b,a,0,0,D\n')
    doc=build_standings(p,permitted=True,**META)
    assert len(doc['entries'])==2 and doc['entries'][0]['points']==4
    assert doc['entries'][0]['form']=='WD'
    assert len(doc['provenance']['input_sha256'])==64
    p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,H\n1/1/26,a,b,2,1,H\n')
    with pytest.raises(CSVResearchError,match='duplicate'):
        build_standings(p,permitted=True,**META)


def test_date_only_rows_do_not_leak_cutoff_day_results(tmp_path):
    p=tmp_path/'games.csv'
    p.write_text('Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2026,A,B,2,1,H\n')
    meta=dict(META,as_of='2026-01-01T23:59:59+00:00')
    with pytest.raises(CSVResearchError,match='No completed'):
        build_standings(p,permitted=True,**meta)
