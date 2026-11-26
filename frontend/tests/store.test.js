import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getState,
  setState,
  subscribe,
  setMode,
  setFilter,
  resetFilters,
  setSelection,
  clearSelection,
  resetStore,
} from '../src/store.js';
import { modeManager, createMode, MODES } from '../src/modes.js';

describe('Store & Modes state management', () => {
  beforeEach(() => {
    resetStore();
  });

  it('initializes with default state', () => {
    const s = getState();
    expect(s.currentMode).toBe('poi');
    expect(s.filters.religion).toBe('all');
    expect(s.filters.improvement).toBe('all');
    expect(s.selection).toBeNull();
  });

  it('updates mode and notifies subscribers', () => {
    const sub = vi.fn();
    const unsub = subscribe(sub);

    setMode('improve');
    expect(getState().currentMode).toBe('improve');
    expect(sub).toHaveBeenCalledWith(expect.any(Object), 'currentMode');

    unsub();
  });

  it('updates filters independently and resets them', () => {
    setFilter('religion', 'muslim');
    setFilter('improvement', 'missing_name_en');

    expect(getState().filters.religion).toBe('muslim');
    expect(getState().filters.improvement).toBe('missing_name_en');

    resetFilters();
    expect(getState().filters.religion).toBe('all');
    expect(getState().filters.improvement).toBe('all');
  });

  it('handles selection lifecycle', () => {
    const place = { properties: { osm_id: 123 }, lat: 24.7, lon: 46.7 };
    setSelection(place);
    expect(getState().selection).toEqual(place);

    clearSelection();
    expect(getState().selection).toBeNull();
  });

  it('runs enter and exit hooks during mode transitions', async () => {
    const exitPoi = vi.fn();
    const enterQa = vi.fn();

    const poiMode = createMode({
      id: MODES.POI,
      name_ar: 'الخريطة',
      name_en: 'Map',
      exit: exitPoi,
    });

    const qaMode = createMode({
      id: MODES.QA,
      name_ar: 'فحص الجودة',
      name_en: 'QA',
      enter: enterQa,
    });

    modeManager.register(poiMode);
    modeManager.register(qaMode);

    // Initial transition to POI
    await modeManager.transitionTo(MODES.POI);
    expect(modeManager.getActiveMode().id).toBe(MODES.POI);
    expect(exitPoi).not.toHaveBeenCalled();

    // Transition from POI to QA
    await modeManager.transitionTo(MODES.QA);
    expect(exitPoi).toHaveBeenCalledTimes(1);
    expect(enterQa).toHaveBeenCalledTimes(1);
    expect(modeManager.getActiveMode().id).toBe(MODES.QA);
    expect(getState().currentMode).toBe(MODES.QA);
  });
});
