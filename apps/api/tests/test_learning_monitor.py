from engines.learning.monitor import score_window,compare_windows,challenger_comparison
import pytest

def test_empty():assert score_window([])['status']=='NO_DATA'
def test_perfect():
    r=score_window([(0.99,1)]*40+[(0.01,0)]*40)
    assert r['brier']<0.001 and r['status']=='DESCRIPTIVE'
def test_bad_probabilities():
    with pytest.raises(ValueError):score_window([(1.2,1)])
def test_drift():
    ref=[(0.9,1)]*50
    recent=[(0.9,0)]*50
    r=compare_windows(ref,recent)
    assert r['alert'] and r['action']=='REVIEW_ONLY'
def test_insufficient():assert not compare_windows([(0.8,1)]*3,[(0.2,0)]*3)['alert']
def test_no_auto_activation():
    r=challenger_comparison([(0.8,1)]*120,[(0.9,1)]*120)
    assert r['automatic_activation'] is False
