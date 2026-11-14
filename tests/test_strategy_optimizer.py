from decimal import Decimal
from app.modules.strategies.optimizer import Candidate,select_tickets

def c(i,fixture=None,odds='2',prob='0.6',decision='QUALIFIED',outcome='home'):
 return Candidate(str(i),str(fixture or i),Decimal(odds),Decimal(prob),'1x2',outcome,'2026-12-01T12:00:00Z',decision)

def test_singles_rejects_unqualified():
 assert len(select_tickets([c(1),c(2,decision='REJECTED')],'singles'))==1

def test_accumulator_requires_distinct_fixtures():
 assert select_tickets([c(1,1),c(2,1)],'accumulator')==[]

def test_draws_require_draw_outcomes_and_leg_count():
 assert len(select_tickets([c(1,outcome='draw'),c(2,outcome='draw'),c(3)],'draws',draw_legs=2))==1

def test_jackpot_never_fabricates_target():
 assert select_tickets([c(1),c(2)],'jackpot')==[]

def test_rollover_filters_odds():
 assert len(select_tickets([c(1,odds='1.5'),c(2,odds='3')],'rollover'))==1

def test_duplicate_signature_rejected():
 assert select_tickets([c(1)],'singles',existing_signatures=['1'])==[]

def test_combined_odds_and_probability_bounds():
 result=select_tickets([c(1),c(2)],'accumulator')
 assert result[0]['combined_odds']=='4'
 assert result[0]['probability_lower_bound']=='0.2'
 assert result[0]['correlation_status']=='UNVERIFIED'
