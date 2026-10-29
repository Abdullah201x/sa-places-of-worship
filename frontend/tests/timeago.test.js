import { describe, expect, it } from 'vitest';
import { DATA_AGE_OK_MS, DATA_AGE_WARN_MS, ageLevel, clockOffset, formatAge } from '../src/timeago.js';

const MIN = 60 * 1000;
const HOUR = 60 * MIN;

describe('formatAge', () => {
  it('uses compact English units', () => {
    expect(formatAge(30 * 1000, 'en')).toBe('now');
    expect(formatAge(5 * MIN, 'en')).toBe('5m');
    expect(formatAge(20 * HOUR + 59 * MIN, 'en')).toBe('20h');
    expect(formatAge(47 * HOUR, 'en')).toBe('47h');
    expect(formatAge(50 * HOUR, 'en')).toBe('2d');
  });

  it('uses compact Arabic units with the given number format', () => {
    expect(formatAge(30 * 1000, 'ar')).toBe('الآن');
    expect(formatAge(20 * HOUR, 'ar')).toBe('20 س');
    expect(formatAge(5 * MIN, 'ar', n => `<${n}>`)).toBe('<5> د');
    expect(formatAge(72 * HOUR, 'ar')).toBe('3 ي');
  });

  it('treats a future time (clock skew) as now', () => {
    expect(formatAge(-5 * MIN, 'en')).toBe('now');
  });
});

describe('ageLevel', () => {
  it('splits ok, warn and stale at the data thresholds', () => {
    expect(ageLevel(20 * HOUR, DATA_AGE_OK_MS, DATA_AGE_WARN_MS)).toBe('ok');
    expect(ageLevel(40 * HOUR, DATA_AGE_OK_MS, DATA_AGE_WARN_MS)).toBe('warn');
    expect(ageLevel(72 * HOUR, DATA_AGE_OK_MS, DATA_AGE_WARN_MS)).toBe('stale');
  });
});

describe('clockOffset', () => {
  it('measures the browser clock against the server Date header', () => {
    const local = Date.parse('2026-10-30T00:00:00Z');
    expect(clockOffset('Fri, 30 Oct 2026 01:00:00 GMT', local)).toBe(HOUR);
  });

  it('is zero without a usable header', () => {
    expect(clockOffset(null, 0)).toBe(0);
    expect(clockOffset('garbage', 0)).toBe(0);
  });
});
