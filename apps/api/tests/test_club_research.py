from datetime import datetime, timezone
from types import SimpleNamespace as N
import pytest
from app.modules.research.league import compute_table, top_two_research
from app.modules.results.service import validate_result_payload, ResultValidationError

def test_table():
    rows=compute_table([dict(home_id='A',away_id='B',home_score=2,away_score=0),dict(home_id='B',away_id='C',home_score=1,away_score=1)])
    assert [r['team_id'] for r in rows]==['A','C','B']
    assert rows[0]['points']==3

def test_score_preserved_and_validated():
    payload=dict(status='FINAL',outcomes={'1X2':{'HOME':'WON'}},score={'home':2,'away':0})
    assert validate_result_payload(payload)==payload
    for score in ({'home':True,'away':0},{'home':-1,'away':0},{'home':1.5,'away':0}):
        with pytest.raises(ResultValidationError):validate_result_payload(dict(payload,score=score))

class DB:
    def __init__(self, records, evidence):self.records=records;self.evidence=evidence
    def get(self, model, key):
        if model.__name__=='Competition':return N(id='c',name='League',country=None,sport_id='s')
        return N(name='football')
    def execute(self, query):
        return N(all=lambda:self.evidence if 'result_evidence' in str(query) else self.records)

def test_cutoff_corrections_and_evidence():
    kickoff=datetime(2026,1,1,tzinfo=timezone.utc)
    fixture=N(id='f',home_name='A',away_name='B',kickoff_at=kickoff)
    result=N(id='r',version=2,verified_at=kickoff,outcome=dict(status='FINAL',score={'home':2,'away':0}))
    evidence=[(N(id='e'),N(source_id='s',fixture_id='f',observed_at=kickoff),N(id='s',enabled=True,permission='AUTHORIZED'))]
    db=DB([(fixture,result)],evidence)
    report=top_two_research(db,'c',datetime(2026,2,1,tzinfo=timezone.utc))
    assert report['top_two'][0]['club']=='A'
    assert report['head_to_head'][0]['result_version']==2
    assert report['qualified'] is False
    db.evidence=[]
    assert top_two_research(db,'c')['status']=='insufficient_data'
    db.evidence=evidence
    correction=N(id='r2',version=3,verified_at=kickoff,outcome={'status':'FINAL'})
    db.records=[(fixture,correction),(fixture,result)]
    assert top_two_research(db,'c')['verified_matches']==0
    with pytest.raises(ValueError):top_two_research(db,'c',datetime(2026,2,1))


def test_research_baseline():
    from app.modules.research.poisson import total_over_probability
    assert total_over_probability(0, 0) == 0
    assert 0 < total_over_probability(1.5, 1.2) < 1
    for rates in ((-1, 2), (float('nan'), 1)):
        with pytest.raises(ValueError):total_over_probability(*rates)


def test_competition_route_precedes_resource_fallback(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app.main import app
    from app.modules.research import league_routes
    monkeypatch.setattr(league_routes, 'SessionLocal', lambda: nullcontext(N(execute=lambda query: [])))
    response=TestClient(app).get('/api/v1/sports/competitions')
    assert response.status_code == 200
    assert response.json() == []
