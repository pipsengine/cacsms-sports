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
 def scalar(self,query):return None  # This unit scenario has no competing quotes; SQL conflicts have integration tests.

def fixture_data(gates=None,odds_age=5,decision='QUALIFIED'):
 t=datetime.now(timezone.utc);ids=['q','p','o','f'];gates=gates or {x:'PASS' for x in ('research','model','calibration','odds_freshness','market_mapping','value')}
 entities={(m.Qualification,'q'):SimpleNamespace(id='q',decision=decision,gates=gates,prediction_id='p',odds_id='o'),(m.Prediction,'p'):SimpleNamespace(id='p',fixture_id='f',market_key='1X2',outcome_key='HOME'),(m.Odds,'o'):SimpleNamespace(id='o',fixture_id='f',market_key='1X2',outcome_key='HOME',decimal_odds=Decimal('1.75'),observed_at=t-timedelta(minutes=odds_age)),(m.Fixture,'f'):SimpleNamespace(id='f',home_name='Home',away_name='Away',kickoff_at=t+timedelta(days=1))}
 entities[(m.Prediction,'p')].model_id='model'
 entities[(m.Odds,'o')].bookmaker='Book'
 stamp=entities[(m.Odds,'o')].observed_at
 entities[(m.ModelVersion,'model')]=SimpleNamespace(status='ACTIVE',validation={key:True for key in ('approved','out_of_sample','calibrated','calibration_verified')})
 entities[(m.Source,'source')]=SimpleNamespace(id='source',name='Controlled provider',permission='AUTHORIZED',enabled=True)
 entities[(m.MarketEvidence,'o')]=SimpleNamespace(source_id='source',observation_id='observation')
 entities[(m.Observation,'observation')]=SimpleNamespace(id='observation',source_id='source',fixture_id='f',observed_at=stamp,source_url='https://provider.example/prices',payload={'section':'market_odds','data':{'prices':[{'bookmaker':'Book','market_key':'1X2','outcome_key':'HOME','decimal_odds':1.75,'observed_at':stamp.isoformat()}]}})
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


def test_model_approval_revoked_after_qualification_is_rejected():
 db,t=fixture_data();db.entities[(m.ModelVersion,'model')].validation['approved']=False
 with pytest.raises(TicketRejected,match='MODEL_NOT_ACTIVE_APPROVED'):validate_leg(db,'q',t)
