from engines.qualification.gates import evaluate

def test_missing_gates_reject():assert evaluate({})['decision']=='REJECTED'
def test_partial_reject():assert evaluate({'research':'PASS'})['decision']=='REJECTED'
def test_all_gates_pass():
 gates={k:'PASS' for k in ('research','model','calibration','odds_freshness','market_mapping','value')}
 assert evaluate(gates)['decision']=='QUALIFIED'
