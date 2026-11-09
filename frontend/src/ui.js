// Small DOM helpers shared by the map app and the content pages. They live here,
// not in app.js, so a page that only needs a toast (osm_api.js on /start) does
// not boot the whole Leaflet app.

export function safeUrl(url) {
  const s = String(url || '').trim();
  return /^https?:\/\//i.test(s) ? s : '';
}

export function showToast(message, type = 'success', options = {}) {
  // Remove existing toast if any
  const existingToast = document.querySelector('.toast-notification');
  if (existingToast) {
    existingToast.remove();
  }

  const toast = document.createElement('div');
  toast.className = `toast-notification ${type}`;
  const span = document.createElement('span');
  span.textContent = message;
  const href = options.link && safeUrl(options.link.href);
  if (href) {
    const a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'toast-link';
    a.textContent = options.link.text;
    span.append(' ', a);
  }
  toast.appendChild(span);
  document.body.appendChild(toast);
  
  // Trigger slide-out and removal
  setTimeout(() => {
    toast.style.animation = 'slide-out-left 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards';
    toast.addEventListener('animationend', () => {
      toast.remove();
    });
  }, 4500);
}

export function showLoadingText(message) {
  const overlay = document.getElementById('loading-overlay');
  const text = document.getElementById('loading-text');
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.classList.remove('error');
  }
  if (text) text.innerText = message;
}

const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function trapFocus(containerEl, onClose) {
  if (!containerEl) return () => {};
  const previousActiveElement = typeof document !== 'undefined' ? document.activeElement : null;

  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (typeof onClose === 'function') onClose();
      return;
    }
    if (e.key !== 'Tab') return;

    const focusables = Array.from(containerEl.querySelectorAll(FOCUSABLE_SELECTOR))
      .filter(el => {
        if (typeof el.getClientRects === 'function') {
          return el.getClientRects().length > 0;
        }
        return el.offsetParent !== null;
      });

    if (focusables.length === 0) {
      e.preventDefault();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first || !containerEl.contains(document.activeElement)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last || !containerEl.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  containerEl.addEventListener('keydown', handleKeyDown);

  // Focus first focusable element
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(() => {
      const first = containerEl.querySelector(FOCUSABLE_SELECTOR);
      if (first && typeof first.focus === 'function') first.focus();
    });
  } else {
    const first = containerEl.querySelector(FOCUSABLE_SELECTOR);
    if (first && typeof first.focus === 'function') first.focus();
  }

  return function untrap() {
    containerEl.removeEventListener('keydown', handleKeyDown);
    if (previousActiveElement && typeof previousActiveElement.focus === 'function' && document.body?.contains(previousActiveElement)) {
      try {
        previousActiveElement.focus();
      } catch {
        // Ignore focus failures if element was unmounted
      }
    }
  };
}

export function openModal(elOrId) {
  const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (!el) return;
  el.classList.remove('hidden');
  el.setAttribute('aria-modal', 'true');
  if (!el.getAttribute('role')) el.setAttribute('role', 'dialog');
  if (el._untrapFocus) el._untrapFocus();
  el._untrapFocus = trapFocus(el, () => closeModal(el));
}

export function closeModal(elOrId) {
  const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (!el) return;
  if (el._untrapFocus) {
    el._untrapFocus();
    delete el._untrapFocus;
  }
  el.classList.add('hidden');
}

export function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

