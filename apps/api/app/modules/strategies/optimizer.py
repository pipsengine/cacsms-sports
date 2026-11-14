"""Pure, deterministic, fail-closed paper ticket optimizer. No bookmaker requests."""
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from math import prod
from itertools import islice

PROGRAMMES={
 'accumulator':{'min_legs':2,'max_legs':12,'max_odds':Decimal('1000'),'daily_cap':5},
 'singles':{'min_legs':1,'max_legs':1,'max_odds':Decimal('1000'),'daily_cap':25},
 'jackpot':{'min_legs':2,'max_legs':30,'max_odds':Decimal('100000000'),'daily_cap':5},
 'draws':{'min_legs':2,'max_legs':10,'max_odds':Decimal('1000'),'daily_cap':5},
 'rollover':{'min_legs':1,'max_legs':1,'max_odds':Decimal('2.10'),'daily_cap':1},
}

@dataclass(frozen=True)
class Candidate:
 qualification_id:str
 fixture_id:str
 odds:Decimal
 probability:Decimal
 market_key:str
 outcome_key:str
 kickoff_at:str
 decision:str='QUALIFIED'


def select_tickets(candidates,programme,limit=5,draw_legs=None,existing_signatures=()):
 if programme not in PROGRAMMES:raise ValueError('Unknown programme')
 if limit<1 or limit>100:raise ValueError('Invalid limit')
 cfg=PROGRAMMES[programme];limit=min(limit,cfg['daily_cap'])
 if programme=='draws' and draw_legs not in (2,5,8,10):raise ValueError('Draw legs must be 2, 5, 8 or 10')
 valid=[];seen=set()
 for c in candidates:
  if c.decision!='QUALIFIED':continue
  if not (Decimal('1')<c.odds and Decimal('0')<c.probability<Decimal('1')):continue
  if c.qualification_id in seen:continue
  seen.add(c.qualification_id);valid.append(c)
 valid.sort(key=lambda x:(-(x.probability*x.odds-1),x.kickoff_at,x.qualification_id))
 if programme=='rollover':valid=[c for c in valid if Decimal('1.45')<=c.odds<=Decimal('2.10')]
 if programme=='draws':valid=[c for c in valid if 'draw' in c.outcome_key.lower() or c.outcome_key.lower()=='x']
 sizes=[draw_legs] if programme=='draws' else ([1] if programme in ('singles','rollover') else list(range(min(cfg['max_legs'],len(valid)),cfg['min_legs']-1,-1)))
 result=[];signatures=set(existing_signatures)
 # Bounded candidate pool to prevent combinatorial blowups.
 for size in sizes:
  for group in islice(combinations(valid[:20],size),10000):
   if len({c.fixture_id for c in group})!=size:continue
   signature='|'.join(sorted(c.qualification_id for c in group))
   if signature in signatures:continue
   combined=prod((c.odds for c in group),start=Decimal('1'))
   if combined>cfg['max_odds']:continue
   if programme=='jackpot' and combined*Decimal('100')<Decimal('200000000'):continue
   if programme=='rollover' and not (Decimal('1.45')<=combined<=Decimal('2.10')):continue
   # Independence is NOT assumed for combined win probability; bound only.
   upper=min(c.probability for c in group)
   lower=max(Decimal('0'),sum((c.probability for c in group),Decimal('0'))-Decimal(size-1))
   result.append({'signature':signature,'programme':programme,'qualification_ids':[c.qualification_id for c in group], 'combined_odds':str(combined),'probability_lower_bound':str(lower),'probability_upper_bound':str(upper),'correlation_status':'UNVERIFIED' if size>1 else 'NOT_APPLICABLE','mode':'PAPER','status':'PAPER_DRAFT'})
   signatures.add(signature)
   if len(result)>=limit:return result
 return result
