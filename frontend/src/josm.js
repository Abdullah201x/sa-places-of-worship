// Helper for JOSM Remote Control requests.
// Tries the standard HTTP port (8111) first, then falls back to JOSM's HTTPS
// port (8112) when an HTTPS page blocks mixed-content HTTP requests.

export const JOSM_ORIGINS = [
  'http://127.0.0.1:8111',
  'https://127.0.0.1:8112',
];

function normalizeJosmPath(pathOrUrl) {
  if (/^https?:\/\/127\.0\.0\.1:(8111|8112)/i.test(pathOrUrl)) {
    return pathOrUrl.replace(/^https?:\/\/127\.0\.0\.1:(8111|8112)/i, '');
  }
  return pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`;
}

export async function sendJosmCommand(pathOrUrl, { fetchImpl = globalThis.fetch } = {}) {
  const path = normalizeJosmPath(pathOrUrl);
  for (const origin of JOSM_ORIGINS) {
    try {
      const res = await fetchImpl(`${origin}${path}`);
      if (res.ok) {
        return { ok: true, reachable: true, status: res.status, origin };
      }
      return { ok: false, reachable: true, status: res.status, origin };
    } catch {
      // Network/mixed-content error — try next origin.
    }
  }
  return { ok: false, reachable: false, status: 0, origin: null };
}
