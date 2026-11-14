from app.modules.qualification.service import evaluate

def test_missing_gates_fail_closed():
 assert evaluate({})['decision']=='REJECTED'
 assert len(evaluate({})['reason_codes'])==6

def test_failed_gate_cannot_qualify():
 gates={k:'PASS' for k in ('research','model','calibration','odds_freshness','market_mapping','value')}
 gates['research']='FAIL'
 assert evaluate(gates)['decision']=='REJECTED'

def test_only_all_gates_pass():
 gates={k:'PASS' for k in ('research','model','calibration','odds_freshness','market_mapping','value')}
 assert evaluate(gates)['decision']=='QUALIFIED'
