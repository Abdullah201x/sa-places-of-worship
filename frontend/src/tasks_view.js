// Tasks & Sprint Board pure helper functions and state formatters
// Decoupled from DOM and API calls for testability.

export const TILE_STATE_LABELS = {
  ready: { ar: 'جاهز للرسم', en: 'Ready' },
  mapping: { ar: 'قيد الرسم', en: 'Mapping' },
  mapped: { ar: 'تم الرسم', en: 'Mapped' },
  validating: { ar: 'قيد التحقق', en: 'Validating' },
  validated: { ar: 'معتمد', en: 'Validated' },
  invalidated: { ar: 'مرفوض للتصحيح', en: 'Needs Work' },
  skipped: { ar: 'تم التخطي', en: 'Skipped' },
};

export function formatTileStateBadge(state, lang = 'ar') {
  const isAr = lang === 'ar';
  const entry = TILE_STATE_LABELS[state] || { ar: state, en: state };
  const label = isAr ? entry.ar : entry.en;

  let className = 'state-ready';
  let glyph = '◻';
  if (state === 'mapping') {
    className = 'state-mapping';
    glyph = '✎';
  } else if (state === 'mapped') {
    className = 'state-mapped';
    glyph = '✓';
  } else if (state === 'validating') {
    className = 'state-validating';
    glyph = '🔍';
  } else if (state === 'validated') {
    className = 'state-validated';
    glyph = '★';
  } else if (state === 'invalidated') {
    className = 'state-invalidated';
    glyph = '✕';
  } else if (state === 'skipped') {
    className = 'state-skipped';
    glyph = '↷';
  }

  return { label, className, glyph };
}

export function generateIdEditorUrl(tileBbox, sprintTitle, hashtag) {
  const [minLon, minLat, maxLon, maxLat] = tileBbox;
  const centerLat = ((minLat + maxLat) / 2).toFixed(6);
  const centerLon = ((minLon + maxLon) / 2).toFixed(6);
  const comment = encodeURIComponent(sprintTitle || 'Mosque mapping sprint');
  const tags = encodeURIComponent(hashtag || '#sa-worship-map');
  return `https://www.openstreetmap.org/edit?editor=id#map=16/${centerLat}/${centerLon}&comment=${comment}&hashtags=${tags}`;
}

export function generateJosmRemoteUrl(tileBbox, sprintTitle, hashtag) {
  const [minLon, minLat, maxLon, maxLat] = tileBbox;
  const comment = encodeURIComponent(sprintTitle || 'Mosque mapping sprint');
  const tags = encodeURIComponent(hashtag || '#sa-worship-map');
  return `http://127.0.0.1:8111/load_and_zoom?left=${minLon}&bottom=${minLat}&right=${maxLon}&top=${maxLat}&changeset_comment=${comment}&changeset_hashtags=${tags}`;
}

export function findNextReadyTile(tiles) {
  if (!Array.isArray(tiles)) return null;
  const readyTiles = tiles.filter(t => t.state === 'ready');
  if (!readyTiles.length) return null;
  // Prioritize highest workload first
  return readyTiles.sort((a, b) => (b.workload || 0) - (a.workload || 0))[0];
}

export function calculateSprintProgress(tiles) {
  if (!Array.isArray(tiles) || tiles.length === 0) {
    return { total: 0, validated: 0, mapped: 0, remainingWorkload: 0, pct: 0 };
  }
  const total = tiles.length;
  const validated = tiles.filter(t => t.state === 'validated').length;
  const mapped = tiles.filter(t => t.state === 'mapped' || t.state === 'validating').length;
  const remainingWorkload = tiles.reduce((acc, t) => {
    return t.state !== 'validated' ? acc + (t.workload || 0) : acc;
  }, 0);
  const pct = Math.round((validated / total) * 100);
  return { total, validated, mapped, remainingWorkload, pct };
}
