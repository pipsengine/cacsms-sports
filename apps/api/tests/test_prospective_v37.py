from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.modules.prediction.prospective import eligible

now=datetime.now(timezone.utc)
def record(**kw):return SimpleNamespace(**kw)
def valid():
    fixture=record(id='f',sport_id='s',kickoff_at=now+timedelta(hours=3))
    dossier=record(id='r',fixture_id='f',status='VERIFIED')
    feature=record(research_id='r',cutoff_at=now-timedelta(minutes=2),features={'numeric_features':{k:1.0 for k in ('home_form','away_form','home_scoring_rate','away_scoring_rate','home_conceding_rate','away_conceding_rate')}})
    model=record(sport_id='s',status='ACTIVE',validation={'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True})
    return model,feature,dossier,fixture

def test_approved_prospective_eligible():assert eligible(*valid(),now)[0]
def test_challenger_rejected():
    args=valid();args[0].status='CHALLENGER';assert not eligible(*args,now)[0]
def test_missing_calibration_rejected():
    args=valid();args[0].validation['calibration_verified']=False;assert not eligible(*args,now)[0]
def test_stale_cutoff_rejected():
    args=valid();args[1].cutoff_at=args[3].kickoff_at;assert not eligible(*args,now)[0]
def test_fixture_mismatch_rejected():
    args=valid();args[2].fixture_id='different';assert not eligible(*args,now)[0]
def test_wrong_feature_schema_rejected():
    args=valid();args[1].features={'numeric_features':{'unknown':1}};assert not eligible(*args,now)[0]
