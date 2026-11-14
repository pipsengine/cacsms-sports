from pathlib import Path
import ast,subprocess,sys
root=Path(__file__).resolve().parents[1]
for file in (root/'apps/api').rglob('*.py'):ast.parse(file.read_text())
required=['docker-compose.yml','apps/web/src/App.tsx','apps/api/app/main.py','apps/api/app/modules/vision/provider.py','apps/api/app/modules/vision/pipeline.py','.github/workflows/ci.yml']
for name in required:assert (root/name).is_file(),name
print('Release source checks passed; Docker runtime and external integrations require separate validation')
