import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.pipeline.logic import gate

def test_no_evidence_cannot_advance():
 assert gate('discover',{})[0]=='WAITING_FOR_DATA'

def test_booking_requires_real_provider():
 assert gate('verify',{'verified_booking_code_ids':['some-id']})[0]=='WAITING_FOR_DATA'

def test_qualification_requires_hard_gate():
 assert gate('qualify',{'qualified_decision_ids':['id'],'all_mandatory_gates_passed':False})[0]=='BLOCKED'

def test_paper_mode_is_enforced():
 assert gate('prepare',{'verified_paper_ticket_ids':['id'],'paper_only':False})[0]=='BLOCKED'
