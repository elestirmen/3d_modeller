/**
 * 3D Model Arşivi — ortak yardımcılar (API, bildirimler, biçimlendirme, diyaloglar).
 */

const bootElement = document.getElementById('boot');
export const boot = bootElement ? JSON.parse(bootElement.textContent) : {};

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const CATEGORY_HUES = {
  vehicle: 0, figure: 22, keychain: 42, mechanical: 62, fun: 82, home: 100, seasonal: 145,
  desk: 168, tech: 188, storage: 205, printer: 222, letters: 238, fidget: 255, puzzle: 272,
  decor: 292, music: 312, miniature: 332, other: 230,
};

export const categories = boot.categories || [];
export const categoryMap = Object.fromEntries(categories.map((item) => [item.key, item]));

export function categoryHue(key) {
  return CATEGORY_HUES[key] ?? 230;
}

export function categoryStyle(key) {
  const saturation = key === 'other' ? '--cat-s: 12%;' : '';
  return `--h: ${categoryHue(key)};${saturation}`;
}

export function categoryLabel(key) {
  return categoryMap[key]?.label || 'Diğer';
}

export function categoryIcon(key) {
  return categoryMap[key]?.icon || 'shapes';
}

// ─── HTML ve biçimlendirme ──────────────────────────────────────────

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function icon(name, extra = '') {
  return `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

export function fold(text) {
  return String(text ?? '')
    .replace(/[ıİ]/g, 'i')
    .replace(/ß/g, 'ss')
    .replace(/[øØ]/g, 'o')
    .replace(/[æÆ]/g, 'ae')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
}

const numberFormat = new Intl.NumberFormat('tr-TR');

export function formatNumber(value) {
  return numberFormat.format(value ?? 0);
}

export function formatBytes(bytes) {
  let size = Number(bytes) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${size} B` : `${size.toFixed(size >= 100 ? 0 : 1).replace('.', ',')} ${units[unit]}`;
}

const relativeFormat = new Intl.RelativeTimeFormat('tr', { numeric: 'auto' });
const dateFormat = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' });

export function formatDate(seconds) {
  if (!seconds) return '';
  return dateFormat.format(new Date(seconds * 1000));
}

export function formatRelative(seconds) {
  if (!seconds) return '';
  const diff = seconds * 1000 - Date.now();
  const abs = Math.abs(diff);
  const steps = [
    ['year', 365 * 864e5], ['month', 30 * 864e5], ['week', 7 * 864e5], ['day', 864e5],
    ['hour', 36e5], ['minute', 6e4],
  ];
  for (const [unit, ms] of steps) {
    if (abs >= ms) return relativeFormat.format(Math.round(diff / ms), unit);
  }
  return 'az önce';
}

export function pluralCount(count, word) {
  return `${formatNumber(count)} ${word}`;
}

export function debounce(fn, wait = 200) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function isMobile() {
  return window.matchMedia('(max-width: 900px)').matches;
}

// ─── API ────────────────────────────────────────────────────────────

let csrfToken = boot.csrf || '';

export function setCsrf(token) {
  if (token) csrfToken = token;
}

export function getCsrf() {
  return csrfToken;
}

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export async function api(url, { method = 'GET', body, headers = {}, raw = false, signal } = {}) {
  const options = { method, headers: { ...headers }, credentials: 'same-origin', signal };
  if (method !== 'GET' && method !== 'HEAD') options.headers['X-CSRF-Token'] = csrfToken;
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) {
      options.body = body;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
  }
  const response = await fetch(url, options);
  if (raw) return response;
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = (payload && payload.error) || `İstek başarısız (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

// ─── Bildirimler ────────────────────────────────────────────────────

export function toast(message, type = 'info', { action, onAction, duration = 3600 } = {}) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const names = { success: 'circle-check', error: 'triangle-alert', info: 'info' };
  const element = document.createElement('div');
  element.className = `toast is-${type}`;
  element.setAttribute('role', type === 'error' ? 'alert' : 'status');
  element.innerHTML = `${icon(names[type] || 'info')}<span>${esc(message)}</span>`;
  if (action) {
    const button = document.createElement('button');
    button.className = 'toast-action';
    button.textContent = action;
    button.addEventListener('click', () => { onAction?.(); dismiss(); });
    element.append(button);
  }
  host.append(element);
  const dismiss = () => {
    element.classList.add('is-leaving');
    setTimeout(() => element.remove(), 220);
  };
  setTimeout(dismiss, duration);
}

// ─── Diyaloglar ─────────────────────────────────────────────────────

/**
 * Yerel <dialog> tabanlı modal oluştur. Kapatınca DOM'dan kaldırılır.
 */
export function createModal({ title, description = '', iconName = '', body = '', footer = '', className = '', labelledBy } = {}) {
  const dialog = document.createElement('dialog');
  dialog.className = `modal ${className}`;
  const titleId = labelledBy || `modal-${Math.random().toString(36).slice(2)}`;
  dialog.setAttribute('aria-labelledby', titleId);
  dialog.innerHTML = `
    <div class="modal-card">
      ${title ? `
        <div class="modal-head">
          ${iconName ? `<div class="modal-head-icon">${icon(iconName)}</div>` : ''}
          <div>
            <h2 class="modal-title" id="${titleId}">${esc(title)}</h2>
            ${description ? `<p class="modal-desc">${esc(description)}</p>` : ''}
          </div>
          <button type="button" class="btn btn-ghost btn-icon btn-sm modal-close" data-close aria-label="Kapat">${icon('x')}</button>
        </div>` : ''}
      <div class="modal-body scroll-thin">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
    </div>`;
  document.body.append(dialog);
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close('backdrop');
    if (event.target.closest('[data-close]')) dialog.close('cancel');
  });
  dialog.addEventListener('close', () => {
    setTimeout(() => dialog.remove(), 50);
  });
  dialog.showModal();
  return dialog;
}

export function confirmDialog({ title, message, confirmText = 'Onayla', danger = false, iconName = 'circle-help' }) {
  return new Promise((resolve) => {
    const dialog = createModal({
      title,
      iconName,
      body: `<p class="prose" style="margin:0">${esc(message)}</p>`,
      footer: `
        <button type="button" class="btn btn-ghost" data-close>Vazgeç</button>
        <button type="button" class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-confirm>${esc(confirmText)}</button>`,
    });
    let answered = false;
    dialog.querySelector('[data-confirm]').addEventListener('click', () => {
      answered = true;
      dialog.close('confirm');
    });
    dialog.addEventListener('close', () => resolve(answered));
  });
}

// ─── Menüler ────────────────────────────────────────────────────────

let openMenuState = null;

export function closeMenus() {
  if (openMenuState) {
    openMenuState.menu.remove();
    openMenuState.trigger?.setAttribute('aria-expanded', 'false');
    openMenuState = null;
  }
}

/**
 * Tetikleyici butonun yanında açılır menü göster.
 * items: [{label, icon, onClick, danger, checked, href, separator, heading}]
 */
export function openMenu(trigger, items, { align = 'right', header = '', up = false } = {}) {
  const alreadyOpen = openMenuState?.trigger === trigger;
  closeMenus();
  if (alreadyOpen) return;
  const wrap = trigger.closest('.menu-wrap') || trigger.parentElement;
  const menu = document.createElement('div');
  menu.className = `menu ${align === 'left' ? 'menu-left' : ''} ${up ? 'menu-up' : ''}`;
  menu.setAttribute('role', 'menu');
  menu.innerHTML = `${header}<div class="menu-scroll scroll-thin">${items.map((item, index) => {
    if (item.separator) return '<div class="menu-sep"></div>';
    if (item.heading) return `<div class="menu-label">${esc(item.heading)}</div>`;
    const classes = `menu-item ${item.danger ? 'is-danger' : ''} ${item.checked ? 'is-checked' : ''}`;
    const content = `${item.icon ? icon(item.icon) : ''}<span>${esc(item.label)}</span>`;
    if (item.href) {
      return `<a class="${classes}" role="menuitem" href="${esc(item.href)}" ${item.external ? 'target="_blank" rel="noopener"' : ''} data-index="${index}">${content}</a>`;
    }
    return `<button type="button" class="${classes}" role="menuitem" data-index="${index}">${content}</button>`;
  }).join('')}</div>`;
  wrap.append(menu);
  trigger.setAttribute('aria-expanded', 'true');
  openMenuState = { menu, trigger };
  menu.addEventListener('click', (event) => {
    const target = event.target.closest('[data-index]');
    if (!target) return;
    const item = items[Number(target.dataset.index)];
    closeMenus();
    item?.onClick?.();
  });
  menu.querySelector('.menu-item')?.focus({ preventScroll: true });
}

document.addEventListener('pointerdown', (event) => {
  if (!openMenuState) return;
  if (openMenuState.menu.contains(event.target) || openMenuState.trigger.contains(event.target)) return;
  closeMenus();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && openMenuState) {
    const trigger = openMenuState.trigger;
    closeMenus();
    trigger.focus();
    event.stopPropagation();
  }
});

// ─── Pano, QR ve paylaşım hedefleri ────────────────────────────────

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  }
}

export function qrSvg(text) {
  if (typeof window.qrcode !== 'function') return '';
  const qr = window.qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
}

export function absoluteUrl(path) {
  return new URL(path, window.location.origin).toString();
}

export function shareTargets(url, title) {
  const text = encodeURIComponent(title);
  const link = encodeURIComponent(url);
  return [
    { label: 'WhatsApp', icon: 'message-circle', href: `https://wa.me/?text=${text}%20${link}` },
    { label: 'Telegram', icon: 'send', href: `https://t.me/share/url?url=${link}&text=${text}` },
    { label: 'E-posta', icon: 'mail', href: `mailto:?subject=${text}&body=${text}%0A${link}` },
  ];
}

// ─── Tema ───────────────────────────────────────────────────────────

export function currentTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit) return explicit;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch { /* depolama kapalı olabilir */ }
  window.dispatchEvent(new CustomEvent('themechange', { detail: next }));
  return next;
}

export function storage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* yoksay */ }
}
