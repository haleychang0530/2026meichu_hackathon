import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, extname, join, normalize, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pageRoot = resolve(repoRoot, 'fixtures', 'device');
const resultDirectory = resolve(repoRoot, 'docs', 'device', 'runtime');
const port = Number(process.argv[2] || 8765);

const contentTypes = {
  '.html': 'text/html; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.wav': 'audio/wav',
  '.json': 'application/json; charset=utf-8',
};

function isInsideRoot(candidate) {
  const rel = relative(pageRoot, candidate);
  return rel === '' || (!rel.startsWith('..') && !rel.includes(`..${process.platform === 'win32' ? '\\' : '/'}`));
}

function send(response, status, body, contentType = 'text/plain; charset=utf-8') {
  response.writeHead(status, { 'Content-Type': contentType, 'Cache-Control': 'no-store' });
  response.end(body);
}

async function readRequestBody(request, maxBytes = 16 * 1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > maxBytes) throw new Error('request body too large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

const server = createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
    if (request.method === 'POST' && requestUrl.pathname === '/api/result') {
      const body = JSON.parse(await readRequestBody(request));
      const result = {
        schema_version: 'browser-device-check.v1',
        checked_at: new Date().toISOString(),
        browser_user_agent: typeof body.browser_user_agent === 'string' ? body.browser_user_agent.slice(0, 300) : null,
        secure_context: body.secure_context === true,
        camera: body.camera && typeof body.camera === 'object' ? {
          status: body.camera.status === 'pass' ? 'pass' : 'not_run',
          width: Number.isInteger(body.camera.width) ? body.camera.width : null,
          height: Number.isInteger(body.camera.height) ? body.camera.height : null,
          captured: body.camera.captured === true,
        } : { status: 'not_run' },
        microphone: body.microphone && typeof body.microphone === 'object' ? {
          status: body.microphone.status === 'pass' ? 'pass' : 'not_run',
          recorder_mime: typeof body.microphone.recorder_mime === 'string' ? body.microphone.recorder_mime.slice(0, 100) : null,
          recorded_bytes: Number.isInteger(body.microphone.recorded_bytes) ? body.microphone.recorded_bytes : null,
        } : { status: 'not_run' },
        playback: body.playback && typeof body.playback === 'object' ? {
          status: body.playback.status === 'pass' ? 'pass' : 'not_run',
          fixture: typeof body.playback.fixture === 'string' ? body.playback.fixture.slice(0, 100) : null,
        } : { status: 'not_run' },
        persistence: 'camera frames and microphone bytes are not persisted',
      };
      await mkdir(resultDirectory, { recursive: true });
      await writeFile(join(resultDirectory, 'browser-check-result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
      send(response, 200, JSON.stringify({ ok: true }), 'application/json; charset=utf-8');
      return;
    }

    if (request.method !== 'GET') {
      send(response, 405, 'Method Not Allowed');
      return;
    }

    const pathname = decodeURIComponent(requestUrl.pathname === '/' ? '/browser-device-check.html' : requestUrl.pathname);
    const candidate = normalize(resolve(pageRoot, `.${pathname}`));
    if (!isInsideRoot(candidate) || !existsSync(candidate)) {
      send(response, 404, 'Not Found');
      return;
    }
    const body = await readFile(candidate);
    send(response, 200, body, contentTypes[extname(candidate).toLowerCase()] || 'application/octet-stream');
  } catch (error) {
    send(response, 400, `Bad Request: ${error.message}`);
  }
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Browser device check: http://127.0.0.1:${port}/`);
  console.log('Press Ctrl+C to stop the local-only server.');
});
