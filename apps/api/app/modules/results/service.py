"""Versioned official results and deterministic, auditable forecast settlement."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from math import log
from typing import Any

class ResultValidationError(ValueError): pass

def validate_result_payload(payload:dict[str,Any])->dict[str,Any]:
    if not isinstance(payload,dict):raise ResultValidationError('Result must be an object')
    if payload.get('status')!='FINAL':raise ResultValidationError('Only FINAL results can settle predictions')
    if not isinstance(payload.get('outcomes'),dict) or not payload['outcomes']:
        raise ResultValidationError('Final result requires outcomes map')
    normalized={}
    for market, selections in payload['outcomes'].items():
        if not isinstance(market,str) or not market.strip() or not isinstance(selections,dict) or not selections:
            raise ResultValidationError('Invalid market outcomes')
        normalized[market]={}
        for selection,result in selections.items():
            if not isinstance(selection,str) or not selection.strip() or result not in ('WON','LOST','VOID','PUSH'):
                raise ResultValidationError('Outcomes must be WON, LOST, VOID or PUSH')
            normalized[market][selection]=result
    clean = {'status':'FINAL','outcomes':normalized}
    if 'score' in payload:
        score = payload['score']
        if not isinstance(score, dict) or any(type(score.get(k)) is not int or score[k] < 0 for k in ('home', 'away')):
            raise ResultValidationError('Score requires nonnegative integer home and away goals')
        clean['score'] = {k: score[k] for k in ('home', 'away')}
    return clean

def settle_outcome(payload:dict[str,Any],market_key:str,outcome_key:str)->str:
    normalized=validate_result_payload(payload)
    return normalized['outcomes'].get(market_key,{}).get(outcome_key,'UNRESOLVED')

def binary_scores(probability:float,outcome:str)->dict[str,float]|None:
    if outcome not in ('WON','LOST'):return None
    p=float(probability)
    if not 0<p<1:raise ResultValidationError('Probability must be strictly between 0 and 1')
    actual=1 if outcome=='WON' else 0
    return {'brier':round((p-actual)**2,8),'log_loss':round(-log(p if actual else 1-p),8),'actual':actual}

def performance_summary(records:list[tuple[float,str]])->dict[str,Any]:
    scores=[binary_scores(probability,outcome) for probability,outcome in records]
    valid=[s for s in scores if s is not None]
    n=len(valid)
    return {'settled_forecasts':n,'unresolved_or_void':len(records)-n,
            'wins':sum(s['actual'] for s in valid),
            'hit_rate':round(sum(s['actual'] for s in valid)/n,6) if n else None,
            'brier':round(sum(s['brier'] for s in valid)/n,6) if n else None,
            'log_loss':round(sum(s['log_loss'] for s in valid)/n,6) if n else None,
            'status':'INSUFFICIENT_DATA' if n<100 else 'DESCRIPTIVE_ONLY',
            'note':'Scores describe forecasts; they do not prove a profitable betting edge.'}
