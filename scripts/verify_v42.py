from pathlib import Path
root=Path(__file__).resolve().parents[1]
a=(root/'apps/web/src/App.tsx').read_text()
assert "<ProgrammeWorkspace programme=" in a
assert "<AdministrationWorkspace page=" in a
assert "String(r.status||'UNVERIFIED')" in (root/'apps/web/src/TicketWorkspace.tsx').read_text()
assert len(list((root/'apps/web/src').glob('*Workspace.tsx')))>=5
print('v4.2 workspace routing and ticket-status regression checks passed')
