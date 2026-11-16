"""Prospective monitoring with durable snapshots and incident deduplication."""
from datetime import datetime,timezone
from sqlalchemy import select
from app.db import models as m
from app.modules.learning.routes import model_rows
from engines.learning.monitor import score_window
from app.modules.governance.policy import assess_model
from app.modules.prediction.prospective import REQUIRED_APPROVALS
from app.modules.results.workspace import latest_settlement_rows


def monitoring_status(model,decision,scored):
 """Separate approved-model warm-up from failed monitoring without granting clearance."""
 sample_reasons={'INSUFFICIENT_RECENT_SAMPLE','INSUFFICIENT_REFERENCE_SAMPLE'}
 approved=model.status=='ACTIVE' and isinstance(model.validation,dict) and all(model.validation.get(k) is True for k in REQUIRED_APPROVALS)
 if approved and decision.reasons and set(decision.reasons)<=sample_reasons:
  return 'AWAITING_OUTCOMES' if not scored else 'WARMING_UP'
 return decision.status


def sample_progress(db,model_id,rows,window):
 """Count current-version outcomes and pending forecasts; never use holdout rows as live evidence."""
 forecasts=db.execute(select(m.Prediction,m.Fixture).join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id).where(m.Prediction.model_id==model_id)).all()
 settled={p.id for s,p,r in latest_settlement_rows(db) if p.model_id==model_id}
 pending=[(p,f) for p,f in forecasts if p.id not in settled]
 recent=len(rows[-window:]);reference=len(rows[-2*window:-window])
 return {'required_per_window':window,'required_total':2*window,'scored_outcomes':len(rows),
         'recent_count':recent,'reference_count':reference,'missing_recent':max(0,window-recent),
         'missing_reference':max(0,window-reference),'forecasts':len(forecasts),'pending_forecasts':len(pending),
         'next_pending_fixture_at':min((f.kickoff_at.isoformat() for p,f in pending),default=None),
         'sample_source':'CURRENT_VERSION_LIVE_SETTLEMENTS','samples_ready':recent>=window and reference>=window}

def window_scores(records):
 if not records:return None
 pairs=[(p,y) for _,p,y in records]
 result=score_window(pairs)
 return {'n':len(pairs),'brier':result.get('brier'),'ece':result.get('calibration_error')}

def evaluate_models(db,window=50,model_id=None):
 report=[]
 query=select(m.ModelVersion)
 if model_id is not None:query=query.where(m.ModelVersion.id==model_id)
 for model in db.scalars(query).all():
  rows=model_rows(db,model.id)
  recent=window_scores(rows[-window:]);reference=window_scores(rows[-2*window:-window])
  decision=assess_model(reference,recent,min_samples=window)
  status=monitoring_status(model,decision,len(rows))
  progress=sample_progress(db,model.id,rows,window)
  snapshot=m.ModelGovernanceSnapshot(model_id=model.id,status=status,reasons=list(decision.reasons),reference=reference or {},recent={**(recent or {}),'monitoring_progress':progress})
  db.add(snapshot)
  if any(x in decision.reasons for x in ('BRIER_DEGRADATION','CALIBRATION_DRIFT')):
   marker='MODEL_DRIFT:'+model.id
   existing=db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%')))
   if existing is None:db.add(m.Incident(severity='HIGH',message=marker+' '+','.join(decision.reasons)))
  report.append({'model_id':model.id,'name':model.name,'status':status,'monitoring_ready':decision.status=='MONITORED',
                 'reasons':list(decision.reasons),'recent':recent,'reference':reference,'sample_progress':progress})
 db.add(m.AuditEvent(actor='scheduler',action='governance.evaluate',correlation_id=m.uid(),payload={'models':len(report),'mode':'PAPER'}))
 return report
