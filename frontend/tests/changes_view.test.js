import { describe, it, expect } from 'vitest';
import {
  formatKindBadge,
  formatSourceBadge,
  formatTriageBadge,
  formatTagDiffSummary,
  buildOsmHistoryUrl,
  buildOsmchaUrl,
  buildOsmoseUrl,
} from '../src/changes_view.js';

describe('Changes & Activity Feed helpers', () => {
  it('formats kind badges in Arabic and English', () => {
    const crAr = formatKindBadge('created', 'ar');
    expect(crAr.className).toBe('kind-created');
    expect(crAr.label).toBe('إضافة جديدة');

    const crEn = formatKindBadge('created', 'en');
    expect(crEn.className).toBe('kind-created');
    expect(crEn.label).toBe('Created');

    const del = formatKindBadge('deleted', 'en');
    expect(del.className).toBe('kind-deleted');

    const upg = formatKindBadge('upgraded', 'en');
    expect(upg.className).toBe('kind-upgraded');

    const mod = formatKindBadge('modified', 'en');
    expect(mod.className).toBe('kind-modified');
  });

  it('formats source badges properly', () => {
    const live = formatSourceBadge('live', false, 'en');
    expect(live.className).toBe('src-live');
    expect(live.glyph).toBe('●');

    const daily = formatSourceBadge('daily', false, 'en');
    expect(daily.className).toBe('src-daily');
    expect(daily.glyph).toBe('◆');

    const conf = formatSourceBadge('daily', true, 'en');
    expect(conf.className).toBe('src-confirmed');
    expect(conf.glyph).toBe('✓');
  });

  it('formats triage badges in Arabic and English', () => {
    const revAr = formatTriageBadge('reviewed', 'ar');
    expect(revAr.className).toBe('triage-reviewed');
    expect(revAr.label).toBe('تمت المراجعة');

    const flagEn = formatTriageBadge('flagged', 'en');
    expect(flagEn.className).toBe('triage-flagged');
    expect(flagEn.label).toBe('Flagged');

    const unrev = formatTriageBadge(null, 'en');
    expect(unrev.className).toBe('triage-unreviewed');
    expect(unrev.label).toBe('Unreviewed');
  });

  it('formats tag diff summaries concisely', () => {
    const tagDiff = {
      modified: {
        building: { before: 'mosque', after: 'yes' },
      },
      added: {
        'name:en': 'Al Noor Mosque',
      },
      removed: {
        old_tag: 'test',
      },
    };
    const summary = formatTagDiffSummary(tagDiff);
    expect(summary).toContain('building: mosque → yes');
    expect(summary).toContain('+name:en=Al Noor Mosque');
    expect(summary).toContain('-old_tag=test');

    expect(formatTagDiffSummary(null)).toBe('–');
    expect(formatTagDiffSummary({})).toBe('–');
  });

  it('constructs correct external URLs', () => {
    // osm.org history
    expect(buildOsmHistoryUrl('way', 12345)).toBe('https://www.openstreetmap.org/way/12345/history');

    // osmcha direct changeset
    expect(buildOsmchaUrl(987654)).toBe('https://osmcha.org/changesets/987654');

    // osmcha bbox fallback
    const bboxUrl = buildOsmchaUrl(null, [46.6753, 24.7136]);
    expect(bboxUrl).toContain('in_bbox=');
    expect(bboxUrl).toContain('46.6253');

    // osmose
    const osmoseUrl = buildOsmoseUrl(24.7136, 46.6753);
    expect(osmoseUrl).toContain('osmose.openstreetmap.fr');
    expect(osmoseUrl).toContain('lat=24.71360');
    expect(osmoseUrl).toContain('lon=46.67530');
  });
});
