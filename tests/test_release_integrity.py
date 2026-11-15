"""Offline release invariants; CI additionally executes migrations against PostgreSQL."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]

def test_migration_chain():
    versions=ROOT/'apps/api/migrations/versions'
    revisions={}
    for path in versions.glob('*.py'):
        tree=ast.parse(path.read_text())
        fields={}
        for stmt in tree.body:
            if isinstance(stmt,ast.Assign):
                for target in stmt.targets:
                    if isinstance(target,ast.Name) and target.id in ('revision','down_revision'):
                        fields[target.id]=ast.literal_eval(stmt.value)
        assert fields.get('revision'),path
        assert fields['revision'] not in revisions
        revisions[fields['revision']]=fields.get('down_revision')
    assert revisions, "No migrations found"
    roots=[key for key,prev in revisions.items() if prev is None]
    assert len(roots)==1
    assert all(prev is None or prev in revisions for prev in revisions.values())
    tips=set(revisions)-{x for x in revisions.values() if x}
    assert len(tips)==1
    seen=set(); current=next(iter(tips))
    while current:
        assert current not in seen
        seen.add(current);current=revisions[current]
    assert seen==set(revisions)

def test_paper_only_runtime():
    config=(ROOT/'apps/api/app/core/config.py').read_text()
    assert "EXECUTION_MODE='PAPER'" in config
    assert 'live_betting' in (ROOT/'apps/api/app/modules/readiness.py').read_text()

def test_all_navigation_pages_have_routes():
    text=(ROOT/'apps/web/src/navigation.ts').read_text()
    assert text.count("'/sports/") == 0 or 'dashboard' in text
    assert 'booking-codes' in text and 'command-centre' in text
