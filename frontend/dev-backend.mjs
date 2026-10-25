import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, openSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

async function isBackendReady(url) {
  let response;
  try {
    response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(1500) });
  } catch (error) {
    if (error.cause?.code === 'ECONNREFUSED') return false;
    throw new Error(`Cannot verify the backend at ${url}. Check backend-error.log.`, { cause: error });
  }
  const health = await response.json().catch(() => null);
  const schema = await fetch(`${url}/openapi.json`, { signal: AbortSignal.timeout(1500) });
  const api = await schema.json().catch(() => null);
  if (!response.ok || health?.status !== 'healthy' || !schema.ok || api?.info?.title !== 'Print Guardian API') {
    throw new Error(`Port ${new URL(url).port} is occupied by an unhealthy or different service. No process was stopped.`);
  }
  return true;
}

// Exported separately so lifecycle tests can use a harmless HTTP fixture, never a printer.
export async function ensureBackend({
  url = 'http://127.0.0.1:8000', command = python,
  args = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log'],
  cwd = root, logDirectory = root, timeoutMs = 30000,
} = {}) {
  if (await isBackendReady(url)) return { owned: false, stop() {} };
  if (!existsSync(command)) throw new Error('Backend Python is missing. Install requirements.txt in the root .venv first.');

  const output = openSync(join(logDirectory, 'backend.log'), 'a');
  const errors = openSync(join(logDirectory, 'backend-error.log'), 'a');
  let child;
  try {
    child = spawn(command, args, { cwd, windowsHide: true, stdio: ['ignore', output, errors] });
  } finally {
    closeSync(output);
    closeSync(errors);
  }
  let failure;
  child.on('error', error => { failure = error; });
  const stop = () => {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    if (process.platform === 'win32') {
      // Only terminate this launcher's process tree, including its vision worker.
      spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    } else child.kill('SIGTERM');
  };
  try {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (failure || child.exitCode !== null || child.signalCode !== null) {
        throw new Error('Backend exited during startup. Check backend-error.log.', { cause: failure });
      }
      if (await isBackendReady(url)) return { owned: true, stop, child };
      await delay(250);
    }
    throw new Error('Backend did not become ready within 30 seconds. Check backend-error.log.');
  } catch (error) {
    stop();
    throw error;
  }
}

export default function backendPlugin() {
  return {
    name: 'layer-lock-backend',
    apply: 'serve',
    async configureServer(server) {
      const backend = await ensureBackend();
      server.config.logger.info(backend.owned
        ? 'Layer-Lock backend ready on port 8000. Logs: backend.log and backend-error.log.'
        : 'Using the existing Layer-Lock backend on port 8000.');
      if (!backend.owned) return;
      let stopping = false;
      const cleanup = () => {
        stopping = true;
        process.removeListener('exit', cleanup);
        backend.stop();
      };
      process.once('exit', cleanup);
      server.httpServer?.once('close', cleanup);
      backend.child.once('exit', () => {
        if (!stopping) server.config.logger.error('Layer-Lock backend stopped. Restart npm run dev; see backend-error.log. Automatic pauses are unavailable until monitoring is armed again.');
      });
    },
  };
}
