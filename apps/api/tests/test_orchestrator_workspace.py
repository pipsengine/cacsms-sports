from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.db import models as m
from app.modules.pipeline import routes,logic
from tests.test_accumulator_engine import store  # noqa: F401


def client_for(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes,'SessionLocal',factory)
    with factory.begin() as db:
        db.add(m.PipelineRun(id='run',idempotency_key='orchestrator-ui-test',fixture_id='f1',mode='PAPER',status='WAITING_FOR_DATA',context={}));db.flush()
        for i,(key,_,_) in enumerate(logic.STAGES,1):
            db.add(m.PipelineStage(id='stage'+str(i),run_id='run',position=i,stage_key=key,status='PENDING',input_payload={},output_payload={},evidence_ids=['obs','missing-ref'] if key=='acquire' else []))
    app=FastAPI();app.include_router(routes.router)
    return TestClient(app),factory


def test_contracts_match_canonical_twelve_stage_runner(store,monkeypatch):
    client,factory=client_for(store,monkeypatch)
    defs=client.get('/api/v1/sports/pipeline/contracts').json()
    assert [d['key'] for d in defs]==[k for k,_,_ in logic.STAGES]
    assert defs[5]['dependencies']==['predict']
    assert defs[10]['dependency_policy']=='INDEPENDENT' and defs[10]['dependencies']==[]
    assert defs[11]['dependency_policy']=='INDEPENDENT'
    assert all(d['sla_ms'] is None for d in defs)


def test_only_recorded_references_resolve_without_mutation(store,monkeypatch):
    client,factory=client_for(store,monkeypatch)
    records=client.get('/api/v1/sports/pipeline/runs/run/evidence?stage=acquire').json()
    assert len(records)==2 and records[0]['type']=='Observation'
    assert records[1]['type']=='UNRESOLVED'
    assert client.get('/api/v1/sports/pipeline/runs/run/evidence?stage=research').json()==[]
    assert client.get('/api/v1/sports/pipeline/runs/missing/evidence?stage=acquire').status_code==404
    assert client.get('/api/v1/sports/pipeline/runs/run/evidence?stage=unknown').status_code==422
    assert client.post('/api/v1/sports/pipeline/contracts').status_code==405
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.PipelineRun))==1
        assert db.scalar(select(func.count()).select_from(m.PipelineStageRun))==0
        assert db.get(m.PipelineStage,'stage2').status=='PENDING'


def test_revoked_source_reference_is_redacted(store,monkeypatch):
    client,factory=client_for(store,monkeypatch)
    with factory.begin() as db:db.get(m.Source,'src').enabled=False
    record=client.get('/api/v1/sports/pipeline/runs/run/evidence?stage=acquire').json()[0]
    assert record['status']=='SOURCE_UNAVAILABLE' and 'payload' not in record['record']
