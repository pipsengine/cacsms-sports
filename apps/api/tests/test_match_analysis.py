from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.research import deep_workspace_routes as deep
from app.modules.match_analysis import service, routes


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    at=datetime.now(timezone.utc)-timedelta(hours=1)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='League',country='Germany'));db.flush()
        db.add(m.CompetitionSeason(id='season',competition_id='league',label='2026/27',start_date=date(2026,7,1),end_date=date(2027,6,30)));db.flush()
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Source(id='blocked',name='Unverified Source',enabled=True,permission='UNVERIFIED'))
        db.add(m.Fixture(id='fixture',competition_id='league',season_id='season',home_name='Home',away_name='Away',kickoff_at=at+timedelta(days=1)));db.flush()
        ids=[];sections={}
        for i,key in enumerate(deep.SECTIONS):
            ident='obs'+str(i);ids.append(ident)
            db.add(m.Observation(id=ident,source_id='source',fixture_id='fixture',observed_at=at,source_url='https://provider.example/e',content_hash=ident.ljust(64,'0'),payload={'section':key,'data':{'fact':key}}))
            sections[key]={'status':'VERIFIED','evidence_ids':[ident]}
        db.add(m.Observation(id='bad',source_id='blocked',fixture_id='fixture',observed_at=at,source_url=None,content_hash='b'*64,payload={'section':'match_statistics'}))
        db.add(m.Research(id='dossier',fixture_id='fixture',version=1,status='VERIFIED',sections=sections,evidence_ids=ids+['bad'],created_at=at+timedelta(minutes=1)))
    yield factory,at
    engine.dispose()


def add_feature(factory,at,metrics):
    with factory.begin() as db:
        db.add(m.Feature(id='feature',research_id='dossier',cutoff_at=at+timedelta(minutes=2),features={'evidence_ids':['obs0'],'metrics':metrics}))


def test_without_features_or_models_nothing_is_simulated(store):
    factory,at=store
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert report['probabilities']==dict(home=None,draw=None,away=None,model=None,predicted_at=None)
    assert report['feature_comparison']==[] and report['expected_goals'] is None
    rows={r['key']:r['status'] for r in report['summary']}
    assert rows['tactics']==rows['features']=='MISSING' and rows['statistics']=='VERIFIED'
    assert report['status']=='PARTIAL' and report['metadata']['analysis_id'] is None
    assert {g['key']:g['count'] for g in report['evidence_groups']}['sources']==1


def test_feature_metrics_require_authorized_evidence(store):
    factory,at=store
    add_feature(factory,at,{'attack_strength':{'home':94.6,'away':63.1,'evidence_ids':['obs0']},
                            'xg_per_match':{'home':2.46,'away':1.03},
                            'midfield_control':{'home':91.3,'away':60.4,'evidence_ids':['bad']},
                            'form_rating':{'home':'0.88','away':0.36}})
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert [r['key'] for r in report['feature_comparison']]==['attack_strength']
    assert report['expected_goals']==dict(home=2.46,away=1.03)
    assert next(r for r in report['form_metrics'] if r['key']=='xg_per_match')['basis']=='FEATURE_SNAPSHOT'
    rows={r['key']:r['status'] for r in report['summary']}
    assert rows['tactics']==rows['features']=='VERIFIED'
    assert report['metadata']['analysis_id']=='feature'


def test_pipeline_numeric_features_count_as_feature_engineering(store):
    factory,at=store
    with factory.begin() as db:
        db.add(m.Feature(id='feature',research_id='dossier',cutoff_at=at+timedelta(minutes=2),features={'evidence_ids':['obs0'],'numeric_features':{'home_form':2.2,'away_form':0.8}}))
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert {r['key']:r['status'] for r in report['summary']}['features']=='VERIFIED'
    assert report['feature_comparison']==[dict(key='form_rating',label='Form Rating',home=2.2,away=0.8,unit='pts/match')]


def test_feature_ignored_when_dossier_not_verified(store):
    factory,at=store
    add_feature(factory,at,{'attack_strength':{'home':1,'away':2}})
    with factory.begin() as db:db.get(m.Research,'dossier').status='DRAFT'
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert report['feature_comparison']==[] and report['metadata']['feature_versions']==1


def test_probabilities_only_from_active_models_before_cutoff(store):
    factory,at=store
    add_feature(factory,at,{})
    with factory.begin() as db:
        db.add(m.ModelVersion(id='active',sport_id='sport',name='Poisson',version='1.0',status='ACTIVE'))
        db.add(m.ModelVersion(id='challenger',sport_id='sport',name='Challenger',version='0.1',status='CHALLENGER'));db.flush()
        for outcome,p in [('HOME',0.824),('DRAW',0.121),('AWAY',0.055)]:
            db.add(m.Prediction(fixture_id='fixture',feature_id='feature',model_id='active',market_key='1X2',outcome_key=outcome,probability=p,predicted_at=at+timedelta(minutes=3)))
        db.add(m.Prediction(fixture_id='fixture',feature_id='feature',model_id='challenger',market_key='1X2',outcome_key='HOME',probability=0.99,predicted_at=at+timedelta(minutes=4)))
    with factory() as db:
        report=service.workspace(db,'fixture')
        assert (report['probabilities']['home'],report['probabilities']['draw'],report['probabilities']['away'])==(82.4,12.1,5.5)
        assert report['probabilities']['model']=='Poisson 1.0'
        past=service.workspace(db,'fixture',at+timedelta(minutes=2,seconds=30))
        assert past['probabilities']['home'] is None


def test_endpoints(store,monkeypatch):
    factory,at=store;monkeypatch.setattr(routes,'SessionLocal',factory)
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/match-analysis/fixtures/fixture').status_code==200
    assert client.get('/api/v1/sports/match-analysis/fixtures/missing').status_code==404
    assert client.get('/api/v1/sports/match-analysis/summary').json()['research_dossiers']==1
