"""Deterministic fail-closed model governance rules."""
from dataclasses import dataclass
@dataclass(frozen=True)
class GovernanceDecision:
 status:str
 reasons:tuple[str,...]

def assess_model(reference:dict|None,recent:dict|None,min_samples:int=50,max_brier_delta:float=0.025,max_ece:float=0.08):
 reasons=[]
 if not recent or int(recent.get('n',0))<min_samples:reasons.append('INSUFFICIENT_RECENT_SAMPLE')
 if not reference or int(reference.get('n',0))<min_samples:reasons.append('INSUFFICIENT_REFERENCE_SAMPLE')
 if recent and recent.get('brier') is None:reasons.append('MISSING_BRIER')
 if recent and recent.get('ece') is None:reasons.append('MISSING_CALIBRATION')
 # A sufficiently sized recent window can expose calibration drift even while
 # the separate reference window is still filling.
 if recent and int(recent.get('n',0))>=min_samples and recent.get('ece') is not None:
  if float(recent['ece'])>max_ece:reasons.append('CALIBRATION_DRIFT')
 if not reasons:
  if float(recent['brier'])-float(reference['brier'])>max_brier_delta:reasons.append('BRIER_DEGRADATION')
 return GovernanceDecision('BLOCKED' if reasons else 'MONITORED',tuple(reasons))
