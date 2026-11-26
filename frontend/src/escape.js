// Escape untrusted text (OSM names, tags, usernames) before it goes into an
// innerHTML template. null/undefined become an empty string.
const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, ch => ENTITIES[ch]);
}
