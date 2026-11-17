"""Capture read-only operational evidence and an authorized provider availability probe."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from run_remediation_checks import ROOT, local_config

os.environ.update(local_config())
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api')]
from sqlalchemy import select, func, text
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.governance.reconciliation import review
from app.modules.markets.odds_intelligence import assess
from app.modules.autonomy import open_intelligence as oi, openligadb
from app.main import app


def main():
    output = ROOT / 'artifacts/remediation'
    output.mkdir(parents=True, exist_ok=True)
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'mode': 'PAPER'}
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        report['database'] = db.scalar(text('select current_database()'))
        report['migration'] = db.scalar(text('select version_num from alembic_version'))
        report['counts'] = {model.__table__.fullname: db.scalar(select(func.count()).select_from(model))
                            for model in (m.Fixture, m.Odds, m.Observation, m.ModelGovernanceSnapshot, m.PipelineRun)}
        report['governance'] = review(db)
        quotes = db.scalars(select(m.Odds).order_by(m.Odds.observed_at.desc()).limit(10)).all()
        report['latest_price_assessments'] = [assess(db, quote) for quote in quotes]
    # Known authorized adapters only. These probes do not persist artificial observations.
    for provider, probe in (
        ('football-data', lambda: oi.fetch_csv(oi.FD_FIXTURES)),
        ('openligadb', lambda: openligadb.fetch(openligadb.BASE + '/getmatchdata/bl1'))):
        try:
            result = probe()
            if provider == 'football-data':
                rows, stamp = result
                report[provider] = {'status': 'REACHABLE', 'rows': len(rows), 'published_at': stamp,
                                    'bundesliga_rows': sum(row.get('Div') == 'D1' for row in rows)}
            else: report[provider] = {'status': 'REACHABLE', 'fixtures': len(result), 'bookmaker_odds': 'NOT_SUPPLIED'}
        except Exception as exc:
            report[provider] = {'status': 'UNAVAILABLE', 'error_type': type(exc).__name__, 'detail': str(exc)[:200]}
    schema = app.openapi()
    (output / 'openapi.json').write_text(json.dumps(schema, indent=2), encoding='utf-8')
    inventory = ['# API inventory', '', '| Method | Route | Summary |', '|---|---|---|']
    for path, operations in schema['paths'].items():
        for method, operation in operations.items():
            if method in ('get','post','put','patch','delete'):
                inventory.append(f"| {method.upper()} | `{path}` | {operation.get('summary','')} |")
    (ROOT / 'docs/REMEDIATION_API_INVENTORY.md').write_text('\n'.join(inventory)+'\n', encoding='utf-8')
    (output / 'live-evidence.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('migration','counts','football-data','openligadb')}, default=str))


if __name__ == '__main__': main()
