// Data Hub view helpers and formatters (pure functions decoupled from DOM)

export function formatBytes(bytes) {
  if (typeof bytes !== 'number' || isNaN(bytes) || bytes < 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function buildOverpassTurboUrl(query, customBbox = null) {
  if (!query) return 'https://overpass-turbo.eu/';
  let q = query.trim();
  if (customBbox && typeof customBbox === 'string') {
    if (q.includes('{{bbox}}')) {
      q = q.replace(/\{\{bbox\}\}/g, customBbox);
    } else if (!q.startsWith('[bbox:')) {
      q = `[bbox:${customBbox}];\n` + q;
    }
  }
  return `https://overpass-turbo.eu/?Q=${encodeURIComponent(q)}`;
}

export function formatShaBadge(sha256) {
  if (!sha256 || typeof sha256 !== 'string') return '';
  return `${sha256.slice(0, 8)}…${sha256.slice(-6)}`;
}

export function filterManifestFiles(files, filters = {}) {
  if (!Array.isArray(files)) return [];

  const { scope = 'all', layer = 'all', format = 'all', query = '' } = filters;
  const q = (query || '').trim().toLowerCase();

  return files.filter(f => {
    if (scope !== 'all' && f.scope !== scope) return false;
    if (layer !== 'all' && f.layer !== layer) return false;
    if (format !== 'all' && f.format !== format) return false;

    if (q) {
      const idMatch = (f.id || '').toLowerCase().includes(q);
      const pathMatch = (f.path || '').toLowerCase().includes(q);
      const layerMatch = (f.layer || '').toLowerCase().includes(q);
      const scopeMatch = (f.scope || '').toLowerCase().includes(q);
      if (!idMatch && !pathMatch && !layerMatch && !scopeMatch) return false;
    }
    return true;
  });
}
