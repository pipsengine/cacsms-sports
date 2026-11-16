// Starts the FastAPI API (port 8000), the background task scheduler and the Vite web app (port 5173) together.
// Usage from the repository root: npm run dev   (Ctrl+C stops both)
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(root, 'apps', 'api');
const webDir = path.join(root, 'apps', 'web');
const isWin = process.platform === 'win32';

// Load KEY=VALUE pairs from the root .env (git-ignored); real environment variables win.
const envFile = path.join(root, '.env');
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m || line.trimStart().startsWith('#')) continue;
    const val = m[2].replace(/^(['"])(.*)\1$/, '$2');
    if (process.env[m[1]] === undefined) process.env[m[1]] = val;
  }
}

const venvPython = path.join(apiDir, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(venvPython)) {
  console.error(`Missing API virtualenv at ${venvPython}\nCreate it: cd apps/api && python -m venv .venv && .venv/${isWin ? 'Scripts' : 'bin'}/python -m pip install -r requirements.txt`);
  process.exit(1);
}
if (!existsSync(path.join(webDir, 'node_modules'))) {
  console.error('Missing web dependencies. Run: cd apps/web && npm install');
  process.exit(1);
}

const children = [];
function start(name, color, cmd, args, opts) {
  const child = spawn(cmd, args, { ...opts, shell: false });
  const tag = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = '';
    stream.on('data', (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) out.write(tag + line + '\n');
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on('exit', (code) => {
    console.log(`${tag}exited with code ${code}`);
    shutdown(code ?? 0);
  });
  children.push(child);
}

let stopping = false;
function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    if (isWin) spawn('taskkill', ['/pid', String(c.pid), '/T', '/F']);
    else c.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 500);
}
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

if (!process.env.DATABASE_URL) console.warn('DATABASE_URL not set (add it to .env); the API will use its built-in default.');

const pyEnv = { ...process.env, PYTHONPATH: root, PYTHONUNBUFFERED: '1' };
// Keep the schema current before either API or scheduler can query new columns.
console.log('[db] Applying database migrations...');
const migration = spawnSync(venvPython, ['-m', 'alembic', 'upgrade', 'head'], {
  cwd: apiDir,
  env: pyEnv,
  stdio: 'inherit',
});
if (migration.error || migration.status !== 0) {
  console.error('[db] Database migration failed; services were not started. Check PostgreSQL and DATABASE_URL in .env.');
  if (migration.error) console.error(migration.error.message);
  process.exit(migration.status || 1);
}
// --timeout-graceful-shutdown: open live-update (SSE) streams would otherwise block reloads.
start('api', '36', venvPython, ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000', '--timeout-graceful-shutdown', '3'], {
  cwd: apiDir,
  env: pyEnv,
});
// Autonomous background tasks (Celery beat schedule, run in-process; no Redis needed locally).
start('worker', '33', venvPython, ['-m', 'app.modules.acquisition.dev_scheduler'], {
  cwd: apiDir,
  env: pyEnv,
});
start('web', '35', isWin ? 'cmd.exe' : 'npm', isWin ? ['/c', 'npm', 'run', 'dev'] : ['run', 'dev'], {
  cwd: webDir,
  env: process.env,
});
