"""Package committed source plus selected verification evidence, without secrets."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/cacsms-sports-remediation-2026-11-18.zip'
EVIDENCE = ['backend-tests.xml', 'backend-tests.txt', 'root-tests.xml', 'ui-tests.json',
            'ui-interactions.json', 'live-evidence.json', 'runtime-status.json',
            'model-reconciliation.json', 'openapi.json',
            'markets-390.png', 'markets-768.png', 'markets-1280.png', 'markets-1920.png']


def main():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise RuntimeError('Commit source changes before packaging')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    subprocess.run(['git', 'archive', '--format=zip', '-o', str(OUTPUT), 'HEAD'], cwd=ROOT, check=True)
    files = [(ROOT / 'artifacts/remediation' / name, 'evidence/' + name) for name in EVIDENCE]
    files += [(ROOT / 'artifacts' / name, 'evidence/' + name) for name in
              ('npm-audit-remediation.json', 'python-audit-remediation.json', 'python-requirements-audit.json')]
    hashes = {}
    with zipfile.ZipFile(OUTPUT, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for source, target in files:
            if not source.is_file(): raise RuntimeError('Missing verification evidence: ' + source.name)
            hashes[target] = hashlib.sha256(source.read_bytes()).hexdigest()
            archive.write(source, target)
        archive.writestr('DELIVERY_MANIFEST.json', json.dumps({'commit': commit,
            'mode': 'PAPER', 'database_migration': '0017', 'evidence_sha256': hashes,
            'database_dump_included': False, 'credentials_included': False,
            'production_ready': False}, indent=2))
        assert all(Path(name).name != '.env' for name in archive.namelist())
        assert archive.testzip() is None
    print(json.dumps({'zip': str(OUTPUT), 'commit': commit, 'bytes': OUTPUT.stat().st_size,
                      'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}))


if __name__ == '__main__': main()
