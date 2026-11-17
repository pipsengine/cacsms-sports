"""Run regression tests with PostgreSQL restricted to disposable test databases.

Local credentials are read without printing them. The ordinary app connection is
deliberately unavailable so unpatched API tests cannot write to the live database.
"""
import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


def local_config():
    config = dict(os.environ)
    path = ROOT / '.env'
    for line in path.read_text().splitlines() if path.exists() else []:
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            config.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return config


def configured_url(config):
    return config.get('DATABASE_URL') or URL.create('postgresql+psycopg',
        username=config.get('POSTGRES_USER', 'sports'), password=config.get('POSTGRES_PASSWORD', 'sports'),
        host=config.get('POSTGRES_HOST', 'localhost'), port=int(config.get('POSTGRES_PORT', '5432')),
        database=config.get('POSTGRES_DB', 'sports_ai')).render_as_string(hide_password=False)


if __name__ == '__main__':
    output = ROOT / 'artifacts' / 'remediation'
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SPORTS_TEST_DATABASE_URL=configured_url(local_config()),
               DATABASE_URL='postgresql+psycopg://unavailable:unavailable@127.0.0.1:1/unavailable', PYTHONPATH=str(ROOT))
    args = [sys.executable, '-m', 'pytest', '-q', '--disable-warnings',
            '--junitxml=' + str(output / 'backend-tests.xml'), *sys.argv[1:]]
    result = subprocess.run(args, cwd=ROOT / 'apps/api', env=env, capture_output=True, text=True)
    (output / 'backend-tests.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout)
    sys.exit(result.returncode)
