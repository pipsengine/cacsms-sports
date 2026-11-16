import math,random
from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db import models as m
from app.modules.prediction import market_model as mm
from app.modules.prediction.service import FEATURE_NAMES

F={'home_form':2.2,'away_form':0.8,'home_scoring_rate':2.6,'away_scoring_rate':0.9,'home_conceding_rate':0.8,'away_conceding_rate':1.9}


def test_score_distribution_is_coherent_across_markets():
    p=mm.probabilities(F)
    assert abs(p[('1X2','HOME')]+p[('1X2','DRAW')]+p[('1X2','AWAY')]-1)<1e-9
    assert abs(p[('DC','1X')]-(p[('1X2','HOME')]+p[('1X2','DRAW')]))<1e-9
    for line in mm.TOTAL_LINES:assert abs(p[(f'OU_{line:g}','OVER')]+p[(f'OU_{line:g}','UNDER')]-1)<1e-9
    assert p[('OU_0.5','OVER')]>p[('OU_2.5','OVER')]>p[('OU_4.5','OVER')]
    assert p[('1X2','HOME')]>p[('1X2','AWAY')], 'stronger home side'


def test_calibration_keeps_groups_coherent():
    params={'shrink':{'home':{'mean':1.6,'raw_mean':1.5,'weight':.7},'away':{'mean':1.2,'raw_mean':1.5,'weight':.6}},
            'platt':{'1X2|HOME':[1.2,.1],'1X2|DRAW':[.8,-.2],'1X2|AWAY':[1.1,0],'OU_2.5|OVER':[.9,.05],'OU_2.5|UNDER':[1.3,0]}}
    p=mm.probabilities(F,params)
    assert abs(sum(p[('1X2',o)] for o in ('HOME','DRAW','AWAY'))-1)<1e-9
    assert abs(p[('OU_2.5','OVER')]+p[('OU_2.5','UNDER')]-1)<1e-9
    assert abs(p[('DC','12')]-(p[('1X2','HOME')]+p[('1X2','AWAY')]))<1e-9
    assert mm.expected_goals(F,params)!=mm.expected_goals(F), 'shrinkage is applied'


def test_settled_outcomes_match_score():
    s=mm.settled_outcomes(2,1)
    assert s['1X2']=={'HOME':'WON','DRAW':'LOST','AWAY':'LOST'} and s['OU_2.5']['OVER']=='WON' and s['BTTS']['YES']=='WON'
    assert s['ODD_EVEN']['ODD']=='WON' and s['CS']['2-1']=='WON' and s['CS']['1-1']=='LOST' and s['HOME_OU_1.5']['OVER']=='WON'


def synthetic(n,seed=7,signal=True):
    rng=random.Random(seed);rows=[]
    for _ in range(n):
        h,a=rng.uniform(.6,2.8),rng.uniform(.4,2.2)
        f={'home_form':1.5,'away_form':1.5,'home_scoring_rate':h,'away_conceding_rate':h,'away_scoring_rate':a,'home_conceding_rate':a}
        lh,la=(h,a) if signal else (1.5,1.2)
        draw=lambda lam:next(k for k in range(30) if rng.random()<math.exp(-lam)*lam**k/math.factorial(k)/max(1e-12,1-sum(math.exp(-lam)*lam**j/math.factorial(j) for j in range(k))))
        rows.append((f,draw(lh),draw(la)))
    return rows


def test_validation_approves_real_signal_and_rejects_noise():
    results,_,test,params=mm.validate(synthetic(900),0.08)
    assert test>=mm.MIN_HOLDOUT and results['1X2|HOME']['approved'] and results['1X2|AWAY']['approved']
    assert results['1X2|HOME']['skill']>0.05
    assert set(params)=={'shrink','platt'}
    noise,_,_,_=mm.validate(synthetic(900,signal=False),0.08)
    assert not noise['1X2|HOME']['approved'] and 'DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE' in noise['1X2|HOME']['reasons']


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    now=datetime.now(timezone.utc);at=now-timedelta(hours=1)
    approved=lambda brier,skill:{'approved':True,'reasons':[],'holdout':{'brier':brier,'log_loss':.6,'sample_size':378},'baseline':{'brier':brier/(1-skill)},'calibration_error':.02,'skill':skill}
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='Bundesliga',country='Germany'));db.flush()
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Fixture(id='fixture',competition_id='league',home_name='Home',away_name='Away',kickoff_at=now+timedelta(days=1)));db.flush()
        db.add(m.Observation(id='obs',source_id='source',fixture_id='fixture',observed_at=at,source_url='https://p.example/e',content_hash='o'*64,payload={'section':'match_statistics','data':{}}))
        db.add(m.Research(id='dossier',fixture_id='fixture',version=1,status='VERIFIED',sections={},evidence_ids=['obs'],created_at=at))
        db.add(m.Feature(id='feature',research_id='dossier',cutoff_at=at+timedelta(minutes=1),features={'numeric_features':F,'evidence_ids':['obs']}))
        markets={'1X2|HOME':approved(.22,.11),'1X2|DRAW':approved(.18,.006),'1X2|AWAY':approved(.19,.08),'OU_3.5|OVER':approved(.248,.004),'OU_3.5|UNDER':approved(.248,.004),
                 'OU_2.5|OVER':{'approved':False,'reasons':['DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE'],'holdout':{'brier':.229,'sample_size':378},'baseline':{'brier':.228},'calibration_error':.03,'skill':-.001}}
        db.add(m.ModelVersion(id='market',sport_id='sport',name=mm.NAME,version='1',status='ACTIVE',validation={'model_type':mm.MODEL_TYPE,'feature_names':list(FEATURE_NAMES),'markets':markets,'parameters':{},
                              **{k:True for k in mm.REQUIRED}}))
        db.add(m.ModelVersion(id='logit',sport_id='sport',name='Logit',version='1',status='ACTIVE',validation={'feature_names':list(FEATURE_NAMES),'holdout_metrics':{'brier':.222},**{k:True for k in mm.REQUIRED}}))
    yield factory,now
    engine.dispose()


def test_inference_publishes_only_approved_outcomes(store):
    factory,now=store
    with factory.begin() as db:
        report=mm.infer(db,db.get(m.Fixture,'fixture'),now=now)
        keys={(p.market_key,p.outcome_key) for p in db.scalars(select(m.Prediction).where(m.Prediction.model_id=='market'))}
        assert len(report['created'])==5 and ('OU_2.5','OVER') not in keys and ('OU_3.5','OVER') in keys
        p=db.scalar(select(m.Prediction).where(m.Prediction.market_key=='1X2',m.Prediction.outcome_key=='HOME'))
        assert p.details['interval']['lower']<float(p.probability)<p.details['interval']['upper'] and p.details['skill']==.11
    with factory.begin() as db:
        assert len(mm.infer(db,db.get(m.Fixture,'fixture'),now=now)['existing'])==5, 'idempotent'


def test_scanner_uses_one_model_per_market_and_ranks_unpriced_by_skill(store):
    factory,now=store
    from app.modules.market_scanner.service import forecasts,workspace
    from app.modules.prediction.prospective import infer_approved
    with factory.begin() as db:
        fixture=db.get(m.Fixture,'fixture')
        mm.infer(db,fixture,now=now)
        # A logistic home-only forecast with a better Brier must not split the 1X2 market across models.
        db.add(m.Prediction(fixture_id='fixture',feature_id='feature',model_id='logit',market_key='1X2',outcome_key='HOME',probability=.5,predicted_at=now,details={}))
        db.flush()
        chosen=forecasts(db,'fixture',now+timedelta(minutes=1))
        assert {chosen[('1X2',o)][1].id for o in ('HOME','DRAW','AWAY')}=={'market'}
        report=workspace(db,'fixture',now=now)
        assert report['evaluations'][0]['market_key']=='1X2' and report['evaluations'][0]['outcome_key']=='HOME', 'most skilled market, its most likely outcome first'
        from app.modules.markets import catalogue
        ranking=catalogue.fixture_view(db,'fixture',at=now+timedelta(minutes=1))['analysis_ranking']
        assert [(r['definition_id'],r['outcome']) for r in ranking][:1]==[('football.full_time_result_1x2','HOME')]
        assert len({(r['definition_id'],r['line'],r['outcome'] if r['definition_id']=='football.exact_score' else '') for r in ranking})==len(ranking), 'one entry per market/line (exact scores individually)'
        assert report['verdict'].startswith('Model favours'), 'full 1X2 now available'
        assert all(r['decision']=='NO_MARKET_PRICE' for r in report['evaluations'])


def test_logistic_promotion_does_not_retire_market_model(store,monkeypatch):
    factory,now=store
    from app.modules.governance import promotion
    with factory.begin() as db:
        db.add(m.ModelVersion(id='challenger',sport_id='sport',name='Logit',version='2',status='CHALLENGER',validation={}))
    with factory.begin() as db:
        monkeypatch.setattr(promotion,'assess_challenger',lambda artifact:(True,[],{'calibration_error':.01}))
        promotion.promote_model(db,'challenger',actor='test',at=now)
        assert db.get(m.ModelVersion,'market').status=='ACTIVE' and db.get(m.ModelVersion,'logit').status=='RETIRED'
