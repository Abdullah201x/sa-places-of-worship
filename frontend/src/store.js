// Manara Central Observable Store
// Holds dataset state, filters, selection, and active workspace mode.

const initialState = {
  currentMode: 'poi', // 'poi' | 'gap' | 'improve' | 'qa'
  filters: {
    religion: 'all',
    improvement: 'all',
    gapUrgency: 'all',
    searchQuery: '',
    dateFrom: null,
    dateTo: null,
  },
  selection: null, // { properties, lat, lon } or null
  datasetStats: {
    totalPlaces: 0,
    visiblePlaces: 0,
    totalGaps: 0,
    visibleGaps: 0,
  },
  pendingEditsCount: 0,
};

let state = { ...initialState, filters: { ...initialState.filters } };
const listeners = new Set();

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(changedKey = null) {
  for (const listener of listeners) {
    try {
      listener(state, changedKey);
    } catch (err) {
      console.error('Store subscriber error:', err);
    }
  }
}

export function setState(updater) {
  const next = typeof updater === 'function' ? updater(state) : { ...state, ...updater };
  state = next;
  notify();
}

export function setMode(mode) {
  if (state.currentMode === mode) return;
  const prevMode = state.currentMode;
  state = { ...state, currentMode: mode };
  notify('currentMode');
  return { prevMode, currentMode: mode };
}

export function setFilter(key, value) {
  if (state.filters[key] === value) return;
  state = {
    ...state,
    filters: {
      ...state.filters,
      [key]: value,
    },
  };
  notify('filters');
}

export function resetFilters() {
  state = {
    ...state,
    filters: { ...initialState.filters },
  };
  notify('filters');
}

export function setSelection(place) {
  state = { ...state, selection: place };
  notify('selection');
}

export function clearSelection() {
  if (!state.selection) return;
  state = { ...state, selection: null };
  notify('selection');
}

export function setPendingEditsCount(count) {
  state = { ...state, pendingEditsCount: count };
  notify('pendingEditsCount');
}

export function resetStore() {
  state = { ...initialState, filters: { ...initialState.filters } };
  notify();
}
