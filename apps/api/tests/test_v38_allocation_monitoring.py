from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace
from app.modules.markets.monitoring import inspect_market
from app.modules.strategies.optimizer import Candidate,select_tickets
from app.modules.results.service import validate_result_payload
from app.modules.acquisition.service import ALLOWED_SECTIONS

class FakeScalars:
    def __init__(self,rows):self.rows=rows
    def all(self):return self.rows
class FakeDB:
    def __init__(self,rows):self.rows=rows
    def scalars(self,_):return FakeScalars(self.rows)

def test_market_change_and_stale_detection():
    now=datetime.now(timezone.utc)
    rows=[SimpleNamespace(id='new',bookmaker='B',market_key='1X2',outcome_key='1',observed_at=now,decimal_odds=Decimal('1.9')),
          SimpleNamespace(id='old',bookmaker='B',market_key='1X2',outcome_key='1',observed_at=now-timedelta(minutes=3),decimal_odds=Decimal('1.8'))]
    report=inspect_market(FakeDB(rows),'fixture',at=now)
    assert report['alerts'][0]['reason']=='PRICE_CHANGED'
    assert report['monitoring_verified'] is False
    assert report['snapshots'][0]['delta']=='0.1'

def test_market_stale_does_not_verify():
    now=datetime.now(timezone.utc)
    row=SimpleNamespace(id='old',bookmaker='B',market_key='1X2',outcome_key='1',observed_at=now-timedelta(hours=1),decimal_odds=Decimal('1.9'))
    report=inspect_market(FakeDB([row]),'fixture',at=now)
    assert report['alerts'][0]['reason']=='STALE_PRICE'
    assert report['monitoring_verified'] is False

def test_ticket_optimizer_rejects_same_fixture_multileg():
    rows=[Candidate('a','f1',Decimal('2'),Decimal('.6'),'1X2','home','2026-12-01'),Candidate('b','f1',Decimal('2'),Decimal('.6'),'1X2','away','2026-12-01')]
    assert select_tickets(rows,'accumulator')==[]

def test_official_results_feed_section_and_validation():
    assert 'official_result' in ALLOWED_SECTIONS
    assert validate_result_payload({'status':'FINAL','outcomes':{'1X2':{'home':'WON'}}})['status']=='FINAL'
