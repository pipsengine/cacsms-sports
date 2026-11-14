"""Non-bypassable gate evaluation. The only qualified decision constructor."""
REQUIRED=('research','model','calibration','odds_freshness','market_mapping','value')
def evaluate(gates):
    reasons=[f'{key.upper()}_{"MISSING" if key not in gates else "FAILED"}' for key in REQUIRED if gates.get(key)!='PASS']
    return {'decision':'QUALIFIED' if not reasons else 'REJECTED','reason_codes':reasons,'gates':{k:gates.get(k,'MISSING') for k in REQUIRED}}
