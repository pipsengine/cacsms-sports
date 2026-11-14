"""Offline smoke checks for sidebar consistency and route preservation."""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
nav=(root/'apps/web/src/navigation.ts').read_text()
app=(root/'apps/web/src/App.tsx').read_text()
entries=re.findall(r"\['([^']+)','([^']+)'\]",nav.split('export const groupIcons')[0])
assert len(entries)==29, f'expected 29 routes, got {len(entries)}'
assert len(set(slug for _,slug in entries))==29, 'duplicate route'
assert len(re.findall(r"^  '[^']+': \[",nav,flags=re.M))==8, 'expected 8 groups'
assert app.count('<PipelineOperations/>')==1, 'orchestrator duplicated'
assert 'CACSMS SPORT AI' not in app, 'legacy brand'
assert 'pageDescriptions[path]' in app
assert 'aria-expanded={isExpanded}' in app
assert 'path===\'live-operations\'' in app
print('PASS: 29 unique routes, 8 groups, 1 orchestrator, accessible collapsible sidebar, new branding')
