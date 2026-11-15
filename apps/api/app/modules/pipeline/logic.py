"""Pure rules for the twelve-stage PAPER pipeline: ordering, outcomes, roll-up and invalidation."""
from datetime import datetime,timezone

STAGES=(
 ('discover','Discover','fixtures'),('acquire','Acquire','observations'),
 ('research','Research','dossiers'),('analyse','Analyse','features'),
 ('predict','Predict','predictions'),('evaluate','Evaluate','odds'),
 ('qualify','Qualify','qualification'),('allocate','Allocate','strategy'),
 ('prepare','Prepare','ticket'),('verify','Verify','paper_betslip'),
 ('monitor','Monitor','monitoring'),('reconcile','Reconcile','settlement'))
STAGE_KEYS=tuple(key for key,_,_ in STAGES)
# Dependency chain: each stage consumes the validated output of the one before it.
CHAIN=STAGE_KEYS[:10]
# Stages that only make sense before kickoff; after kickoff their chain is frozen.
PRE_MATCH=STAGE_KEYS[2:10]
# Monitor and reconcile run concurrently with, and independently of, the chain.
INDEPENDENT=('monitor','reconcile')

# Valid terminal business outcomes: not technical failures.
BUSINESS_OUTCOMES=frozenset({'NO_OPPORTUNITY','INSUFFICIENT_DATA','REJECTED'})
# Stage states that count as settled: a validated output or an explicit terminal outcome.
SETTLED=frozenset({'VERIFIED','NOT_APPLICABLE',*BUSINESS_OUTCOMES})
STATUS_COLORS={'PENDING':'slate','RUNNING':'blue','COMPLETED':'green','VERIFIED':'green','MONITORING':'green',
               'WAITING_FOR_DATA':'amber','RETRY_SCHEDULED':'amber','BLOCKED':'red','FAILED':'red',
               'NO_OPPORTUNITY':'violet','INSUFFICIENT_DATA':'violet','REJECTED':'violet','NOT_APPLICABLE':'gray','EXPIRED':'gray'}


def utcnow():return datetime.now(timezone.utc)


def next_stage_key(key,status='VERIFIED'):
 """The stage that consumes this stage's output; business outcomes divert to monitoring."""
 if key in INDEPENDENT:return 'reconcile' if key=='monitor' else None
 if status in BUSINESS_OUTCOMES or status=='NOT_APPLICABLE':return 'monitor'
 index=STAGE_KEYS.index(key)
 return STAGE_KEYS[index+1] if index+1<len(CHAIN) else 'monitor'


def earliest(keys):
 keys=[key for key in keys if key in STAGE_KEYS]
 return min(keys,key=STAGE_KEYS.index) if keys else None


def run_status(statuses:dict)->str:
 """Roll stage states up to a run state. Business outcomes are completion, not failure."""
 values=[statuses.get(key,'PENDING') for key in STAGE_KEYS]
 if 'FAILED' in values:return 'FAILED'
 if all(value in SETTLED for value in values):return 'COMPLETED'
 if 'RETRY_SCHEDULED' in values:return 'RETRY_SCHEDULED'
 if 'BLOCKED' in values:return 'BLOCKED'
 if all(statuses.get(key) in SETTLED for key in CHAIN):return 'MONITORING'
 return 'WAITING_FOR_DATA'


def run_outcome(statuses:dict):
 """Business result of the betting path once the chain has settled."""
 if not all(statuses.get(key) in SETTLED for key in CHAIN):return None
 if statuses.get('verify')=='VERIFIED':return 'QUALIFIED_PAPER_BETSLIP'
 for key in CHAIN:
  if statuses.get(key) in BUSINESS_OUTCOMES:return statuses[key]+':'+key.upper()
 return None


# Earliest stage whose output depends on a changed entity; downstream stages are
# re-run only if that stage's output version actually changes.
ENTITY_STAGE={'Fixture':'discover','Source':'discover','Odds':'evaluate','ModelVersion':'predict',
              'Research':'research','Feature':'analyse','Qualification':'qualify','Ticket':'verify',
              'Betslip':'verify','TicketVerification':'verify','Result':'reconcile'}
SECTION_STAGE={'market_odds':'evaluate','official_result':'reconcile'}


def invalidation_stage(entity:str,section:str|None=None):
 if entity=='Observation':return SECTION_STAGE.get(section,'research')
 return ENTITY_STAGE.get(entity)
