// Live Duplicate POI Inspector & Diff (OSM API 0.6)
// Fetches the live building and inner node from OpenStreetMap on-demand when a place
// with duplicate_poi / poi_node_id is inspected. Zero background polling; strictly cached
// in sessionStorage for OSM API Acceptable Use Policy compliance.

import { escapeHtml } from './escape.js';
import { addTranslations, t, currentLang, fmtDate } from './i18n.js';
import { OsmApi } from './osm_api.js';
import { ReviewMarks, refreshAfterReviewChange } from './review.js';

addTranslations({
  dupInspectorTitle: ['🔍 الفحص المباشر للازدواجية (OSM Live Diff)', '🔍 Live Duplicate Diff (OSM API)'],
  dupInspectorLoading: ['جارٍ فحص خادم خريطة الشارع المفتوحة مباشرة...', 'Fetching live elements from OpenStreetMap...'],
  dupInspectorError: ['تعذر جلب البيانات المباشرة من خادم OSM.', 'Could not fetch live elements from OSM.'],
  dupNodeGone: ['✅ النقطة المكررة تم حذفها بالفعل على OSM!', '✅ The duplicate node is already deleted on OSM!'],
  dupNodeGoneDesc: ['تم حل هذا التكرار مسبقاً من قِبل مجتمع OSM. يمكنك تحديث الحالة محلياً لإخفاء التنبيه.', 'This duplicate was already resolved on OSM by the community. You can mark it fixed locally.'],
  dupMarkFixed: ['تحديث الحالة محلياً إلى تم الحل ✓', 'Mark as Resolved Locally ✓'],
  dupRelationAlert: ['⚠️ تحذير: النقطة جزء من {n} علاقة (Relation) على OSM!', '⚠️ Warning: Node belongs to {n} relation(s) on OSM!'],
  dupRelationDesc: ['حذف هذه النقطة سيتسبب في كسر علاقات على الخريطة! لا يجوز حذفها تلقائياً، بل يجب فحصها ومعالجتها يدوياً عبر JOSM.', 'Deleting this node will break OSM relations! Do not delete mechanically; inspect and fix relations manually via JOSM.'],
  dupDistinctPoi: ['💡 تنبيه: النقطة قد تمثل مصلى فرعياً أو قسماً مخصصاً (مثل مصلى النساء)', '💡 Notice: Node may represent an indoor sub-facility (e.g. musalla/women prayer hall)'],
  dupDistinctPoiDesc: ['النقطة تحمل وسوماً خاصة تختلف عن المبنى. يُفضّل الإبقاء عليها كمعلم داخلي وإزالة وسم دار العبادة العام من المبنى إن لم يكن مسجداً مستقلاً.', 'The node carries distinct tags. Keep it as an indoor POI and adjust the building tagging if appropriate.'],
  dupTrueDuplicate: ['💡 توصية: كلا العنصرين يمثلان نفس المسجد تماماً', '💡 Recommendation: Both elements represent the exact same mosque'],
  dupTrueDuplicateDesc: ['يُنصح بفتح المعلمين معاً في JOSM، ودمج أي وسوم إضافية على المبنى، ثم حذف النقطة بأمان.', 'Open both in JOSM, transfer missing tags to the building, and delete the redundant node safely.'],
  dupOpenJosm: ['تعديل المعلمين معاً في JOSM ↗', 'Edit both in JOSM ↗'],
  dupViewNode: ['عرض النقطة على OSM ↗', 'View Node on OSM ↗'],
  dupViewWay: ['عرض المبنى على OSM ↗', 'View Building on OSM ↗'],
  dupTagDiff: ['مقارنة الوسوم التفصيلية', 'Detailed Tag Comparison'],
  dupTagKey: ['الوسم (Key)', 'Tag Key'],
  dupBuildingVal: ['المبنى (Building)', 'Building Outline'],
  dupNodeVal: ['النقطة (Node)', 'Inner Node'],
  dupRefetch: ['إعادة الفحص المباشر 🔄', 'Re-fetch Live 🔄'],
  dupVersion: ['الإصدار', 'Version'],
  dupLastEdit: ['آخر تعديل', 'Last edit'],
  dupNoTags: ['(لا توجد وسوم)', '(no tags)'],
  dupMissing: ['(غير موجود)', '(missing)'],
  dupDiffSummary: ['{total} وسماً: {matching} متطابقة، {conflicts} متعارضة، {nodeOnly} خاصة بالنقطة', '{total} tags: {matching} matching, {conflicts} different, {nodeOnly} node-only'],
});

/**
 * Fetch a single live element (JSON) from OSM API 0.6 with sessionStorage caching.
 */
export async function fetchLiveOsmElement(type, id, apiUrl = 'https://api.openstreetmap.org') {
  const cacheKey = `live_osm_${type}_${id}`;
  try {
    if (typeof sessionStorage !== 'undefined') {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) return JSON.parse(cached);
    }
  } catch {
    // Ignore storage errors
  }

  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timeoutId = controller ? setTimeout(() => controller.abort(), 6500) : null;

  try {
    const res = await fetch(`${apiUrl}/api/0.6/${type}/${id}.json`, {
      headers: { 'Accept': 'application/json' },
      signal: controller ? controller.signal : undefined,
    });
    if (timeoutId) clearTimeout(timeoutId);
    if (res.status === 410 || res.status === 404) {
      const goneData = { gone: true, status: res.status };
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem(cacheKey, JSON.stringify(goneData));
        }
      } catch {}
      return goneData;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const el = data.elements && data.elements[0];
    if (!el || el.visible === false) {
      return { gone: true };
    }
    try {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem(cacheKey, JSON.stringify(el));
      }
    } catch {}
    return el;
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId);
    throw err;
  }
}

/**
 * Fetch relations referencing a node from OSM API 0.6 with sessionStorage caching.
 */
export async function fetchLiveNodeRelations(nodeId, apiUrl = 'https://api.openstreetmap.org') {
  const cacheKey = `live_osm_node_relations_${nodeId}`;
  try {
    if (typeof sessionStorage !== 'undefined') {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) return JSON.parse(cached);
    }
  } catch {
    // Ignore storage errors
  }

  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timeoutId = controller ? setTimeout(() => controller.abort(), 6500) : null;

  try {
    const res = await fetch(`${apiUrl}/api/0.6/node/${nodeId}/relations.json`, {
      headers: { 'Accept': 'application/json' },
      signal: controller ? controller.signal : undefined,
    });
    if (timeoutId) clearTimeout(timeoutId);
    if (res.status === 410 || res.status === 404) return [];
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const rels = Array.isArray(data.elements) ? data.elements : [];
    try {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem(cacheKey, JSON.stringify(rels));
      }
    } catch {}
    return rels;
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId);
    return [];
  }
}

/**
 * Analyze the tag difference and structural relationship between the building and node.
 */
export function analyzeDuplicatePair(wayEl, nodeEl, relations = []) {
  if (!nodeEl || nodeEl.gone) {
    return {
      status: 'resolved',
      isNodeGone: true,
      relations: [],
      tagsDiff: [],
      conflictsCount: 0,
      nodeOnlyCount: 0,
      matchingCount: 0,
    };
  }

  const wayTags = wayEl && !wayEl.gone ? (wayEl.tags || {}) : {};
  const nodeTags = nodeEl.tags || {};

  // Check if either object is no longer tagged as place of worship
  const wayIsWorship = wayTags.amenity === 'place_of_worship' || wayTags.amenity === 'mosque';
  const nodeIsWorship = nodeTags.amenity === 'place_of_worship' || nodeTags.amenity === 'mosque';

  if (!wayIsWorship || !nodeIsWorship) {
    return {
      status: 'resolved',
      isNodeGone: false,
      isRetagged: true,
      relations,
      tagsDiff: [],
      conflictsCount: 0,
      nodeOnlyCount: 0,
      matchingCount: 0,
    };
  }

  // Relations hazard check
  const hasRelations = Array.isArray(relations) && relations.length > 0;

  // Distinct POI check (e.g. musalla, female prayer room, or distinctly different name)
  const isMusalla = nodeTags.place_of_worship === 'musalla';
  const hasFemaleTag = !!(nodeTags['female:prayer_room'] || nodeTags.female);
  const nodeName = String(nodeTags.name || nodeTags['name:ar'] || '').trim();
  const wayName = String(wayTags.name || wayTags['name:ar'] || '').trim();
  const nameSuggestsMusalla = /مصلى|نساء/i.test(nodeName) && !/مصلى|نساء/i.test(wayName);
  const isDistinct = isMusalla || hasFemaleTag || nameSuggestsMusalla;

  // Compile detailed tag diff
  const allKeys = [...new Set([...Object.keys(wayTags), ...Object.keys(nodeTags)])].sort((a, b) => {
    // Prioritize name and classification tags at the top
    const prio = ['name', 'name:ar', 'name:en', 'amenity', 'building', 'religion', 'denomination', 'female:prayer_room', 'wheelchair'];
    const pa = prio.indexOf(a);
    const pb = prio.indexOf(b);
    if (pa !== -1 && pb !== -1) return pa - pb;
    if (pa !== -1) return -1;
    if (pb !== -1) return 1;
    return a.localeCompare(b);
  });

  let conflictsCount = 0;
  let nodeOnlyCount = 0;
  let matchingCount = 0;

  const tagsDiff = allKeys.map(k => {
    const inWay = k in wayTags;
    const inNode = k in nodeTags;
    const wayVal = wayTags[k];
    const nodeVal = nodeTags[k];

    let type = 'matching';
    if (inWay && inNode) {
      if (wayVal === nodeVal) {
        type = 'matching';
        matchingCount++;
      } else {
        type = 'conflict';
        conflictsCount++;
      }
    } else if (inNode && !inWay) {
      type = 'node_only';
      nodeOnlyCount++;
    } else {
      type = 'way_only';
    }

    return { key: k, wayVal, nodeVal, type };
  });

  let status = 'true_duplicate';
  if (hasRelations) {
    status = 'relation_hazard';
  } else if (isDistinct) {
    status = 'distinct_poi';
  }

  return {
    status,
    isNodeGone: false,
    relations,
    tagsDiff,
    conflictsCount,
    nodeOnlyCount,
    matchingCount,
  };
}

/**
 * Render the Live Duplicate Inspector into the details panel.
 */
export async function renderDuplicateInspector(containerEl, props, lat, lon) {
  if (!containerEl) return;
  if (!props || !props.poi_node_id) {
    containerEl.style.display = 'none';
    containerEl.innerHTML = '';
    return;
  }

  containerEl.style.display = 'block';

  // Loading state
  containerEl.innerHTML = `
    <div class="duplicate-inspector-card loading">
      <div class="dup-loading-spinner"></div>
      <span>${t('dupInspectorLoading')}</span>
    </div>
  `;

  const wayType = props.osm_type || (props.geom_type === 'Point' ? 'node' : 'way');
  const wayId = props.osm_id;
  const nodeId = props.poi_node_id;
  const apiUrl = (OsmApi && typeof OsmApi.urls === 'function') ? OsmApi.urls().api : 'https://api.openstreetmap.org';
  const siteUrl = (OsmApi && typeof OsmApi.urls === 'function') ? OsmApi.urls().site : 'https://www.openstreetmap.org';

  try {
    const [wayRes, nodeRes, relsRes] = await Promise.allSettled([
      fetchLiveOsmElement(wayType, wayId, apiUrl),
      fetchLiveOsmElement('node', nodeId, apiUrl),
      fetchLiveNodeRelations(nodeId, apiUrl),
    ]);

    const wayEl = wayRes.status === 'fulfilled' ? wayRes.value : null;
    const nodeEl = nodeRes.status === 'fulfilled' ? nodeRes.value : null;
    const rels = relsRes.status === 'fulfilled' ? relsRes.value : [];

    const analysis = analyzeDuplicatePair(wayEl, nodeEl, rels);
    renderAnalysisView(containerEl, props, lat, lon, { wayEl, nodeEl, analysis, siteUrl });
  } catch (err) {
    console.warn('Failed to inspect live duplicate:', err);
    containerEl.innerHTML = `
      <div class="duplicate-inspector-card error">
        <div class="dup-error-msg">⚠️ ${t('dupInspectorError')} (${escapeHtml(err.message)})</div>
        <button type="button" class="dup-action-btn refetch" id="btn-dup-retry">
          ${t('dupRefetch')}
        </button>
      </div>
    `;
    const retryBtn = containerEl.querySelector('#btn-dup-retry');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        try {
          sessionStorage.removeItem(`live_osm_${wayType}_${wayId}`);
          sessionStorage.removeItem(`live_osm_node_${nodeId}`);
          sessionStorage.removeItem(`live_osm_node_relations_${nodeId}`);
        } catch {}
        renderDuplicateInspector(containerEl, props, lat, lon);
      });
    }
  }
}

function renderAnalysisView(containerEl, props, lat, lon, { wayEl, nodeEl, analysis, siteUrl }) {
  const isAr = currentLang === 'ar';
  const wayType = props.osm_type || 'way';
  const wayId = props.osm_id;
  const nodeId = props.poi_node_id;

  let bannerClass = 'info';
  let bannerTitle = '';
  let bannerDesc = '';
  let showMarkFixedBtn = false;

  if (analysis.status === 'resolved') {
    bannerClass = 'success';
    bannerTitle = t('dupNodeGone');
    bannerDesc = t('dupNodeGoneDesc');
    showMarkFixedBtn = true;
  } else if (analysis.status === 'relation_hazard') {
    bannerClass = 'hazard';
    bannerTitle = t('dupRelationAlert', { n: analysis.relations.length });
    bannerDesc = t('dupRelationDesc');
  } else if (analysis.status === 'distinct_poi') {
    bannerClass = 'notice';
    bannerTitle = t('dupDistinctPoi');
    bannerDesc = t('dupDistinctPoiDesc');
  } else {
    bannerClass = 'guidance';
    bannerTitle = t('dupTrueDuplicate');
    bannerDesc = t('dupTrueDuplicateDesc');
  }

  // Relations list HTML
  let relationsHtml = '';
  if (analysis.relations && analysis.relations.length > 0) {
    relationsHtml = `
      <div class="dup-relations-list">
        <strong>${isAr ? 'العلاقات المرتبطة بالنقطة:' : 'Relations containing this node:'}</strong>
        ${analysis.relations.map(r => `
          <a href="${siteUrl}/relation/${r.id}" target="_blank" rel="noopener noreferrer" class="dup-rel-link">
            #${r.id} (${r.tags && r.tags.type ? r.tags.type : 'relation'})
          </a>
        `).join(', ')}
      </div>
    `;
  }

  // Tag Diff Table rows
  const tagRowsHtml = analysis.tagsDiff.map(row => {
    let rowBadgeClass = 'matching';
    let rowBadgeText = '=';
    if (row.type === 'conflict') {
      rowBadgeClass = 'conflict';
      rowBadgeText = '≠';
    } else if (row.type === 'node_only') {
      rowBadgeClass = 'node-only';
      rowBadgeText = '+ Node';
    } else if (row.type === 'way_only') {
      rowBadgeClass = 'way-only';
      rowBadgeText = '+ Way';
    }

    return `
      <tr class="dup-diff-row ${rowBadgeClass}">
        <td class="dup-col-key">
          <span class="dup-key-name">${escapeHtml(row.key)}</span>
          <span class="dup-diff-badge ${rowBadgeClass}">${rowBadgeText}</span>
        </td>
        <td class="dup-col-val way-val ${!row.wayVal ? 'empty' : ''}">
          ${row.wayVal ? escapeHtml(row.wayVal) : `<span class="val-missing">${t('dupMissing')}</span>`}
        </td>
        <td class="dup-col-val node-val ${!row.nodeVal ? 'empty' : ''}">
          ${row.nodeVal ? escapeHtml(row.nodeVal) : `<span class="val-missing">${t('dupMissing')}</span>`}
        </td>
      </tr>
    `;
  }).join('');

  const wayMeta = wayEl && !wayEl.gone ? {
    v: wayEl.version,
    user: wayEl.user || '?',
    date: wayEl.timestamp ? fmtDate(wayEl.timestamp) : '-'
  } : null;

  const nodeMeta = nodeEl && !nodeEl.gone ? {
    v: nodeEl.version,
    user: nodeEl.user || '?',
    date: nodeEl.timestamp ? fmtDate(nodeEl.timestamp) : '-'
  } : null;

  containerEl.innerHTML = `
    <div class="duplicate-inspector-card">
      <div class="dup-card-header">
        <h4 class="dup-card-title">${t('dupInspectorTitle')}</h4>
        <button type="button" class="dup-btn-refetch" id="btn-dup-refetch" title="${t('dupRefetch')}">🔄</button>
      </div>

      <!-- Live Diagnosis Banner -->
      <div class="dup-diagnosis-banner ${bannerClass}">
        <div class="dup-banner-title">${bannerTitle}</div>
        <div class="dup-banner-desc">${bannerDesc}</div>
        ${relationsHtml}
        ${showMarkFixedBtn ? `
          <button type="button" class="dup-action-btn resolve" id="btn-dup-mark-fixed">
            ${t('dupMarkFixed')}
          </button>
        ` : ''}
      </div>

      <!-- Metadata summary -->
      <div class="dup-meta-grid">
        <div class="dup-meta-col way">
          <div class="dup-meta-title">
            <span>🏛️ ${isAr ? 'المبنى' : 'Building'} (${wayType}/${wayId})</span>
            <a href="${siteUrl}/${wayType}/${wayId}" target="_blank" rel="noopener noreferrer">↗</a>
          </div>
          ${wayMeta ? `
            <div class="dup-meta-info">${t('dupVersion')} ${wayMeta.v} • ${wayMeta.user} • ${wayMeta.date}</div>
          ` : `<div class="dup-meta-info gone">${t('dupMissing')}</div>`}
        </div>

        <div class="dup-meta-col node">
          <div class="dup-meta-title">
            <span>📍 ${isAr ? 'النقطة' : 'Node'} (node/${nodeId})</span>
            <a href="${siteUrl}/node/${nodeId}" target="_blank" rel="noopener noreferrer">↗</a>
          </div>
          ${nodeMeta ? `
            <div class="dup-meta-info">${t('dupVersion')} ${nodeMeta.v} • ${nodeMeta.user} • ${nodeMeta.date}</div>
          ` : `<div class="dup-meta-info gone">❌ ${isAr ? 'محذوفة' : 'Deleted'}</div>`}
        </div>
      </div>

      <!-- Tag Diff Table -->
      ${analysis.tagsDiff.length > 0 ? `
        <div class="dup-diff-table-wrapper">
          <div class="dup-diff-header">
            <span>${t('dupTagDiff')}</span>
            <span class="dup-diff-summary">
              ${t('dupDiffSummary', {
                total: analysis.tagsDiff.length,
                matching: analysis.matchingCount,
                conflicts: analysis.conflictsCount,
                nodeOnly: analysis.nodeOnlyCount
              })}
            </span>
          </div>
          <table class="dup-diff-table">
            <thead>
              <tr>
                <th>${t('dupTagKey')}</th>
                <th>${t('dupBuildingVal')}</th>
                <th>${t('dupNodeVal')}</th>
              </tr>
            </thead>
            <tbody>
              ${tagRowsHtml}
            </tbody>
          </table>
        </div>
      ` : ''}

      <!-- Action Footer -->
      <div class="dup-card-actions">
        <button type="button" class="dup-action-btn josm" id="btn-dup-josm">
          <span>⚡ ${t('dupOpenJosm')}</span>
        </button>
      </div>
    </div>
  `;

  // Attach event handlers
  const refetchBtn = containerEl.querySelector('#btn-dup-refetch');
  if (refetchBtn) {
    refetchBtn.addEventListener('click', () => {
      try {
        sessionStorage.removeItem(`live_osm_${wayType}_${wayId}`);
        sessionStorage.removeItem(`live_osm_node_${nodeId}`);
        sessionStorage.removeItem(`live_osm_node_relations_${nodeId}`);
      } catch {}
      renderDuplicateInspector(containerEl, props, lat, lon);
    });
  }

  const markFixedBtn = containerEl.querySelector('#btn-dup-mark-fixed');
  if (markFixedBtn) {
    markFixedBtn.addEventListener('click', () => {
      ReviewMarks.set(props, 'fixed');
      refreshAfterReviewChange();
      containerEl.style.display = 'none';
    });
  }

  const josmBtn = containerEl.querySelector('#btn-dup-josm');
  if (josmBtn) {
    josmBtn.addEventListener('click', async () => {
      const select = [`${wayType}${wayId}`, `node${nodeId}`];
      const delta = 0.0015;
      const url = `http://127.0.0.1:8111/load_and_zoom?left=${lon - delta}&right=${lon + delta}&top=${lat + delta}&bottom=${lat - delta}&select=${select.join(',')}`;
      try {
        await fetch(url);
      } catch {
        window.open(`${siteUrl}/edit?editor=id&${wayType}=${wayId}`, '_blank');
      }
    });
  }
}
