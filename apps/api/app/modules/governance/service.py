"""Prospective monitoring with durable snapshots and incident deduplication."""
from datetime import datetime,timezone
from sqlalchemy import select
from app.db import models as m
from app.modules.learning.routes import model_rows
from engines.learning.monitor import score_window
from app.modules.governance.policy import assess_model

def window_scores(records):
 if not records:return None
 pairs=[(p,y) for _,p,y in records]
 result=score_window(pairs)
 return {'n':len(pairs),'brier':result.get('brier'),'ece':result.get('calibration_error')}

def evaluate_models(db,window=50):
 report=[]
 for model in db.scalars(select(m.ModelVersion)).all():
  rows=model_rows(db,model.id)
  recent=window_scores(rows[-window:]);reference=window_scores(rows[-2*window:-window])
  decision=assess_model(reference,recent,min_samples=window)
  snapshot=m.ModelGovernanceSnapshot(model_id=model.id,status=decision.status,reasons=list(decision.reasons),reference=reference or {},recent=recent or {})
  db.add(snapshot)
  if any(x in decision.reasons for x in ('BRIER_DEGRADATION','CALIBRATION_DRIFT')):
   marker='MODEL_DRIFT:'+model.id
   existing=db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%')))
   if existing is None:db.add(m.Incident(severity='HIGH',message=marker+' '+','.join(decision.reasons)))
  report.append({'model_id':model.id,'name':model.name,'status':decision.status,'reasons':list(decision.reasons),'recent':recent,'reference':reference})
 db.add(m.AuditEvent(actor='scheduler',action='governance.evaluate',correlation_id=m.uid(),payload={'models':len(report),'mode':'PAPER'}))
 return report
