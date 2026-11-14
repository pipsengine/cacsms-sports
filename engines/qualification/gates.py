"""Pure mandatory qualification gate. A missing gate always fails closed."""
REQUIRED=('research','model','calibration','odds_freshness','market_mapping','value')
def evaluate(gates:dict)->dict:
 normalized={name:'PASS' if gates.get(name)=='PASS' else 'FAIL' for name in REQUIRED}
 return {'decision':'QUALIFIED' if all(v=='PASS' for v in normalized.values()) else 'REJECTED','gate_results':normalized,'reason_codes':[f'{k.upper()}_FAILED' for k,v in normalized.items() if v!='PASS']}
