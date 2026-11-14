from pathlib import Path
root=Path(__file__).resolve().parents[1]
app=(root/'apps/web/src/App.tsx').read_text()
workspace=(root/'apps/web/src/IntelligenceMarketWorkspace.tsx').read_text()
assert 'IntelligenceMarketWorkspace' in app
for page in ['fixtures','statistics','match-analysis','predictions','markets','qualification','opportunities']:
 assert page in workspace
assert 'fetch(API+resource)' in workspace
assert 'No matching evidence records' in workspace
print('v4.1 workspace integrity passed')
