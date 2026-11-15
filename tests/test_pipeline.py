import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.pipeline.logic import (STAGES,STAGE_KEYS,STATUS_COLORS,SETTLED,BUSINESS_OUTCOMES,
     run_status,run_outcome,next_stage_key,invalidation_stage,earliest)


def states(**overrides):
 base={key:'PENDING' for key in STAGE_KEYS};base.update(overrides);return base


def test_twelve_ordered_stages():
 assert len(STAGES)==12
 assert list(STAGE_KEYS)==['discover','acquire','research','analyse','predict','evaluate','qualify','allocate','prepare','verify','monitor','reconcile']


def test_business_outcomes_are_settled_not_failures():
 assert BUSINESS_OUTCOMES=={'NO_OPPORTUNITY','INSUFFICIENT_DATA','REJECTED'}
 assert BUSINESS_OUTCOMES<SETTLED and 'FAILED' not in SETTLED and 'BLOCKED' not in SETTLED
 assert STATUS_COLORS['REJECTED']!=STATUS_COLORS['FAILED']


def test_non_qualifying_fixture_completes_after_reconciliation():
 statuses=states(**{k:'VERIFIED' for k in STAGE_KEYS[:6]},qualify='REJECTED',allocate='NOT_APPLICABLE',prepare='NOT_APPLICABLE',
                 verify='NOT_APPLICABLE',monitor='VERIFIED',reconcile='WAITING_FOR_DATA')
 assert run_status(statuses)=='MONITORING'
 assert run_outcome(statuses)=='REJECTED:QUALIFY'
 statuses['reconcile']='VERIFIED'
 assert run_status(statuses)=='COMPLETED'


def test_run_status_precedence():
 assert run_status(states(discover='WAITING_FOR_DATA'))=='WAITING_FOR_DATA'
 assert run_status(states(discover='BLOCKED'))=='BLOCKED'
 assert run_status(states(discover='BLOCKED',acquire='RETRY_SCHEDULED'))=='RETRY_SCHEDULED'
 assert run_status(states(discover='FAILED',acquire='RETRY_SCHEDULED'))=='FAILED'
 assert run_status({k:'VERIFIED' for k in STAGE_KEYS})=='COMPLETED'
 assert run_outcome({k:'VERIFIED' for k in STAGE_KEYS})=='QUALIFIED_PAPER_BETSLIP'


def test_outcomes_divert_to_monitoring():
 assert next_stage_key('research')=='analyse'
 assert next_stage_key('verify')=='monitor'
 assert next_stage_key('qualify','REJECTED')=='monitor'
 assert next_stage_key('monitor')=='reconcile' and next_stage_key('reconcile') is None


def test_changes_invalidate_only_the_affected_stage():
 assert invalidation_stage('Odds')=='evaluate'
 assert invalidation_stage('Observation','market_odds')=='evaluate'
 assert invalidation_stage('Observation','official_result')=='reconcile'
 assert invalidation_stage('Observation','injuries')=='research'
 assert invalidation_stage('ModelVersion')=='predict'
 assert invalidation_stage('Fixture')=='discover'
 assert earliest(['evaluate',None,'research'])=='research'
