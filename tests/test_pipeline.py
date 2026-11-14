import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.pipeline.logic import STAGES,gate,advance,STATUS_COLORS

def test_twelve_ordered_stages():
 assert len(STAGES)==12
 assert [x[0] for x in STAGES]==['discover','acquire','research','analyse','predict','evaluate','qualify','allocate','prepare','verify','monitor','reconcile']
def test_missing_evidence_blocks_downstream():
 rows=[{'stage_key':x[0],'status':'PENDING'} for x in STAGES]
 result=advance(rows,{})
 assert result[0]['status']=='WAITING_FOR_DATA'
 assert all(x['status']=='PENDING' for x in result[1:])
def test_qualification_mandatory_gate():
 status,reason=gate('qualify',{'qualified_decision_ids':['q1'],'all_mandatory_gates_passed':False})
 assert status=='BLOCKED'
def test_paper_only():
 assert gate('prepare',{'verified_paper_ticket_ids':['t1'],'paper_only':False})[0]=='BLOCKED'
def test_missing_provider():
 assert gate('verify',{'verified_booking_code_ids':['b1']})[0]=='WAITING_FOR_DATA'
def test_all_stage_colors():
 assert STATUS_COLORS['VERIFIED']=='green' and STATUS_COLORS['FAILED']=='red'
