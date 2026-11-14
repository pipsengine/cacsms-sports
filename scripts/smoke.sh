#!/usr/bin/env sh
set -eu
BASE="${BASE_URL:-http://localhost:8000}"
python3 - "$BASE" <<'PYSMOKE'
import json,sys,urllib.request
base=sys.argv[1]
for path in ('/health','/api/v1/sports/browser/readiness','/api/v1/sports/dashboard/summary'):
    with urllib.request.urlopen(base+path,timeout=15) as r:
        assert r.status==200,(path,r.status)
        body=json.load(r)
        print(path,body)
        if path=='/health':assert body['database']=='CONNECTED','Database unavailable'
        if path.endswith('/browser/readiness'):assert body['mode']=='PAPER'
print('API smoke checks passed (does not verify external vision or sports-data provider)')
PYSMOKE
