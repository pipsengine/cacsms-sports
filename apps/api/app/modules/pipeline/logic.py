"""Fail-closed 12-stage evidence pipeline. No external wagers or synthetic fixtures."""
from datetime import datetime,timezone
from typing import Any
STAGES=(
 ('discover','Discover','fixtures'),('acquire','Acquire','observations'),
 ('research','Research','dossiers'),('analyse','Analyse','features'),
 ('predict','Predict','predictions'),('evaluate','Evaluate','odds'),
 ('qualify','Qualify','qualification'),('allocate','Allocate','strategy'),
 ('prepare','Prepare','ticket'),('verify','Verify','booking_code'),
 ('monitor','Monitor','monitoring'),('reconcile','Reconcile','settlement'))
STATUS_COLORS={'PENDING':'slate','RUNNING':'blue','COMPLETED':'green','VERIFIED':'green','WAITING_FOR_DATA':'amber','RETRY_SCHEDULED':'amber','BLOCKED':'red','FAILED':'red','REJECTED':'red','EXPIRED':'gray'}
TERMINAL={'BLOCKED','FAILED','REJECTED','EXPIRED'}

def utcnow():return datetime.now(timezone.utc)
def gate(stage:str, context:dict[str,Any]):
 """Require explicit evidence for every stage; never infer success from prior status."""
 if stage not in {s[0] for s in STAGES}:raise ValueError('Unknown stage')
 if stage=='verify' and context.get('paper_only') is not True:
  return 'WAITING_FOR_DATA','Verified paper betslip evidence required'
 if stage=='reconcile' and not context.get('official_result_final'):
  return 'WAITING_FOR_DATA','Final official result not available'
 required={
  'discover':('fixture_ids',), 'acquire':('authorized_source_ids','observation_ids'),
  'research':('verified_dossier_ids',), 'analyse':('validated_feature_ids',),
  'predict':('approved_model_ids','prediction_ids'),
  'evaluate':('fresh_odds_ids','matching_market_ids'),
  'qualify':('qualified_decision_ids',), 'allocate':('programme_allocation_ids',),
  'prepare':('verified_paper_ticket_ids',), 'verify':('verified_betslip_ids','paper_verification_ids'),
  'monitor':('monitoring_evidence_ids',), 'reconcile':('official_result_ids','settlement_ids')}
 for key in required[stage]:
  value=context.get(key)
  if not isinstance(value,list) or not value or not all(isinstance(x,str) and x.strip() for x in value):
   return 'WAITING_FOR_DATA',f'Missing independently verified evidence: {key}'
 if stage=='qualify' and context.get('all_mandatory_gates_passed') is not True:
  return 'BLOCKED','Mandatory qualification gates have not all passed'
 if stage=='prepare' and context.get('paper_only') is not True:
  return 'BLOCKED','Only paper ticket preparation is allowed'
 return 'VERIFIED',None

def advance(stage_rows:list[dict], context:dict[str,Any]):
 """Deterministic stage advancement, blocking downstream stages on any unmet gate."""
 result=[]; blocked=False
 for item in stage_rows:
  stage=item['stage_key']; status=item.get('status','PENDING')
  if blocked:
   result.append({**item,'status':'PENDING','error':'Upstream stage not verified'});continue
  if status=='VERIFIED':result.append(item);continue
  if status in TERMINAL:
   blocked=True;result.append(item);continue
  state,error=gate(stage,context)
  result.append({**item,'status':state,'error':error})
  if state!='VERIFIED':blocked=True
 return result
