"""Leakage-aware binary research model, prospective predictions, and validation.

No model is approved automatically. This module does not manufacture research or odds.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from collections import defaultdict

FEATURE_NAMES=("home_form","away_form","home_scoring_rate","away_scoring_rate","home_conceding_rate","away_conceding_rate")

def sigmoid(z):
    if z >= 0:
        return 1/(1+math.exp(-min(z,700)))
    t=math.exp(max(z,-700));return t/(1+t)

def validate_examples(examples, *, minimum=80):
    if len(examples)<minimum:raise ValueError(f"At least {minimum} independently labeled historical matches required")
    seen=set();out=[]
    for row in examples:
        fid=row.get('fixture_id')
        if not fid or fid in seen:raise ValueError('Missing or duplicate fixture ID')
        seen.add(fid)
        at=datetime.fromisoformat(str(row['feature_cutoff_at']).replace('Z','+00:00'))
        result=datetime.fromisoformat(str(row['result_at']).replace('Z','+00:00'))
        if at.tzinfo is None or result.tzinfo is None or at>=result:raise ValueError('Feature cutoff must precede result and use timezone')
        x=row.get('features',{})
        if set(x)!=set(FEATURE_NAMES):raise ValueError('Incorrect feature contract')
        vals=[float(x[k]) for k in FEATURE_NAMES]
        if any(not math.isfinite(v) or v<0 or v>10 for v in vals):raise ValueError('Invalid feature values')
        y=row.get('outcome')
        if type(y) is not int or y not in (0,1):raise ValueError('Binary outcome required')
        out.append((result,at,fid,vals,y))
    out.sort(key=lambda r:r[0]);return out

def metrics(predictions,labels):
    if not labels:raise ValueError('Empty evaluation')
    eps=1e-12
    return {'brier':round(sum((p-y)**2 for p,y in zip(predictions,labels))/len(labels),6),
            'log_loss':round(-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in zip(predictions,labels))/len(labels),6),
            'sample_size':len(labels)}

def fit_challenger(examples):
    """Chronological 70/30 holdout, train-only standardization, ridge logistic regression.

    Baseline is a train-set constant-rate forecast. Never auto-activate.
    """
    rows=validate_examples(examples)
    split=int(len(rows)*.7)
    train,test=rows[:split],rows[split:]
    if len(test)<24:raise ValueError('Holdout too small')
    if len({r[4] for r in train})<2:raise ValueError('Training requires both outcomes')
    means=[sum(r[3][j] for r in train)/len(train) for j in range(len(FEATURE_NAMES))]
    scales=[max(.01,(sum((r[3][j]-means[j])**2 for r in train)/len(train))**.5) for j in range(len(means))]
    standardized=lambda x:[(v-means[j])/scales[j] for j,v in enumerate(x)]
    w=[0.0]*len(means);bias=0.0
    for epoch in range(800):
        dw=[0.0]*len(w);db=0.0
        for row in train:
            z=standardized(row[3]);error=sigmoid(bias+sum(a*b for a,b in zip(w,z)))-row[4]
            db+=error
            for j in range(len(w)):dw[j]+=error*z[j]
        lr=.14/(1+epoch/150)
        bias-=lr*db/len(train)
        for j in range(len(w)):w[j]-=lr*(dw[j]/len(train)+.03*w[j])
    predicted=[sigmoid(bias+sum(a*b for a,b in zip(w,standardized(r[3])))) for r in test]
    labels=[r[4] for r in test]
    rate=sum(r[4] for r in train)/len(train)
    result=metrics(predicted,labels);baseline=metrics([rate]*len(test),labels)
    # Reliability buckets are descriptive, not an automatic calibration guarantee.
    buckets=[]
    for lower in (0,.2,.4,.6,.8):
        indices=[i for i,p in enumerate(predicted) if lower<=p<(lower+.2 if lower<.8 else 1.000001)]
        if indices:buckets.append({'range':[lower,round(lower+.2,1)],'count':len(indices),'predicted':round(sum(predicted[i] for i in indices)/len(indices),4),'observed':round(sum(labels[i] for i in indices)/len(indices),4)})
    return {'schema_version':'1.0','feature_names':list(FEATURE_NAMES),'coefficients':[round(v,10) for v in w],
            'intercept':round(bias,10),'means':means,'scales':scales,
            'training_count':len(train),'holdout_count':len(test),
            'training_result_before':train[-1][0].isoformat(),
            'holdout_first_result':test[0][0].isoformat(),
            'holdout_metrics':result,'baseline_metrics':baseline,'reliability_bins':buckets,
            'status':'CHALLENGER','activation_allowed':False,
            'note':'Independent prospective validation and model-governance approval required'}

def predict_from_artifact(artifact,features):
    if set(features)!=set(FEATURE_NAMES):raise ValueError('Feature contract mismatch')
    for key in ('means','scales','coefficients'):
        values=artifact.get(key)
        if not isinstance(values,list) or len(values)!=len(FEATURE_NAMES) or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):raise ValueError('Invalid model artifact array: '+key)
    if any(v<=0 for v in artifact['scales']):raise ValueError('Model scales must be positive')
    if type(artifact.get('intercept')) not in (int,float) or not math.isfinite(artifact['intercept']):raise ValueError('Invalid model intercept')
    z=[]
    for i,key in enumerate(FEATURE_NAMES):
        value=float(features[key])
        if not math.isfinite(value) or not 0<=value<=10:raise ValueError('Invalid feature')
        z.append((value-artifact['means'][i])/artifact['scales'][i])
    return sigmoid(artifact['intercept']+sum(w*x for w,x in zip(artifact['coefficients'],z)))

def create_challenger(session,sport_id,name,version,examples):
    from sqlalchemy import select
    from app.db import models as m
    if session.get(m.Sport,sport_id) is None:raise ValueError('Unknown sport')
    if session.scalar(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.name==name,m.ModelVersion.version==version)):
        raise ValueError('Model version already exists')
    artifact=fit_challenger(examples)
    # Approval flags are computed only by governance promotion, never carried in by a challenger.
    for key in ('approved','out_of_sample','calibrated','calibration_verified'):artifact.pop(key,None)
    obj=m.ModelVersion(sport_id=sport_id,name=name,version=version,status='CHALLENGER',validation=artifact)
    session.add(obj);session.flush()
    return {'id':obj.id,'status':obj.status,'validation':artifact}

def preview_model(session,model_id,feature_id):
    from app.db import models as m
    model=session.get(m.ModelVersion,model_id)
    feature=session.get(m.Feature,feature_id)
    if model is None or feature is None:raise ValueError('Unknown model or feature snapshot')
    if model.status!='ACTIVE':raise ValueError('Model is not ACTIVE: challenger predictions cannot be published')
    research=session.get(m.Research,feature.research_id)
    if research is None:raise ValueError('Research dossier missing')
    fixture=session.get(m.Fixture,research.fixture_id)
    if fixture is None or feature.cutoff_at>=fixture.kickoff_at:raise ValueError('Invalid as-of feature cutoff')
    values=feature.features.get('numeric_features',{})
    return {'fixture_id':fixture.id,'model_id':model.id,'feature_id':feature.id,
            'probability':predict_from_artifact(model.validation,values),'status':'PREVIEW_ONLY'}
