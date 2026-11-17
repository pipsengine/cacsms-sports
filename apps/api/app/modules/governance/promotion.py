"""Model promotion gate: learning may propose a challenger, only validation can promote it.

The approval flags consumed by inference (approved, out_of_sample, calibrated,
calibration_verified) are computed here from the challenger's server-fitted chronological
holdout. They are never accepted from callers or stored model payloads.
"""
import math,os
from datetime import datetime,timezone
from sqlalchemy import select
from app.db import models as m
from app.modules.prediction.prospective import REQUIRED_APPROVALS
from app.modules.prediction.service import FEATURE_NAMES


def max_calibration_error():
 try:return float(os.getenv('SPORTS_MODEL_MAX_ECE','0.08'))
 except ValueError:return 0.08


def calibration_error(bins):
 total=sum(int(b.get('count',0)) for b in bins)
 if not total:return None
 return sum(int(b['count'])*abs(float(b['predicted'])-float(b['observed'])) for b in bins)/total


def assess_challenger(artifact):
 """Return (passed, reasons, evidence) for an out-of-sample promotion decision."""
 reasons=[];evidence={}
 if not isinstance(artifact,dict):return False,['ARTIFACT_MISSING'],evidence
 for key in ('coefficients','means','scales'):
  values=artifact.get(key)
  if not isinstance(values,list) or len(values)!=len(FEATURE_NAMES) or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):reasons.append('ARTIFACT_INVALID_'+key.upper())
 if list(artifact.get('feature_names') or [])!=list(FEATURE_NAMES):reasons.append('FEATURE_CONTRACT_MISMATCH')
 holdout=artifact.get('holdout_metrics') or {};baseline=artifact.get('baseline_metrics') or {}
 size=int(holdout.get('sample_size') or 0)
 evidence.update(holdout_sample_size=size,holdout=holdout,baseline=baseline)
 if size<24:reasons.append('HOLDOUT_TOO_SMALL')
 try:
  chronological=datetime.fromisoformat(str(artifact['training_result_before']))<datetime.fromisoformat(str(artifact['holdout_first_result']))
 except (KeyError,ValueError,TypeError):chronological=False
 if not chronological:reasons.append('HOLDOUT_NOT_OUT_OF_SAMPLE')
 try:
  beats=float(holdout['brier'])<float(baseline['brier']) and float(holdout['log_loss'])<float(baseline['log_loss'])
 except (KeyError,ValueError,TypeError):beats=False
 if not beats:reasons.append('DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE')
 ece=calibration_error(artifact.get('reliability_bins') or [])
 evidence.update(calibration_error=ece,max_calibration_error=max_calibration_error())
 if ece is None:reasons.append('CALIBRATION_UNMEASURED')
 elif ece>max_calibration_error():reasons.append('CALIBRATION_ERROR_TOO_HIGH')
 return not reasons,reasons,evidence


def promote_model(db,model_id,*,actor,at=None):
 at=at or datetime.now(timezone.utc)
 model=db.scalar(select(m.ModelVersion).where(m.ModelVersion.id==model_id).with_for_update())
 if model is None:raise LookupError('Unknown model')
 if model.status!='CHALLENGER':raise ValueError('Only CHALLENGER models can be promoted')
 artifact={k:v for k,v in (model.validation or {}).items() if k not in REQUIRED_APPROVALS}
 passed,reasons,evidence=assess_challenger(artifact)
 if not passed:
  db.add(m.ModelGovernanceSnapshot(model_id=model.id,status='PROMOTION_REJECTED',reasons=reasons,reference=evidence.get('baseline') or {},recent={**(evidence.get('holdout') or {}),'calibration_error':evidence.get('calibration_error'),'dataset':'CHRONOLOGICAL_HOLDOUT','evaluation_window':{'start':artifact.get('holdout_first_result'),'end':artifact.get('holdout_last_result')},'approval_status':'APPROVED' if passed else 'REJECTED'}))
  db.add(m.AuditEvent(actor=actor,action='model.promotion_rejected',correlation_id=model.id,payload={'reasons':reasons,'evidence':evidence}))
  return {'model_id':model.id,'status':model.status,'promoted':False,'reasons':reasons,'evidence':evidence}
 retired=[]
 for active in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==model.sport_id,m.ModelVersion.status=='ACTIVE',m.ModelVersion.id!=model.id)):
  from app.modules.prediction.market_model import model_type
  if model_type(active)!=model_type(model):continue  # a logistic promotion never retires the market model
  active.status='RETIRED';retired.append(active.id)
 # The training artifact's own CHALLENGER/activation_allowed markers describe it before this gate; replace them so a
 # promoted record cannot read as both approved and not-allowed.
 model.validation={**artifact,'status':'ACTIVE','activation_allowed':True,'note':'Promoted by the out-of-sample validation gate',
                   'approved':True,'out_of_sample':True,'calibrated':True,'calibration_verified':True,
                   'calibration_error':round(evidence['calibration_error'],6),
                   'promotion':{'promoted_at':at.isoformat(),'actor':actor,'evidence':evidence,'retired_model_ids':retired}}
 model.status='ACTIVE'
 db.add(m.ModelGovernanceSnapshot(model_id=model.id,status='PROMOTED',reasons=[],reference=evidence.get('baseline') or {},recent={**(evidence.get('holdout') or {}),'calibration_error':evidence.get('calibration_error'),'dataset':'CHRONOLOGICAL_HOLDOUT','evaluation_window':{'start':artifact.get('holdout_first_result'),'end':artifact.get('holdout_last_result')},'approval_status':'APPROVED' if passed else 'REJECTED'}))
 db.add(m.AuditEvent(actor=actor,action='model.promoted',correlation_id=model.id,payload={'evidence':evidence,'retired_model_ids':retired}))
 return {'model_id':model.id,'status':model.status,'promoted':True,'reasons':[],'evidence':evidence,'retired_model_ids':retired}
