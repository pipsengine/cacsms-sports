from app.modules.pipeline.logic import STAGES,gate,advance

def test_every_stage_requires_evidence():
    for stage,_,_ in STAGES:
        state,reason=gate(stage,{'paper_only':True})
        assert state!='VERIFIED',stage
        assert reason

def test_unverified_acquisition_blocks_downstream():
    rows=[{'stage_key':key,'status':'PENDING'} for key,_,_ in STAGES]
    updated=advance(rows,{'paper_only':True,'fixture_ids':['fixture-1']})
    assert updated[0]['status']=='VERIFIED'
    assert updated[1]['status']=='WAITING_FOR_DATA'
    assert all(row['status']=='PENDING' for row in updated[2:])

def test_client_cannot_claim_qualification_without_persisted_gates():
    state,reason=gate('qualify',{'qualified_decision_ids':['q1']})
    assert state=='BLOCKED'
    assert 'Mandatory' in reason

def test_paper_mode_is_mandatory():
    state,reason=gate('prepare',{'verified_paper_ticket_ids':['ticket1'],'paper_only':False})
    assert state=='BLOCKED'
