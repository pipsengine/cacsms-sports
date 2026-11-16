import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import { checkPort, checkDevPorts } from './dev-ports.mjs';

test('occupied port reports its service and port without stopping its owner', async () => {
  const owner = createServer();
  await new Promise(resolve => owner.listen(0, '127.0.0.1', resolve));
  const port = owner.address().port;
  try {
    await assert.rejects(checkPort({ name: 'API', port, host: '127.0.0.1' }), error =>
      error.message.includes(`API port ${port}`) && error.message.includes('already in use'));
    assert.equal(owner.listening, true);
  } finally {
    await new Promise(resolve => owner.close(resolve));
  }
});

test('available ports are released after checking', async () => {
  await checkDevPorts([{ name: 'Web', port: 0, host: '127.0.0.1' }]);
});

test('all conflicting services are reported together', async () => {
  const owners = [createServer(), createServer()];
  await Promise.all(owners.map(server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve))));
  try {
    await assert.rejects(checkDevPorts(owners.map((server, index) => ({
      name: index ? 'Web' : 'API', port: server.address().port, host: '127.0.0.1',
    }))), error => error.message.includes('API port') && error.message.includes('Web port'));
  } finally {
    await Promise.all(owners.map(server => new Promise(resolve => server.close(resolve))));
  }
});
