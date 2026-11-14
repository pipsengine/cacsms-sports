from datetime import datetime,timezone,timedelta
import pytest
from app.modules.acquisition.service import utc,validate_url,fingerprint,ingest_observation,build_feature_snapshot
from app.db import models as m

NOW=datetime.now(timezone.utc)
class FakeSession:
    def __init__(self,records):self.records=records;self.added=[]
    def get(self,model,key):return self.records.get((model,key))
    def scalar(self,query):return None
    def add(self,obj):self.added.append(obj)
    def flush(self):
        for obj in self.added:
            if not obj.id:obj.id='test-generated-id'

def test_timezone_required():
    with pytest.raises(ValueError,match='timezone'):utc(datetime(2026,1,1))

def test_internal_url_blocked():
    for url in ['http://example.com','https://localhost/x','https://127.0.0.1/x','https://10.0.0.1/x']:
        with pytest.raises(ValueError):validate_url(url)

def test_fingerprint_deterministic():
    args=('src','fix','standings','https://example.com',NOW,{'x':1})
    assert fingerprint(*args)==fingerprint(*args)

def test_disabled_source_fails_closed():
    source=m.Source(id='s',name='Example',permission='UNVERIFIED',enabled=False)
    session=FakeSession({(m.Source,'s'):source})
    with pytest.raises(PermissionError):ingest_observation(session,source_id='s',fixture_id='f',section='standings',source_url='https://example.com',observed_at=NOW,payload={'value':1})

def test_observation_provenance_and_payload():
    source=m.Source(id='s',name='Example',permission='AUTHORIZED',enabled=True)
    fixture=m.Fixture(id='f',competition_id='c',home_name='A',away_name='B',kickoff_at=NOW+timedelta(days=1))
    session=FakeSession({(m.Source,'s'):source,(m.Fixture,'f'):fixture})
    result=ingest_observation(session,source_id='s',fixture_id='f',section='standings',source_url='https://example.com/match',observed_at=NOW-timedelta(minutes=1),payload={'rank':3})
    assert result['duplicate'] is False
    assert session.added[0].payload['section']=='standings'

def test_feature_cutoff_prevents_future_leakage():
    fixture=m.Fixture(id='f',competition_id='c',home_name='A',away_name='B',kickoff_at=NOW+timedelta(days=1))
    dossier=m.Research(id='r',fixture_id='f',version=1,status='PARTIAL',sections={'standings':{'status':'VERIFIED','evidence_ids':['e']}},evidence_ids=['e'])
    source=m.Source(id='s',name='Example',permission='AUTHORIZED',enabled=True)
    obs=m.Observation(id='e',source_id='s',fixture_id='f',source_url='https://example.com',content_hash='x'*64,observed_at=NOW,payload={'section':'standings','data':{'rank':2}})
    session=FakeSession({(m.Fixture,'f'):fixture,(m.Research,'r'):dossier,(m.Source,'s'):source,(m.Observation,'e'):obs})
    with pytest.raises(ValueError,match='after the feature cutoff'):
        build_feature_snapshot(session,research_id='r',cutoff_at=NOW-timedelta(minutes=1),required_sections=['standings'])
    result=build_feature_snapshot(session,research_id='r',cutoff_at=NOW+timedelta(minutes=1),required_sections=['standings'])
    assert result['status']=='MATERIALIZED_NOT_MODEL_APPROVED'
