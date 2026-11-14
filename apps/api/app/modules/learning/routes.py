"""Read-only, latest-correction-aware prospective model monitoring."""
from fastapi import APIRouter,HTTPException
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db import models as m
from engines.learning.monitor import score_window,compare_windows
router=APIRouter(prefix='/api/v1/sports',tags=['Model monitoring'])

def model_rows(db,model_id):
    rows=db.execute(select(m.Prediction,m.Settlement,m.Result).join(m.Settlement,m.Settlement.prediction_id==m.Prediction.id).join(m.Result,m.Result.id==m.Settlement.result_id).where(m.Prediction.model_id==model_id)).all()
    latest={}
    for pred,settlement,result in rows:
        if pred.id not in latest or result.version>latest[pred.id][2].version:
            latest[pred.id]=(pred,settlement,result)
    return sorted([(p.predicted_at,float(p.probability),1 if s.outcome=='WON' else 0) for p,s,r in latest.values() if s.outcome in ('WON','LOST')],key=lambda x:x[0])

@router.get('/models/monitoring/summary')
def monitoring_summary():
    with SessionLocal() as db:
        models=db.scalars(select(m.ModelVersion)).all()
        return {'mode':'PAPER','models':[{'id':x.id,'name':x.name,'version':x.version,'status':x.status} for x in models],
                'note':'No models activated or retrained by monitoring endpoint'}

@router.get('/models/{model_id}/monitoring')
def monitoring(model_id:str,window:int=50):
    if not 10<=window<=1000:raise HTTPException(422,'window must be 10..1000')
    with SessionLocal() as db:
        model=db.get(m.ModelVersion,model_id)
        if model is None:raise HTTPException(404,'Unknown model')
        records=model_rows(db,model_id)
        recent=[(p,y) for _,p,y in records[-window:]]
        reference=[(p,y) for _,p,y in records[-2*window:-window]]
        result=compare_windows(reference,recent,min_count=max(30,window//2))
        return {'model_id':model_id,'model_status':model.status,'total_settled':len(records),
                'mode':'PAPER','monitoring':result,'automatic_activation':False}

@router.get('/models/monitoring/summary')
def monitoring_summary():
    with SessionLocal() as db:
        models=db.scalars(select(m.ModelVersion)).all()
        return {'mode':'PAPER','models':[{'id':x.id,'name':x.name,'version':x.version,'status':x.status} for x in models],
                'note':'No models activated or retrained by monitoring endpoint'}
