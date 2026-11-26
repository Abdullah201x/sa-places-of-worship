// Gate for the Wikidata "suggestions" layer (mosques in Wikidata that are missing from OSM).
//
// Only OSM users on the backend's MANARA_SUGGESTIONS_ALLOWLIST may see them. The backend
// enforces it (the API and Caddy's forward_auth on the /data/ files); this module only
// decides whether to show the controls. The answer lives in memory, never in localStorage,
// so editing browser storage cannot grant anything, and every failure means "no access".

let allowed = false;
let pending = null;

export function canViewSuggestions() {
  return allowed;
}

/** Asks the backend whether the signed-in Manara session may view suggestions. Cached per page load. */
export function checkSuggestionsAccess() {
  if (!pending) {
    pending = fetch('/api/v1/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(res => (res.ok ? res.json() : null))
      .then(body => {
        allowed = body?.can_view_suggestions === true;
        return allowed;
      })
      .catch(() => false);
  }
  return pending;
}
