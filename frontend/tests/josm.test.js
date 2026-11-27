import { describe, it, expect, vi } from 'vitest';
import '../src/translations.js';
import { t, TRANSLATIONS } from '../src/i18n.js';
import { sendJosmCommand, JOSM_ORIGINS } from '../src/josm.js';

describe('JOSM Remote Control helper & translations', () => {
  it('registers josmUnreachable in core translations for both Arabic and English', () => {
    expect(t('josmUnreachable')).not.toBe('josmUnreachable');
    expect(TRANSLATIONS.ar.josmUnreachable).toContain('JOSM');
    expect(TRANSLATIONS.en.josmUnreachable).toContain('Remote Control');
  });

  it('succeeds directly on HTTP port 8111 when reachable', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const res = await sendJosmCommand('/load_and_zoom?left=1&right=2&top=3&bottom=4', { fetchImpl });

    expect(res).toEqual({
      ok: true,
      reachable: true,
      status: 200,
      origin: JOSM_ORIGINS[0],
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith('http://127.0.0.1:8111/load_and_zoom?left=1&right=2&top=3&bottom=4');
  });

  it('does not retry HTTPS port when JOSM responds with an HTTP error', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    const res = await sendJosmCommand('/add_node?lon=46&lat=24', { fetchImpl });

    expect(res).toEqual({
      ok: false,
      reachable: true,
      status: 403,
      origin: JOSM_ORIGINS[0],
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('falls back to HTTPS port 8112 when HTTP port 8111 fails with a network error', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ ok: true, status: 200 });

    const res = await sendJosmCommand('http://127.0.0.1:8111/load_and_zoom?left=1', { fetchImpl });

    expect(res).toEqual({
      ok: true,
      reachable: true,
      status: 200,
      origin: JOSM_ORIGINS[1],
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(fetchImpl).toHaveBeenNthCalledWith(1, 'http://127.0.0.1:8111/load_and_zoom?left=1');
    expect(fetchImpl).toHaveBeenNthCalledWith(2, 'https://127.0.0.1:8112/load_and_zoom?left=1');
  });

  it('reports unreachable when both HTTP and HTTPS ports fail', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const res = await sendJosmCommand('/load_object?objects=w123', { fetchImpl });

    expect(res).toEqual({
      ok: false,
      reachable: false,
      status: 0,
      origin: null,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
