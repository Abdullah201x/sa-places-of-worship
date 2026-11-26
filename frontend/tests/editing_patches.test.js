import { describe, it, expect, beforeEach, vi } from 'vitest';

class MockStorage {
  constructor() {
    this._s = {};
  }
  getItem(k) { return this._s[k] ?? null; }
  setItem(k, v) { this._s[k] = String(v); }
  removeItem(k) { delete this._s[k]; }
  clear() { this._s = {}; }
}

const mockLocal = new MockStorage();
const mockSession = new MockStorage();

vi.stubGlobal('localStorage', mockLocal);
vi.stubGlobal('sessionStorage', mockSession);
vi.stubGlobal('document', {
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
});

const { EditBatch, LocalPatches } = await import('../src/editing.js');

describe('LocalPatches & Persistent Edit Queue', () => {
  beforeEach(() => {
    mockLocal.clear();
    mockSession.clear();
  });

  describe('EditBatch with Undo / Redo', () => {
    it('migrates legacy gcc_edit_batch to manara_pending_edits_v1', () => {
      const legacyItem = { type: 'way', id: 123, fixId: 'missing_name_en', edits: { 'name:en': 'Test' } };
      mockLocal.setItem('gcc_edit_batch', JSON.stringify([legacyItem]));

      const items = EditBatch.items();
      expect(items).toHaveLength(1);
      expect(items[0].id).toBe(123);
      expect(mockLocal.getItem('manara_pending_edits_v1')).toBeTruthy();
      expect(mockLocal.getItem('gcc_edit_batch')).toBeNull();
    });

    it('supports undo and redo when modifying the edit batch queue', () => {
      expect(EditBatch.canUndo()).toBe(false);
      expect(EditBatch.canRedo()).toBe(false);

      const item1 = { type: 'way', id: 1, fixId: 'fix1', edits: { 'name:en': 'One' } };
      const item2 = { type: 'way', id: 2, fixId: 'fix2', edits: { 'name:en': 'Two' } };

      EditBatch.add(item1);
      expect(EditBatch.items()).toHaveLength(1);
      expect(EditBatch.canUndo()).toBe(true);
      expect(EditBatch.canRedo()).toBe(false);

      EditBatch.add(item2);
      expect(EditBatch.items()).toHaveLength(2);

      // Undo item2
      const undone = EditBatch.undo();
      expect(undone).toBe(true);
      expect(EditBatch.items()).toHaveLength(1);
      expect(EditBatch.items()[0].id).toBe(1);
      expect(EditBatch.canRedo()).toBe(true);

      // Redo item2
      const redone = EditBatch.redo();
      expect(redone).toBe(true);
      expect(EditBatch.items()).toHaveLength(2);
      expect(EditBatch.items()[1].id).toBe(2);

      // Undo both
      EditBatch.undo();
      EditBatch.undo();
      expect(EditBatch.items()).toHaveLength(0);
      expect(EditBatch.canUndo()).toBe(false);
    });
  });

  describe('LocalPatches tag overlay & pruning', () => {
    it('sets, retrieves and overlays tag patches on a place', () => {
      LocalPatches.set('way', 555, 3, {
        name: 'جامع التقوى الجديد',
        'name:en': 'New Al-Taqwa Mosque',
        denomination: 'sunni',
        'female:prayer_room': 'yes',
      });

      const patch = LocalPatches.get('way', 555);
      expect(patch).toBeTruthy();
      expect(patch.version).toBe(3);
      expect(patch.tags['name:en']).toBe('New Al-Taqwa Mosque');

      const originalProps = {
        osm_id: 555,
        osm_type: 'way',
        name: 'جامع التقوى',
        name_en: '',
        denomination: 'unknown',
        female: '',
        version: 2,
      };

      const patched = LocalPatches.apply(originalProps);
      expect(patched._locallyPatched).toBe(true);
      expect(patched.name).toBe('جامع التقوى الجديد');
      expect(patched.name_en).toBe('New Al-Taqwa Mosque');
      expect(patched.denomination).toBe('sunni');
      expect(patched.female).toBe('yes');
      expect(patched.version).toBe(3);
    });

    it('prunes patches that are older than pbf_timestamp', () => {
      const now = Date.now();
      LocalPatches.set('way', 101, 2, { 'name:en': 'Old' });
      LocalPatches.set('way', 202, 2, { 'name:en': 'Fresh' });

      const patches = LocalPatches.all();
      patches['way/101'].uploadedAt = now - 7200000; // 2h ago
      patches['way/202'].uploadedAt = now - 600000;  // 10m ago
      mockLocal.setItem(LocalPatches.KEY, JSON.stringify(patches));

      const pbfCutoff = now - 3600000;
      LocalPatches.prune(pbfCutoff);

      expect(LocalPatches.get('way', 101)).toBeNull();
      expect(LocalPatches.get('way', 202)).toBeTruthy();
    });
  });
});
