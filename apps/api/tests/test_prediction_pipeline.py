import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.modules.prediction.service import fit_challenger,predict_from_artifact,validate_examples,metrics,FEATURE_NAMES
from datetime import datetime,timedelta,timezone
import pytest

def examples(n=120):
    base=datetime(2023,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(n):
        result=base+timedelta(days=i)
        features={k:round(((i*(j+3))%31)/10,2) for j,k in enumerate(FEATURE_NAMES)}
        out.append({'fixture_id':str(i),'feature_cutoff_at':(result-timedelta(days=1)).isoformat(),'result_at':result.isoformat(),'features':features,'outcome':int((i%7)<3)})
    return out

def test_training_holdout_is_chronological():
    artifact=fit_challenger(examples())
    assert artifact['status']=='CHALLENGER'
    assert artifact['activation_allowed'] is False
    assert artifact['holdout_count']==36
    assert artifact['training_result_before']<artifact['holdout_first_result']
    assert 0<=predict_from_artifact(artifact,examples()[0]['features'])<=1

def test_rejects_future_leakage():
    rows=examples();rows[0]['feature_cutoff_at']=rows[0]['result_at']
    with pytest.raises(ValueError,match='cutoff'):fit_challenger(rows)

def test_rejects_duplicate_fixtures():
    rows=examples();rows[1]['fixture_id']=rows[0]['fixture_id']
    with pytest.raises(ValueError,match='duplicate'):fit_challenger(rows)

def test_rejects_missing_features():
    rows=examples();del rows[0]['features']['home_form']
    with pytest.raises(ValueError,match='contract'):fit_challenger(rows)

def test_rejects_small_dataset():
    with pytest.raises(ValueError,match='80'):fit_challenger(examples(40))

def test_metric_correctness():
    assert metrics([1,0],[1,0])['brier']==0
