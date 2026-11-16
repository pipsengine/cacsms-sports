import { createServer } from 'node:net';

export function checkPort({ name, port, host }) {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', (error) => {
      const reason = error.code === 'EADDRINUSE' ? 'already in use'
        : error.code === 'EACCES' ? 'unavailable (access denied or reserved by Windows)'
        : `unavailable (${error.code || error.message})`;
      reject(new Error(`${name} port ${port} on ${host} is ${reason}. Stop the existing server or release this port before running npm run dev.`));
    });
    server.listen({ port, host, exclusive: true }, () => server.close(resolve));
  });
}

export async function checkDevPorts(ports = [
  { name: 'API', port: 8000, host: '127.0.0.1' },
  { name: 'Web', port: 5173, host: '0.0.0.0' },
]) {
  const checks = await Promise.allSettled(ports.map(checkPort));
  const failures = checks.filter(result => result.status === 'rejected');
  if (failures.length) throw new Error(failures.map(result => result.reason.message).join('\n'));
}
