// Manara Mode System (iD-style state machine with enter/exit hooks)
import { setMode } from './store.js';

export const MODES = {
  POI: 'poi',
  GAP: 'gap',
  IMPROVE: 'improve',
  QA: 'qa',
};

class ModeManager {
  constructor() {
    this.currentMode = null;
    this.modes = new Map();
    this.context = {};
  }

  setContext(context) {
    this.context = { ...this.context, ...context };
  }

  register(modeObj) {
    this.modes.set(modeObj.id, modeObj);
  }

  get(id) {
    return this.modes.get(id);
  }

  getActiveMode() {
    return this.currentMode;
  }

  async transitionTo(newModeId) {
    if (this.currentMode && this.currentMode.id === newModeId) {
      return this.currentMode;
    }

    const nextMode = this.modes.get(newModeId);
    if (!nextMode) {
      console.warn(`Mode ${newModeId} not registered`);
      return null;
    }

    if (this.currentMode && typeof this.currentMode.exit === 'function') {
      try {
        await this.currentMode.exit(this.context);
      } catch (err) {
        console.error(`Error exiting mode ${this.currentMode.id}:`, err);
      }
    }

    const prevMode = this.currentMode;
    this.currentMode = nextMode;
    setMode(newModeId);

    if (typeof nextMode.enter === 'function') {
      try {
        await nextMode.enter(this.context, prevMode ? prevMode.id : null);
      } catch (err) {
        console.error(`Error entering mode ${newModeId}:`, err);
      }
    }

    return nextMode;
  }
}

export const modeManager = new ModeManager();

export function createMode(def) {
  return {
    id: def.id,
    name_ar: def.name_ar || def.id,
    name_en: def.name_en || def.id,
    enter: def.enter || (() => {}),
    exit: def.exit || (() => {}),
  };
}
