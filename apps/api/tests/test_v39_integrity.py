from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.modules.markets.monitoring import inspect_market
from app.modules.strategies.optimizer import PROGRAMMES
from app.modules.strategies.automation import allocate_paper

class Result:
 def __init__(self,rows):self.rows=rows
 def all(self):return self.rows

class FakeDB:
 bind=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
 def __init__(self):self.executed=[]
 def execute(self,statement,params):self.executed.append((str(statement),params))
 def scalars(self,statement):return Result([])
 def scalar(self,statement):return None

def test_allocation_acquires_programme_locks():
 db=FakeDB();result=allocate_paper(db,programme_keys=('singles','draws'))
 assert result['mode']=='PAPER'
 assert len(db.executed)==2
 assert all('pg_advisory_xact_lock' in sql for sql,_ in db.executed)
 assert db.executed[0][1]['key'].endswith('singles')

def test_market_monitor_handles_naive_provider_timestamp():
 now=datetime.now(timezone.utc)
 db=MagicMock()
 db.scalars.return_value.all.return_value=[SimpleNamespace(id='a',bookmaker='B',market_key='1X2',outcome_key='1',observed_at=now.replace(tzinfo=None),decimal_odds=Decimal('2'))]
 result=inspect_market(db,'fixture',at=now)
 assert result['snapshots'][0]['fresh'] is True
 assert result['monitoring_verified'] is False

def test_programme_specific_odds_limits_are_distinct():
 assert PROGRAMMES['jackpot']['max_odds']>PROGRAMMES['accumulator']['max_odds']
 assert PROGRAMMES['rollover']['max_odds']<PROGRAMMES['accumulator']['max_odds']
