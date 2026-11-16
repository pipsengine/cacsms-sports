"""Operator documentation of the canonical runner, not a second execution engine."""
from app.modules.pipeline.logic import STAGES,CHAIN

INPUTS={
 'discover':['canonical fixture','authorized source provenance'],
 'acquire':['discovered fixture','permitted source feeds'],
 'research':['authorized observations','section evidence references'],
 'analyse':['verified research dossier','pre-match cutoff'],
 'predict':['feature snapshot','approved active calibrated model'],
 'evaluate':['stored forecasts','fresh source-backed bookmaker prices','fixture context'],
 'qualify':['forecast and market identities','mandatory qualification gates'],
 'allocate':['qualified decisions','programme policies','exposure allocation'],
 'prepare':['programme allocations','canonical qualification IDs'],
 'verify':['prepared paper tickets','current odds','market-risk proof'],
 'monitor':['fixture state','recorded stage receipts','health and price changes'],
 'reconcile':['verified final result versions','stored predictions','settlement records']}
RULES={
 'discover':['valid fixture identity','authorized provenance'],
 'acquire':['source permission enabled','durable acquisition evidence'],
 'research':['section-specific evidence links','pre-match evidence cutoff','independent review or configured corroboration'],
 'analyse':['validated dossier','as-of feature integrity'],
 'predict':['active approved model','calibration approval','prospective feature cutoff'],
 'evaluate':['fresh market','source-backed price','consistent bookmaker and market identity'],
 'qualify':['research gate','model and calibration gates','market mapping','fresh odds','value and market-risk gates'],
 'allocate':['eligible programme','distinct fixture selections','odds and exposure limits'],
 'prepare':['canonical qualified legs','fresh prices and future kickoff','programme limits','paper-only preparation'],
 'verify':['ticket/betslip identity and price consistency','market-risk proof','expiring paper verification receipt'],
 'monitor':['record actual operational state','invalidate changed inputs only','independent of pre-match chain'],
 'reconcile':['verified latest result correction','versioned settlement','independent of pre-match chain']}


def definitions():
    return [dict(key=key,name=name,position=i+1,inputs=INPUTS[key],validation_rules=RULES[key],expected_output=evidence,
                 dependencies=[CHAIN[i-1]] if key in CHAIN and i else [],dependency_policy='INDEPENDENT' if key not in CHAIN else 'VALIDATED_UPSTREAM',
                 sla_ms=None,outcome='Explicit terminal business outcomes divert to monitoring; only validated persisted output proceeds down the pre-match chain.') for i,(key,name,evidence) in enumerate(STAGES)]
