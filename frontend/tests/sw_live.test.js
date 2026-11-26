import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

function loadSw() {
  const src = readFileSync(fileURLToPath(new URL('../public/sw.js', import.meta.url)), 'utf8');
  const listeners = {};
  const put = vi.fn();
  const cache = { put, addAll: () => Promise.resolve() };
  const self = { addEventListener: (type, fn) => { listeners[type] = fn; }, skipWaiting() {}, clients: { claim() {} } };
  const caches = { open: () => Promise.resolve(cache), match: () => Promise.resolve(undefined), keys: () => Promise.resolve([]) };
  new Function('self', 'caches', 'fetch', 'URL', src)(self, caches, () => Promise.resolve({ status: 200, clone: () => ({}) }), URL);
  return { fetchHandler: listeners.fetch, put };
}

async function dispatch(fetchHandler, url) {
  let pending;
  fetchHandler({ request: { url, headers: { get: () => null } }, respondWith: p => { pending = p; } });
  await pending;
  await new Promise(r => setTimeout(r, 0));
}

describe('service worker', () => {
  it('never caches the live places delta', async () => {
    const { fetchHandler, put } = loadSw();
    await dispatch(fetchHandler, 'https://manara.saudiosm.org/api/v1/places/live?since=2026-11-25T00:00:00Z');
    expect(put).not.toHaveBeenCalled();
  });

  it('still caches other API responses (sanity check of the harness)', async () => {
    const { fetchHandler, put } = loadSw();
    await dispatch(fetchHandler, 'https://manara.saudiosm.org/api/v1/meta');
    expect(put).toHaveBeenCalled();
  });
});
