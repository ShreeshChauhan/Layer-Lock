import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { ensureBackend } from './dev-backend.mjs';

async function options(t) {
  const directory = await mkdtemp(join(tmpdir(), 'layerlock-startup-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const reservation = createServer();
  reservation.listen(0, '127.0.0.1');
  await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const script = `
    const http = require('node:http');
    setTimeout(() => http.createServer((req, res) => {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(req.url === '/health' ? {status: 'healthy'} : {info: {title: 'Print Guardian API'}}));
    }).listen(${port}, '127.0.0.1'), 300);
  `;
  return { url: `http://127.0.0.1:${port}`, command: process.execPath,
    args: ['-e', script], logDirectory: directory, timeoutMs: 5000 };
}

test('waits for startup, reuses a healthy backend, and stops only an owned process', async t => {
  const config = await options(t);
  const owned = await ensureBackend(config);
  t.after(async () => {
    owned.stop();
    if (owned.child.exitCode === null && owned.child.signalCode === null) await once(owned.child, 'exit');
  });
  assert.equal(owned.owned, true);
  const reused = await ensureBackend(config);
  assert.equal(reused.owned, false);
  reused.stop();
  assert.equal((await fetch(`${config.url}/health`)).status, 200);
  owned.stop();
  await once(owned.child, 'exit');
  await assert.rejects(fetch(`${config.url}/health`));
});

test('reports a backend that exits instead of opening a broken dashboard', async t => {
  const config = await options(t);
  await assert.rejects(ensureBackend({ ...config, args: ['-e', 'process.exit(1)'] }), /exited during startup/);
});

test('startup timeout stops the child and releases resources', async t => {
  const config = await options(t);
  await assert.rejects(ensureBackend({ ...config, timeoutMs: 500, args: ['-e', 'setInterval(() => {}, 1000)'] }), /did not become ready/);
});

test('refuses a port occupied by a different service', async t => {
  const config = await options(t);
  const server = createServer((req, res) => res.end('{"status":"healthy","info":{"title":"Other API"}}'));
  server.listen(Number(new URL(config.url).port), '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise(resolve => server.close(resolve)));
  await assert.rejects(ensureBackend(config), /different service/);
  assert.equal((await fetch(`${config.url}/health`)).status, 200);
});
