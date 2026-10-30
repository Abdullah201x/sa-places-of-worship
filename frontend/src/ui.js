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
