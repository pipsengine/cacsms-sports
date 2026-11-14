import sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.tickets.service import validate_leg,prepare_paper_ticket,TicketRejected
from app.db import models as m

class DB:
 def __init__(self,entities):self.entities=entities
 def get(self,model,key):return self.entities.get((model,key))

def fixture_data(gates=None,odds_age=5,decision='QUALIFIED'):
 t=datetime.now(timezone.utc);ids=['q','p','o','f'];gates=gates or {x:'PASS' for x in ('research','model','calibration','odds_freshness','market_mapping','value')}
 entities={(m.Qualification,'q'):SimpleNamespace(id='q',decision=decision,gates=gates,prediction_id='p',odds_id='o'),(m.Prediction,'p'):SimpleNamespace(id='p',fixture_id='f',market_key='1X2',outcome_key='HOME'),(m.Odds,'o'):SimpleNamespace(id='o',fixture_id='f',market_key='1X2',outcome_key='HOME',decimal_odds=Decimal('1.75'),observed_at=t-timedelta(minutes=odds_age)),(m.Fixture,'f'):SimpleNamespace(id='f',home_name='Home',away_name='Away',kickoff_at=t+timedelta(days=1))}
 return DB(entities),t

def test_valid_leg():
 db,t=fixture_data();assert validate_leg(db,'q',t)['odds']=='1.75'

def test_gate_failure_rejected():
 db,t=fixture_data(gates={'research':'PASS'});
 with pytest.raises(TicketRejected,match='QUALIFICATION_GATES_INCOMPLETE'):validate_leg(db,'q',t)

def test_unqualified_rejected():
 db,t=fixture_data(decision='REJECTED')
 with pytest.raises(TicketRejected,match='NOT_QUALIFIED'):validate_leg(db,'q',t)

def test_stale_price_rejected():
 db,t=fixture_data(odds_age=18)
 with pytest.raises(TicketRejected,match='ODDS_NOT_FRESH'):validate_leg(db,'q',t)

def test_wrong_market_rejected():
 db,t=fixture_data();db.entities[(m.Odds,'o')].market_key='TOTAL'
 with pytest.raises(TicketRejected,match='MARKET_MAPPING_MISMATCH'):validate_leg(db,'q',t)
