from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.market_scanner import service, routes

APPROVED={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True,'holdout_metrics':{'brier':0.198,'log_loss':0.58,'sample_size':300}}


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    now=datetime.now(timezone.utc);at=now-timedelta(hours=1)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='Bundesliga',country='Germany'));db.flush()
        db.add(m.CompetitionSeason(id='season',competition_id='league',label='2026/27',start_date=date(2026,7,1),end_date=date(2027,6,30)))
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Fixture(id='fixture',competition_id='league',season_id='season',home_name='Home',away_name='Away',kickoff_at=now+timedelta(days=1)));db.flush()
        db.add(m.Observation(id='obs',source_id='source',fixture_id='fixture',observed_at=at,source_url='https://provider.example/e',content_hash='o'*64,payload={'section':'match_statistics','data':{}}))
        db.add(m.Research(id='dossier',fixture_id='fixture',version=1,status='VERIFIED',sections={'match_statistics':{'status':'VERIFIED','evidence_ids':['obs']}},evidence_ids=['obs'],created_at=at+timedelta(minutes=1)))
        db.add(m.Feature(id='feature',research_id='dossier',cutoff_at=at+timedelta(minutes=2),features={'evidence_ids':['obs']}))
        db.add(m.ModelVersion(id='active',sport_id='sport',name='Logit',version='1.0',status='ACTIVE',validation=APPROVED))
        db.add(m.ModelVersion(id='challenger',sport_id='sport',name='Challenger',version='0.1',status='CHALLENGER',validation={}));db.flush()
        for outcome,p,lo,hi,price in [('HOME',0.824,0.80,0.84,1.27),('DRAW',0.121,0.10,0.14,5.40),('AWAY',0.055,0.04,0.07,12.0)]:
            db.add(m.Prediction(id='p'+outcome,fixture_id='fixture',feature_id='feature',model_id='active',market_key='1X2',outcome_key=outcome,probability=p,predicted_at=at+timedelta(minutes=3),details={'interval':{'lower':lo,'upper':hi,'level':0.95}}))
            db.add(m.Odds(fixture_id='fixture',bookmaker='SportyBet',market_key='1X2',outcome_key=outcome,decimal_odds=price,observed_at=now-timedelta(minutes=5)))
        db.add(m.Prediction(id='pc',fixture_id='fixture',feature_id='feature',model_id='challenger',market_key='BTTS',outcome_key='YES',probability=0.9,predicted_at=at+timedelta(minutes=3)))
        for market,outcome,price in [('OU_2.5','OVER',1.56),('OU_2.5','UNDER',2.47),('BTTS','YES',2.08),('BTTS','NO',1.73),('DC','1X',1.05)]:
            db.add(m.Odds(fixture_id='fixture',bookmaker='SportyBet',market_key=market,outcome_key=outcome,decimal_odds=price,observed_at=now-timedelta(minutes=5)))
        db.add(m.Odds(fixture_id='fixture',bookmaker='Other Book',market_key='1X2',outcome_key='HOME',decimal_odds=1.30,observed_at=now-timedelta(minutes=5)))
    yield factory,now
    engine.dispose()


def test_catalogue_is_discovered_from_stored_odds(store):
    factory,now=store
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert report['bookmaker']=='SportyBet' and report['bookmakers']==['Other Book','SportyBet']
    assert [(mk['name'],mk['family']) for mk in report['markets']]==[('1X2 (Match Result)','Main Markets'),('Both Teams to Score','Both Teams to Score'),('Double Chance','Double Chance'),('Over/Under 2.5','Totals / Over-Under')]
    assert [s['name'] for s in report['markets'][0]['selections']]==['Home','Draw','Away']
    assert report['coverage']['selections']==8 and report['coverage']['modelled']==3 and report['coverage']['inventory']=='UNVERIFIED'
    assert dict((f['name'],f['count']) for f in report['families'])['Main Markets']==1


def test_evaluation_uses_existing_gates_and_lower_bound(store):
    factory,now=store
    with factory() as db:
        report=service.workspace(db,'fixture')
    rows={r['outcome_key']:r for r in report['evaluations']}
    assert set(rows)=={'HOME','DRAW','AWAY'}, 'challenger forecasts must be ignored'
    assert rows['HOME']['decision']=='QUALIFIED' and rows['HOME']['conservative_ev']==1.6
    assert rows['DRAW']['decision']=='REJECTED' and 'INSUFFICIENT_VALUE' in rows['DRAW']['reasons']
    assert report['evaluations'][0]['outcome_key']=='HOME'
    assert report['outcome']==dict(probabilities={'HOME':82.4,'DRAW':12.1,'AWAY':5.5},confidence='High')
    assert report['verdict']=='Model favours home win (82.4%).'
    with factory() as db:
        for ident in ('pDRAW','pAWAY'):db.delete(db.get(m.Prediction,ident))
        db.commit()
        assert service.workspace(db,'fixture')['verdict']=='Home win probability 82.4%; not a home win 17.6% (draw/away not modelled separately).'
    assert report['metrics']['model_brier']==0.198 and report['metrics']['predictions']==4


def test_other_bookmaker_and_stale_prices(store):
    factory,now=store
    with factory() as db:
        other=service.workspace(db,'fixture',bookmaker='Other Book')
        assert {r['outcome_key']:r['decision'] for r in other['evaluations']}=={'HOME':'QUALIFIED','DRAW':'NO_MARKET_PRICE','AWAY':'NO_MARKET_PRICE'}
        late=service.workspace(db,'fixture',now=now+timedelta(minutes=30))
        assert 'ODDS_STALE_OR_FUTURE' in next(r for r in late['evaluations'] if r['outcome_key']=='HOME')['reasons']


def test_unapproved_model_cannot_qualify(store):
    factory,now=store
    with factory.begin() as db:db.get(m.ModelVersion,'active').validation={'holdout_metrics':{'brier':0.2}}
    with factory() as db:
        report=service.workspace(db,'fixture')
    assert all(r['decision']=='REJECTED' for r in report['evaluations'])
    assert 'MODEL_NOT_INDEPENDENTLY_APPROVED' in report['evaluations'][0]['reasons']


def test_no_data_means_no_claims(store):
    factory,now=store
    with factory.begin() as db:
        db.add(m.Fixture(id='empty',competition_id='league',season_id='season',home_name='A',away_name='B',kickoff_at=now+timedelta(days=2)))
    with factory() as db:
        report=service.workspace(db,'empty')
    assert report['markets']==[] and report['evaluations']==[] and report['bookmaker'] is None
    assert report['coverage']['percent'] is None and report['verdict'] is None and report['outcome']['confidence'] is None


def test_endpoints(store,monkeypatch):
    factory,now=store;monkeypatch.setattr(routes,'SessionLocal',factory)
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    assert client.get('/api/v1/sports/market-scanner/fixtures/fixture').status_code==200
    assert client.get('/api/v1/sports/market-scanner/fixtures/missing').status_code==404
    body=client.get('/api/v1/sports/market-scanner/catalog').json()
    assert body['discovered_count']==4 and body['completeness'].startswith('UNVERIFIED')
    assert client.post('/api/v1/sports/market-scanner/fixtures/fixture').status_code==405
