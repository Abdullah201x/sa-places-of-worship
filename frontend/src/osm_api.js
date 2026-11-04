// OpenStreetMap OAuth 2.0 (PKCE) and API 0.6 tag editing, adapted from the
// osm x wikidata project's js/osm_oauth.js (linkOsmElement /
// linkOsmElementsBatch), which itself started from this project's login code.
import { addTranslations, t } from './i18n.js';
import { showToast, showLoadingText } from './ui.js';
import { trackEvent } from './analytics.js';
import { MAX_TAG_LENGTH, upgradeTags } from './presets.js';

addTranslations({
  authNeedClientId: ['لا يوجد معرّف عميل مدمج لهذا العنوان. أدخل معرّف العميل (Client ID) في الإعدادات المتقدمة.', 'No built-in client ID for this address. Enter a client ID under advanced settings.'],
  authStateMismatch: ['خطأ في التحقق من حالة الطلب (State Mismatch). يرجى المحاولة مجدداً.', 'Login state mismatch. Please try again.'],
  authNoVerifier: ['مفقود رمز التحقق (Code Verifier). يرجى المحاولة مجدداً.', 'Missing PKCE code verifier. Please try again.'],
  authExchanging: ['جارٍ تأكيد الهوية وتبادل الرموز مع OSM...', 'Confirming your identity with OSM...'],
  authSuccess: ['تم تسجيل الدخول بنجاح عبر OpenStreetMap!', 'Logged in with OpenStreetMap.'],
  authFailed: ['فشل في تسجيل الدخول عبر OpenStreetMap: {msg}', 'OpenStreetMap login failed: {msg}'],
  authLoggedOut: ['تم تسجيل الخروج بنجاح.', 'Logged out.'],
  authHttpsRequired: ['يتطلب تسجيل الدخول عبر OpenStreetMap اتصالاً آمناً (HTTPS). شغّل الخادم المحلي بالأمر: npm run dev (داخل مجلد frontend) ثم افتح https://localhost:8000/', 'OpenStreetMap login requires HTTPS. Run the local server with: npm run dev (in the frontend folder) and open https://localhost:8000/'],
  authFileProtocol: ['لا يمكن تسجيل الدخول عبر فتح الملف مباشرة (file://). شغّل الموقع عبر خادم محلي آمن (npm run dev).', 'Login is not supported over file://. Please serve the site over HTTPS (npm run dev).'],
});

// OAuth2 application registered on openstreetmap.org for this site (public
// PKCE client, scopes read_prefs write_api write_notes, redirect URI
// https://manara.saudiosm.org/).
export const DEFAULT_OSM_CLIENT_ID = 'TTBAYQAUONpxZxCbg_FRe-78y6A8K0DHIj1AylyCn7w';

export const OSM_SCOPES = 'read_prefs write_api write_notes';
export const CHANGESET_CREATED_BY = 'Saudi Places of Worship Map (https://manara.saudiosm.org)';
export const CHANGESET_HASHTAGS = '#sa-worship-map';

export const OsmApi = {
  environment() {
    return localStorage.getItem('osm_oauth_environment') || 'production';
  },

  urls() {
    const dev = this.environment() === 'dev';
    const site = dev ? 'https://master.apis.dev.openstreetmap.org' : 'https://www.openstreetmap.org';
    const api = dev ? 'https://master.apis.dev.openstreetmap.org' : 'https://api.openstreetmap.org';
    return {
      site,
      api,
      authorize: `${site}/oauth2/authorize`,
      token: `${site}/oauth2/token`,
      userDetails: `${api}/api/0.6/user/details.json`
    };
  },

  // A custom client ID (advanced settings) wins over the built-in one.
  clientId() {
    const custom = (localStorage.getItem('osm_oauth_client_id') || '').trim();
    if (custom === 'FLWYiombLxXfIjsnoG25hqP5fMQZJD52WdME2gn0b60' || custom === '66V3GYmV7X9ZP9zIimXwk1Pi-R2YWBLz2peCFLjcImE') {
      localStorage.removeItem('osm_oauth_client_id');
      return DEFAULT_OSM_CLIENT_ID;
    }
    return custom || DEFAULT_OSM_CLIENT_ID;
  },

  // Always the site root: it is the one redirect URI registered for the OSM
  // application, whichever page (/tasks, /start ...) started the login. The
  // page to come back to is kept in sessionStorage (see startLogin).
  redirectUri() {
    return window.location.origin + '/';
  },

  token() {
    return localStorage.getItem('osm_access_token');
  },

  uid() {
    const raw = localStorage.getItem('osm_uid');
    return raw ? parseInt(raw, 10) : null;
  },

  grantedScopes() {
    return (localStorage.getItem('osm_granted_scope') || '').split(/\s+/).filter(Boolean);
  },

  canEdit() {
    return !!this.token() && this.grantedScopes().includes('write_api');
  },

  userName() {
    return localStorage.getItem('osm_user_display_name') || '';
  },

  _random(length) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
    const values = crypto.getRandomValues(new Uint8Array(length));
    return Array.from(values, v => chars[v % chars.length]).join('');
  },

  async _challenge(verifier) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  },

  async startLogin({ returnHash } = {}) {
    if (window.location.protocol === 'file:') {
      showToast(t('authFileProtocol'), 'error');
      return false;
    }
    if (window.location.protocol === 'http:') {
      showToast(t('authHttpsRequired'), 'warning');
      return false;
    }
    const clientId = this.clientId();
    if (!clientId) {
      showToast(t('authNeedClientId'), 'error');
      return false;
    }
    const verifier = this._random(64);
    const state = this._random(24);
    sessionStorage.setItem('osm_oauth_code_verifier', verifier);
    sessionStorage.setItem('osm_oauth_state', state);
    // Come back to this exact page/view after the round trip through openstreetmap.org.
    sessionStorage.setItem('osm_oauth_return_to',
      window.location.pathname + window.location.search + (returnHash ?? window.location.hash));

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: clientId,
      redirect_uri: this.redirectUri(),
      scope: OSM_SCOPES,
      code_challenge: await this._challenge(verifier),
      code_challenge_method: 'S256',
      state
    });
    window.location.href = `${this.urls().authorize}?${params}`;
    return true;
  },

  // Completes the PKCE flow if the page was opened by the OAuth redirect.
  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    if (!code || !state) return;

    const returnTo = sessionStorage.getItem('osm_oauth_return_to') || '';
    sessionStorage.removeItem('osm_oauth_return_to');
    // Same-origin paths only, never a protocol-relative or absolute URL.
    const safeReturnTo = /^\/(?!\/)/.test(returnTo) ? returnTo : '';
    const returnUrl = new URL(safeReturnTo || window.location.pathname, window.location.origin);
    const leaveToOtherPage = returnUrl.pathname !== window.location.pathname;
    window.history.replaceState({}, document.title,
      leaveToOtherPage ? window.location.pathname : returnUrl.pathname + returnUrl.search + returnUrl.hash);

    const savedState = sessionStorage.getItem('osm_oauth_state');
    const verifier = sessionStorage.getItem('osm_oauth_code_verifier');
    sessionStorage.removeItem('osm_oauth_state');
    sessionStorage.removeItem('osm_oauth_code_verifier');
    if (state !== savedState) {
      showToast(t('authStateMismatch'), 'error');
      if (leaveToOtherPage) window.location.replace(returnUrl.pathname + returnUrl.search + returnUrl.hash);
      return;
    }
    if (!verifier) {
      showToast(t('authNoVerifier'), 'error');
      if (leaveToOtherPage) window.location.replace(returnUrl.pathname + returnUrl.search + returnUrl.hash);
      return;
    }

    try {
      showLoadingText(t('authExchanging'));
      const response = await fetch(this.urls().token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          client_id: this.clientId(),
          grant_type: 'authorization_code',
          code,
          redirect_uri: this.redirectUri(),
          code_verifier: verifier
        })
      });
      if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
      const data = await response.json();
      if (!data.access_token) throw new Error('no access_token in response');
      localStorage.setItem('osm_access_token', data.access_token);
      localStorage.setItem('osm_granted_scope', data.scope || OSM_SCOPES);
      try {
        await fetch('/auth/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Manara-CSRF': '1' },
          body: JSON.stringify({ access_token: data.access_token })
        });
      } catch (sessionErr) {
        console.warn('Could not establish Manara backend session:', sessionErr);
      }
      await this.checkAuth();
      trackEvent('Login success');
      showToast(t('authSuccess'));
    } catch (err) {
      console.error(err);
      showToast(t('authFailed', { msg: err.message }), 'error');
    }
    if (leaveToOtherPage) {
      // Login started on another page (e.g. /tasks): the token is stored, go back there.
      window.location.replace(returnUrl.pathname + returnUrl.search + returnUrl.hash);
    }
  },

  // Verifies the stored token and refreshes the display name.
  async checkAuth() {
    const token = this.token();
    if (!token) return false;
    try {
      const response = await fetch(this.urls().userDetails, { headers: { Authorization: `Bearer ${token}` } });
      if (response.ok) {
        const data = await response.json();
        if (data.user) {
          if (data.user.id) {
            localStorage.setItem('osm_uid', String(data.user.id));
          }
          if (data.user.display_name) {
            localStorage.setItem('osm_user_display_name', data.user.display_name);
          }
          return true;
        }
      } else if (response.status === 401 || response.status === 403) {
        this.logout(false);
      }
    } catch (err) {
      console.error('Error verifying OSM token:', err);
    }
    return false;
  },

  async logout(reload = true) {
    try {
      await fetch('/auth/logout', {
        method: 'POST',
        headers: { 'X-Manara-CSRF': '1' }
      });
    } catch (_) {}
    ['osm_access_token', 'osm_user_display_name', 'osm_granted_scope', 'osm_uid'].forEach(k => localStorage.removeItem(k));
    if (reload) {
      showToast(t('authLoggedOut'));
      window.location.reload();
    }
  },

  // ---------------------------------------------------------------------------
  // API 0.6 editing
  // ---------------------------------------------------------------------------

  _escapeXml(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  },

  truncateTag(value) {
    const chars = [...String(value)];
    return chars.length > MAX_TAG_LENGTH ? chars.slice(0, MAX_TAG_LENGTH - 1).join('') + '…' : String(value);
  },

  async _request(method, path, body) {
    const token = this.token();
    if (!token) throw new Error('NOT_AUTHENTICATED');
    const headers = { Authorization: `Bearer ${token}` };
    if (body) headers['Content-Type'] = 'application/xml; charset=utf-8';
    const res = await fetch(`${this.urls().api}/api/0.6/${path}`, { method, headers, body });
    if (res.status === 401 || res.status === 403) throw new Error('AUTH_EXPIRED');
    const text = await res.text();
    if (res.status === 409 && /version mismatch/i.test(text)) {
      // Someone edited the element between our GET and PUT.
      throw new Error(`VERSION_CONFLICT ${method} ${path}`);
    }
    if (!res.ok) throw new Error(`${method} ${path}: HTTP ${res.status} ${text}`.trim());
    return text;
  },

  // Current XML of an element, its tags and version.
  async fetchElement(type, id) {
    const res = await fetch(`${this.urls().api}/api/0.6/${type}/${id}`);
    if (res.status === 404 || res.status === 410) throw new Error(`ELEMENT_GONE ${type}/${id}`);
    if (!res.ok) throw new Error(`GET ${type}/${id}: HTTP ${res.status}`);
    const doc = new DOMParser().parseFromString(await res.text(), 'application/xml');
    const node = doc.querySelector(type);
    if (!node) throw new Error(`Could not parse ${type}/${id}`);
    const tags = {};
    node.querySelectorAll(':scope > tag').forEach(tag => {
      tags[tag.getAttribute('k')] = tag.getAttribute('v');
    });
    return { doc, node, tags, version: Number(node.getAttribute('version')) };
  },

  // Lazy-fetch contributor info (user, uid, changeset) for authenticated mappers.
  // The public extract omits these fields; we fetch them on-demand per element
  // and cache in sessionStorage keyed by version.
  async fetchLastEdit(type, id, version = null) {
    if (version != null) {
      const cached = sessionStorage.getItem(`osm_meta:${type}/${id}@${version}`);
      if (cached) {
        try { return JSON.parse(cached); } catch (e) { /* ignore parse error */ }
      }
    }
    const res = await fetch(`${this.urls().api}/api/0.6/${type}/${id}.json`);
    if (!res.ok) throw new Error(`GET ${type}/${id}.json: HTTP ${res.status}`);
    const data = await res.json();
    const el = data.elements && data.elements[0];
    if (!el) throw new Error(`Element ${type}/${id} not found`);
    const meta = {
      user: el.user || '',
      uid: el.uid != null ? el.uid : null,
      changeset: el.changeset != null ? el.changeset : null,
      version: el.version != null ? el.version : null,
      timestamp: el.timestamp || ''
    };
    try {
      if (meta.version != null) {
        sessionStorage.setItem(`osm_meta:${type}/${id}@${meta.version}`, JSON.stringify(meta));
      }
      if (version != null && version !== meta.version) {
        sessionStorage.setItem(`osm_meta:${type}/${id}@${version}`, JSON.stringify(meta));
      }
    } catch (e) {
      // Ignore quota errors in private browsing
    }
    return meta;
  },

  // edits = { upgrade: [rule], set: {k: v}, setIfMissing: {k: v}, del: [k] }.
  // upgrade holds preset upgrade rules (presets.js), matched against the
  // element's current tags so a rule that no longer applies changes nothing.
  // Returns the resulting tags, or null when the edit would change nothing.
  /**
   * Merges the edits of several queued fixes for the SAME element into one
   * edits object, so the element is fetched and uploaded exactly once.
   */
  mergeEdits(list) {
    const merged = {};
    list.forEach(e => {
      if (e.upgrade && !merged.upgrade) merged.upgrade = e.upgrade;
      if (e.set) merged.set = { ...(merged.set || {}), ...e.set };
      if (e.setIfMissing) merged.setIfMissing = { ...e.setIfMissing, ...(merged.setIfMissing || {}) };
      if (e.del) merged.del = [...new Set([...(merged.del || []), ...e.del])];
    });
    return merged;
  },

  applyEditsToTags(tags, edits) {
    let result = { ...tags };
    if (edits.upgrade) result = upgradeTags(result, edits.upgrade).tags;
    Object.entries(edits.set || {}).forEach(([k, v]) => { result[k] = v; });
    Object.entries(edits.setIfMissing || {}).forEach(([k, v]) => {
      if (!(k in result)) result[k] = v;
    });
    (edits.del || []).forEach(k => { delete result[k]; });
    const changed = Object.keys({ ...tags, ...result }).some(k => tags[k] !== result[k]);
    return changed ? result : null;
  },

  _setTagsOnNode(element, newTags) {
    element.node.querySelectorAll(':scope > tag').forEach(tag => tag.remove());
    Object.entries(newTags).forEach(([k, v]) => {
      const tag = element.doc.createElement('tag');
      tag.setAttribute('k', k);
      tag.setAttribute('v', this.truncateTag(v));
      element.node.appendChild(tag);
    });
  },

  async openChangeset(comment, source) {
    const tags = {
      created_by: CHANGESET_CREATED_BY,
      comment: this.truncateTag(comment),
      hashtags: CHANGESET_HASHTAGS
    };
    if (source) tags.source = this.truncateTag(source);
    const tagXml = Object.entries(tags)
      .map(([k, v]) => `    <tag k="${this._escapeXml(k)}" v="${this._escapeXml(v)}"/>`).join('\n');
    const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Saudi Places of Worship Map">\n  <changeset>\n${tagXml}\n  </changeset>\n</osm>`;
    return (await this._request('PUT', 'changeset/create', xml)).trim();
  },

  async closeChangeset(changesetId) {
    try {
      await this._request('PUT', `changeset/${changesetId}/close`);
    } catch (err) {
      console.warn('Failed to close changeset cleanly:', err);
    }
  },

  async _uploadElement(changesetId, type, id, element, newTags) {
    this._setTagsOnNode(element, newTags);
    element.node.setAttribute('changeset', changesetId);
    const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Saudi Places of Worship Map">\n${new XMLSerializer().serializeToString(element.node)}\n</osm>`;
    return Number((await this._request('PUT', `${type}/${id}`, xml)).trim());
  },

  /**
   * Creates a brand new node inside an open changeset. Returns the new node ID.
   */
  async createNode(changesetId, { lat, lon, tags }) {
    const latNum = Number(lat);
    const lonNum = Number(lon);
    if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) {
      throw new Error(`Invalid coordinates: lat=${lat}, lon=${lon}`);
    }
    const tagLines = Object.entries(tags || {})
      .filter(([_, v]) => v !== undefined && v !== null && String(v).trim() !== '')
      .map(([k, v]) => `    <tag k="${this._escapeXml(k)}" v="${this._escapeXml(this.truncateTag(v))}"/>`)
      .join('\n');
    const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Saudi Places of Worship Map">\n  <node changeset="${this._escapeXml(changesetId)}" lat="${latNum.toFixed(7)}" lon="${lonNum.toFixed(7)}">\n${tagLines}\n  </node>\n</osm>`;
    const responseText = await this._request('PUT', 'node/create', xml);
    return Number(responseText.trim());
  },

  /**
   * Creates a new node in its own changeset, reports it, and records it in local EditHistory.
   */
  async addNode({ lat, lon, tags, comment, source }) {
    if (!this.canEdit()) throw new Error('NOT_AUTHENTICATED');
    let changesetId = null;
    try {
      changesetId = await this.openChangeset(comment, source);
      const nodeId = await this.createNode(changesetId, { lat, lon, tags });
      trackEvent('Node created', { type: 'mosque', nodeId });
      EditHistory.add({
        changesetId,
        timestamp: Date.now(),
        user: this.userName(),
        environment: this.environment(),
        comment: this.truncateTag(comment),
        items: [{
          ref: `node/${nodeId}`,
          label: tags.name || tags['name:ar'] || tags['name:en'] || 'Mosque',
          version: 1,
          summary: `Created node/${nodeId} (${tags.amenity || 'place_of_worship'})`,
          wikidata: tags.wikidata || ''
        }]
      });
      return { changesetId, nodeId };
    } finally {
      if (changesetId) {
        await this.closeChangeset(changesetId);
        // The backend verifies against OSM that the changeset is closed, so
        // report only after closing (reporting earlier was always rejected).
        await this.reportEdit(changesetId);
      }
    }
  },

  /**
   * Applies tag edits to several elements in ONE changeset (one element is
   * just a batch of one). Each item: { type, id, edits, expectedVersion,
   * label }. Items whose element changed since expectedVersion are skipped
   * with status "conflict" unless item.force is set; items the edit would
   * not change are skipped as "unchanged". The changeset is always closed.
   */
  async applyEdits(items, { comment, source, onProgress, deferReport = false } = {}) {
    if (!this.canEdit()) throw new Error('NOT_AUTHENTICATED');
    // Several queued fixes for one element (e.g. name:en + denomination) are
    // uploaded together: after the first PUT the element's version moves on,
    // so a second PUT built from the old snapshot would conflict with itself.
    const results = items.map(item => ({ ...item, status: 'pending' }));
    const groups = new Map();
    items.forEach((item, i) => {
      const key = `${item.type}/${item.id}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(i);
    });
    let changesetId = null;
    try {
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const group = groups.get(`${item.type}/${item.id}`);
        if (group[0] !== i) continue; // filled in from the group's first item below
        const result = results[i];
        const edits = group.length > 1 ? this.mergeEdits(group.map(j => items[j].edits)) : item.edits;
        const force = group.some(j => items[j].force);
        if (onProgress) onProgress({ current: i + 1, total: items.length, item });
        try {
          const element = await this.fetchElement(item.type, item.id);
          result.oldTags = element.tags;
          if (item.expectedVersion && element.version !== item.expectedVersion && !force) {
            result.status = 'conflict';
            result.currentVersion = element.version;
            continue;
          }
          const newTags = this.applyEditsToTags(element.tags, edits);
          if (!newTags) {
            result.status = 'unchanged';
            continue;
          }
          if (!changesetId) changesetId = await this.openChangeset(comment, source);
          result.newVersion = await this._uploadElement(changesetId, item.type, item.id, element, newTags);
          result.newTags = newTags;
          result.status = 'success';
        } catch (err) {
          if (err.message === 'AUTH_EXPIRED') throw err;
          if (err.message.startsWith('VERSION_CONFLICT')) {
            result.status = 'conflict';
          } else {
            result.status = 'error';
            result.error = err.message;
          }
        }
        // Be gentle with the API between elements.
        if (i < items.length - 1) await new Promise(r => setTimeout(r, 120));
      }
      groups.forEach(group => {
        const first = results[group[0]];
        group.slice(1).forEach(j => {
          const { status, oldTags, newTags, newVersion, currentVersion, error } = first;
          Object.assign(results[j], { status, oldTags, newTags, newVersion, currentVersion, error });
        });
      });
    } finally {
      if (changesetId) await this.closeChangeset(changesetId);
    }

    if (changesetId) {
      trackEvent('Fix uploaded', { objects: results.filter(r => r.status === 'success').length });
      // deferReport: the caller saves its review marks first, then calls reportEdit().
      if (!deferReport) this.reportEdit(changesetId);
      EditHistory.add({
        changesetId,
        timestamp: Date.now(),
        user: this.userName(),
        environment: this.environment(),
        comment: this.truncateTag(comment),
        items: this.historyItems(results)
      });
    }
    return { changesetId, results };
  },

  // One history row per element, joining the summaries of its merged fixes.
  historyItems(results) {
    const byRef = new Map();
    results.filter(r => r.status === 'success').forEach(r => {
      const ref = `${r.type}/${r.id}`;
      const existing = byRef.get(ref);
      if (existing) {
        if (r.summary && !existing.summary.includes(r.summary)) existing.summary += `; ${r.summary}`;
      } else {
        byRef.set(ref, { ref, label: r.label || '', version: r.newVersion, summary: r.summary || '' });
      }
    });
    return [...byRef.values()];
  },

  async reportEdit(changesetId) {
    try {
      await fetch('/api/v1/edits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Manara-CSRF': '1' },
        body: JSON.stringify({ changeset_id: Number(changesetId) }),
      });
    } catch (e) {
      console.warn('Could not report edit to backend:', e);
    }
  },

  changesetUrl(changesetId) {
    return `${this.urls().site}/changeset/${changesetId}`;
  },

  nodeUrl(nodeId) {
    return `${this.urls().site}/node/${nodeId}`;
  },

  elementUrl(type, id) {
    return `${this.urls().site}/${type}/${id}`;
  }
};

// Local record of changesets made from this browser (most recent first).
export const EditHistory = {
  KEY: 'gcc_edit_history',
  MAX: 300,

  list() {
    try {
      return JSON.parse(localStorage.getItem(this.KEY)) || [];
    } catch (e) {
      return [];
    }
  },

  add(record) {
    const all = [record, ...this.list()].slice(0, this.MAX);
    try {
      localStorage.setItem(this.KEY, JSON.stringify(all));
    } catch (e) {
      // Ignore storage errors in private browsing
    }
    document.dispatchEvent(new CustomEvent('gcc-history-updated'));
  },

  clear() {
    localStorage.removeItem(this.KEY);
    document.dispatchEvent(new CustomEvent('gcc-history-updated'));
  }
};
