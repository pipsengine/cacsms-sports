"""Leakage-safe descriptive monitoring; no automatic activation of models."""
from __future__ import annotations
from math import log, sqrt
from typing import Iterable

def score_window(records: Iterable[tuple[float,int]], minimum: int = 30):
    data=list(records)
    if any(not (0 < float(probability) < 1) or outcome not in (0,1) for probability,outcome in data):
        raise ValueError('Invalid probabilities or outcomes')
    n=len(data)
    if n == 0:
        return {'count':0,'status':'NO_DATA','brier':None,'log_loss':None,'calibration_error':None}
    brier=sum((float(p)-y)**2 for p,y in data)/n
    loss=-sum(y*log(float(p))+(1-y)*log(1-float(p)) for p,y in data)/n
    bins=[[] for _ in range(10)]
    for p,y in data:bins[min(int(float(p)*10),9)].append((float(p),y))
    ece=sum(len(b)/n*abs(sum(x for x,_ in b)/len(b)-sum(y for _,y in b)/len(b)) for b in bins if b)
    return {'count':n,'status':'DESCRIPTIVE' if n>=minimum else 'INSUFFICIENT_DATA','brier':round(brier,6),'log_loss':round(loss,6),'calibration_error':round(ece,6)}

def compare_windows(reference, recent, min_count=30, brier_tolerance=0.03):
    old=score_window(reference,min_count)
    new=score_window(recent,min_count)
    if old['status']!='DESCRIPTIVE' or new['status']!='DESCRIPTIVE':
        return {'status':'INSUFFICIENT_DATA','reference':old,'recent':new,'alert':False,'action':'REVIEW_ONLY'}
    delta=round(new['brier']-old['brier'],6)
    return {'status':'DEGRADATION_FLAG' if delta>brier_tolerance else 'NO_DEGRADATION_FLAG',
            'reference':old,'recent':new,'brier_delta':delta,'alert':delta>brier_tolerance,
            'action':'REVIEW_ONLY','note':'Descriptive alert, not causal proof of drift or model approval'}

def challenger_comparison(champion, challenger, min_count=100):
    a=score_window(champion,min_count);b=score_window(challenger,min_count)
    if len(list(champion))!=len(list(challenger)):
        raise ValueError('Matched out-of-sample observations required')
    return {'champion':a,'challenger':b,'status':'REVIEW_REQUIRED' if a['status']=='DESCRIPTIVE' and b['status']=='DESCRIPTIVE' else 'INSUFFICIENT_DATA',
            'automatic_activation':False,'note':'Requires independent chronological evaluation and human governance approval'}
