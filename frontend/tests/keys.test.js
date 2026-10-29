import { describe, expect, it } from 'vitest';
import { shortcutKey } from '../src/keys.js';

describe('shortcutKey', () => {
  it('uses Latin letters and digits as typed', () => {
    expect(shortcutKey({ key: 'n', code: 'KeyN' })).toBe('n');
    expect(shortcutKey({ key: 'N', code: 'KeyN', shiftKey: true })).toBe('n');
    expect(shortcutKey({ key: '2', code: 'Digit2' })).toBe('2');
  });

  it('keeps the typed letter on non-QWERTY Latin layouts', () => {
    // AZERTY: the key in the Q position types "a".
    expect(shortcutKey({ key: 'a', code: 'KeyQ' })).toBe('a');
  });

  it('falls back to the physical key with the Arabic layout', () => {
    expect(shortcutKey({ key: 'ى', code: 'KeyN' })).toBe('n');
    expect(shortcutKey({ key: 'ح', code: 'KeyP' })).toBe('p');
    expect(shortcutKey({ key: 'ب', code: 'KeyF' })).toBe('f');
    expect(shortcutKey({ key: 'لا', code: 'KeyB' })).toBe('b');
  });

  it('maps Arabic-Indic and Persian digits', () => {
    expect(shortcutKey({ key: '١', code: 'Digit1' })).toBe('1');
    expect(shortcutKey({ key: '۳', code: 'Digit3' })).toBe('3');
    expect(shortcutKey({ key: '٢', code: 'Numpad2' })).toBe('2');
  });

  it('recognises the help key in both scripts', () => {
    expect(shortcutKey({ key: '?', code: 'Slash', shiftKey: true })).toBe('?');
    expect(shortcutKey({ key: '؟', code: 'Slash', shiftKey: true })).toBe('?');
  });

  it('returns named keys unchanged', () => {
    expect(shortcutKey({ key: 'Escape', code: 'Escape' })).toBe('Escape');
    expect(shortcutKey({ key: 'ArrowDown', code: 'ArrowDown' })).toBe('ArrowDown');
  });
});
