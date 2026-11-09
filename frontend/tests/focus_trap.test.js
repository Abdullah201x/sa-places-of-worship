import { describe, it, expect, beforeEach } from 'vitest';

class MockElement {
  constructor(tag, id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this._classes = new Set();
    this.attributes = {};
    this.children = [];
    this.parentElement = null;
    this.listeners = {};
    this.offsetParent = {};
  }

  get classList() {
    const set = this._classes;
    return {
      contains: (c) => set.has(c),
      add: (c) => set.add(c),
      remove: (c) => set.delete(c),
      has: (c) => set.has(c),
    };
  }

  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  addEventListener(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  }

  removeEventListener(event, fn) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(l => l !== fn);
    }
  }

  dispatchEvent(e) {
    e.target = this;
    const list = this.listeners[e.type] || [];
    list.forEach(fn => fn(e));
  }

  contains(node) {
    if (node === this) return true;
    return this.children.some(c => c.contains ? c.contains(node) : c === node);
  }

  focus() {
    globalThis.document.activeElement = this;
  }

  querySelectorAll() {
    const results = [];
    const check = (node) => {
      if (node.tagName === 'BUTTON' || node.tagName === 'INPUT') {
        results.push(node);
      }
      (node.children || []).forEach(check);
    };
    check(this);
    return results;
  }

  querySelector(sel) {
    const all = this.querySelectorAll(sel);
    return all.length ? all[0] : null;
  }
}

// Setup document shims
const body = new MockElement('body');
const elementsById = {};

globalThis.document = {
  body,
  activeElement: null,
  getElementById: (id) => elementsById[id] || null,
};

import { trapFocus, openModal, closeModal } from '../src/ui.js';

describe('Modal Focus Trap & Accessibility', () => {
  let btnOpen;
  let modal;
  let input1;
  let btn2;

  beforeEach(() => {
    btnOpen = new MockElement('button', 'open-btn');
    modal = new MockElement('div', 'test-modal');
    modal.classList.add('hidden');
    input1 = new MockElement('input', 'input1');
    btn2 = new MockElement('button', 'btn2');

    modal.appendChild(input1);
    modal.appendChild(btn2);

    elementsById['open-btn'] = btnOpen;
    elementsById['test-modal'] = modal;
    elementsById['input1'] = input1;
    elementsById['btn2'] = btn2;

    body.children = [btnOpen, modal];
    document.activeElement = null;
  });

  it('openModal unhides element and sets aria-modal', () => {
    btnOpen.focus();
    openModal(modal);

    expect(modal.classList.contains('hidden')).toBe(false);
    expect(modal.getAttribute('aria-modal')).toBe('true');
    expect(modal.getAttribute('role')).toBe('dialog');
  });

  it('traps Tab navigation between first and last elements', () => {
    openModal(modal);
    btn2.focus();

    // Tab on last element wraps to first
    let defaultPrevented = false;
    const tabEvent = {
      type: 'keydown',
      key: 'Tab',
      shiftKey: false,
      preventDefault: () => { defaultPrevented = true; }
    };
    modal.dispatchEvent(tabEvent);
    expect(defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input1);

    // Shift+Tab on first element wraps to last
    defaultPrevented = false;
    const shiftTabEvent = {
      type: 'keydown',
      key: 'Tab',
      shiftKey: true,
      preventDefault: () => { defaultPrevented = true; }
    };
    modal.dispatchEvent(shiftTabEvent);
    expect(defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(btn2);
  });

  it('Escape key triggers modal close and restores focus', () => {
    btnOpen.focus();
    expect(document.activeElement).toBe(btnOpen);

    openModal(modal);
    let defaultPrevented = false;
    const escEvent = {
      type: 'keydown',
      key: 'Escape',
      preventDefault: () => { defaultPrevented = true; }
    };
    modal.dispatchEvent(escEvent);

    expect(defaultPrevented).toBe(true);
    expect(modal.classList.contains('hidden')).toBe(true);
    expect(document.activeElement).toBe(btnOpen);
  });

  it('closeModal cleans up trap and adds hidden class', () => {
    btnOpen.focus();
    openModal('test-modal');
    expect(modal.classList.contains('hidden')).toBe(false);

    closeModal('test-modal');
    expect(modal.classList.contains('hidden')).toBe(true);
    expect(modal._untrapFocus).toBeUndefined();
    expect(document.activeElement).toBe(btnOpen);
  });
});
