/**
 * 3D Model Arşivi — galeri uygulaması.
 */

import {
  $, api, boot, categories, categoryIcon, categoryLabel, categoryStyle, confirmDialog, debounce, esc,
  fold, formatBytes, formatNumber, formatRelative, icon, isMobile, openMenu, setCsrf, storage, store, toast,
  toggleTheme,
} from './core.js';
import { DetailView } from './detail.js';
import { openAccount, openEdit, openLogin, openOrganize, openSettings, openShare, openUpload, renderLockedScreen } from './admin.js';

const PAGE_SIZE = 48;
const RECENT_DAYS = 30;
const SORTS = [
  ['recent', 'Yeni eklenen'],
  ['name', 'Ada göre (A–Z)'],
  ['modified', 'Son güncellenen'],
  ['size', 'Boyuta göre'],
  ['files', 'Parça sayısına göre'],
];
const VIEWS = {
  all: { label: 'Tüm modeller', icon: 'layout-grid' },
  featured: { label: 'Öne çıkanlar', icon: 'star' },
  recent: { label: 'Son eklenenler', icon: 'sparkles' },
  printed: { label: 'Basılanlar', icon: 'printer' },
  public: { label: 'Herkese açık', icon: 'globe', manage: 'editor' },
  hidden: { label: 'Gizli modeller', icon: 'eye-off', manage: 'editor' },
  nsfw: { label: '18+ içerik', icon: 'lock', manage: 'admin' },
  nothumb: { label: 'Önizlemesi olmayanlar', icon: 'image', manage: 'editor' },
};
const FLAGS = [
  ['multipart', 'Çok parçalı', 'layers'],
  ['images', 'Görselli', 'image'],
  ['readme', 'README', 'file-text'],
  ['license', 'Lisanslı', 'badge-check'],
  ['cad', 'CAD kaynaklı', 'ruler'],
  ['gcode', 'G-code', 'printer'],
  ['source', 'Kaynak bağlantılı', 'globe'],
];

const state = {
  user: boot.user || null,
  admin: boot.user?.role === 'admin',
  canEdit: ['admin', 'editor'].includes(boot.user?.role),
  models: [],
  byId: new Map(),
  stats: {},
  filters: { q: '', category: null, view: 'all', formats: new Set(), flags: new Set(), tag: null, collection: null },
  sort: storage('sort', 'recent'),
  layout: storage('layout', 'grid'),
  visible: [],
  rendered: 0,
  loaded: false,
  pollTimer: null,
  pollCount: 0,
  revealed: new Set(),
  detailId: null,
  pushedDetail: false,
};

const el = {
  body: document.body,
  topActions: $('#topActions'),
  sidebar: $('#sidebar'),
  content: $('#content'),
  search: $('#search'),
  searchClear: $('#searchClear'),
  detailDialog: $('#detailDialog'),
  detailRoot: $('#detailRoot'),
  menuButton: $('#menuButton'),
};

// ─── Veri ───────────────────────────────────────────────────────────

async function loadLibrary({ quiet = false } = {}) {
  try {
    const data = await api('/api/library');
    const previous = state.byId;
    state.models = data.models;
    state.byId = new Map(data.models.map((model) => [model.id, model]));
    state.stats = data.stats;
    state.loaded = true;
    const sameSet = quiet && previous.size === state.byId.size && [...state.byId.keys()].every((id) => previous.has(id));
    if (sameSet) {
      patchCards(previous);
      renderSidebar();
    } else {
      render();
    }
    schedulePoll(data.pending);
    return data;
  } catch (error) {
    if (error.status === 401) {
      renderLocked();
      return null;
    }
    if (!quiet) {
      el.content.innerHTML = `<div class="empty"><div class="empty-art">${icon('triangle-alert', 'icon-xl')}</div><h3>Arşiv yüklenemedi</h3><p>${esc(error.message)}</p><button class="btn" data-action="reload">${icon('refresh-cw')}Tekrar dene</button></div>`;
    }
    return null;
  }
}

function schedulePoll(pending) {
  clearTimeout(state.pollTimer);
  if (!pending) {
    state.pollCount = 0;
    return;
  }
  state.pollCount += 1;
  if (state.pollCount > 240) return;
  const delay = state.pollCount < 12 ? 4000 : 10000;
  state.pollTimer = setTimeout(() => {
    if (document.hidden) {
      document.addEventListener('visibilitychange', () => loadLibrary({ quiet: true }), { once: true });
      return;
    }
    loadLibrary({ quiet: true });
  }, delay);
}

function allTags() {
  const counts = new Map();
  for (const model of state.models) {
    for (const tag of model.tags) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'tr'));
}

// ─── Filtreleme ─────────────────────────────────────────────────────

function matchesView(model, view) {
  switch (view) {
    case 'featured': return model.featured;
    case 'printed': return model.printed;
    case 'recent': return model.added && Date.now() / 1000 - model.added < RECENT_DAYS * 86400;
    case 'public': return model.public === true;
    case 'hidden': return model.hidden;
    case 'nsfw': return model.nsfw;
    case 'nothumb': return !model.thumb;
    default: return true;
  }
}

function applyFilters() {
  const { q, category, view, formats, flags, tag, collection } = state.filters;
  const terms = fold(q).split(/\s+/).filter(Boolean);
  let list = state.models.filter((model) => {
    if (category && model.category !== category) return false;
    if (!matchesView(model, view)) return false;
    if (tag && !model.tags.includes(tag)) return false;
    if (collection && model.collectionId !== collection) return false;
    if (formats.size && !model.formats.some((format) => formats.has(format))) return false;
    for (const flag of flags) if (!model.flags[flag]) return false;
    if (terms.length && !terms.every((term) => model.search.includes(term))) return false;
    return true;
  });
  const collator = new Intl.Collator('tr', { sensitivity: 'base', numeric: true });
  const sorters = {
    recent: (a, b) => (b.added || 0) - (a.added || 0),
    name: (a, b) => collator.compare(a.title, b.title),
    modified: (a, b) => (b.modified || 0) - (a.modified || 0),
    size: (a, b) => b.size - a.size,
    files: (a, b) => b.fileCount - a.fileCount,
  };
  list = list.sort(sorters[state.sort] || sorters.recent);
  if (terms.length && state.sort === 'recent') {
    const titleHit = (model) => terms.every((term) => fold(model.title).includes(term));
    list = [...list.filter(titleHit), ...list.filter((model) => !titleHit(model))];
  }
  state.visible = list;
}

function hasActiveFilters() {
  const f = state.filters;
  return Boolean(f.q || f.category || f.view !== 'all' || f.formats.size || f.flags.size || f.tag || f.collection);
}

function setFilter(changes, { keepScroll = false } = {}) {
  Object.assign(state.filters, changes);
  syncUrl();
  render();
  if (!keepScroll) window.scrollTo({ top: 0, behavior: 'smooth' });
  if (isMobile()) setSidebar(false);
}

function clearFilters() {
  state.filters = { q: '', category: null, view: 'all', formats: new Set(), flags: new Set(), tag: null, collection: null };
  el.search.value = '';
  syncUrl();
  render();
}

function syncUrl() {
  const params = new URLSearchParams();
  const f = state.filters;
  if (f.q) params.set('q', f.q);
  if (f.category) params.set('kategori', f.category);
  if (f.view !== 'all') params.set('gorunum', f.view);
  if (f.tag) params.set('etiket', f.tag);
  if (f.collection) params.set('koleksiyon', f.collection);
  if (f.formats.size) params.set('format', [...f.formats].join(','));
  if (f.flags.size) params.set('ozellik', [...f.flags].join(','));
  const query = params.toString();
  const base = state.detailId ? `/m/${state.detailId}` : '/';
  history.replaceState(history.state, '', query ? `${base}?${query}` : base);
}

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  const f = state.filters;
  f.q = params.get('q') || '';
  f.category = categories.some((item) => item.key === params.get('kategori')) ? params.get('kategori') : null;
  f.view = VIEWS[params.get('gorunum')] ? params.get('gorunum') : 'all';
  f.tag = params.get('etiket') || null;
  f.collection = params.get('koleksiyon') || null;
  f.formats = new Set((params.get('format') || '').split(',').filter(Boolean));
  f.flags = new Set((params.get('ozellik') || '').split(',').filter(Boolean));
  el.search.value = f.q;
}

// ─── Çizim ──────────────────────────────────────────────────────────

function render() {
  if (state.locked) return;
  applyFilters();
  renderTopActions();
  renderSidebar();
  renderMain();
  el.searchClear.hidden = !state.filters.q;
}

function setUser(user) {
  state.user = user || null;
  state.admin = state.user?.role === 'admin';
  state.canEdit = ['admin', 'editor'].includes(state.user?.role);
  boot.user = state.user;
  detail?.setRole(state.user?.role || null);
}

function renderTopActions() {
  const theme = `<button type="button" class="btn btn-icon btn-ghost" data-action="theme" aria-label="Temayı değiştir" title="Temayı değiştir">${icon('moon')}</button>`;
  if (state.user) {
    const initial = esc((state.user.name || state.user.username).trim().charAt(0).toLocaleUpperCase('tr'));
    el.topActions.innerHTML = `
      ${theme}
      ${state.canEdit ? `<button type="button" class="btn btn-primary" data-action="upload" title="Model yükle (U)">${icon('cloud-upload')}<span class="btn-label">Yükle</span></button>` : ''}
      <div class="menu-wrap">
        <button type="button" class="admin-pill" data-action="admin-menu" aria-haspopup="menu" aria-expanded="false" title="${esc(state.user.name)} · ${esc(state.user.roleLabel)}">
          <span class="admin-avatar">${state.admin ? icon('shield-check') : `<span class="avatar-initial">${initial}</span>`}</span>
          <span class="admin-name">${esc(state.user.name)}</span>${icon('chevron-down', 'icon-xs')}
        </button>
      </div>`;
  } else {
    el.topActions.innerHTML = `
      ${theme}
      <button type="button" class="btn btn-ghost" data-action="login" title="Giriş yap">${icon('log-in')}<span class="btn-label">Giriş</span></button>`;
  }
  updateThemeIcon();
}

function updateThemeIcon() {
  const button = el.topActions.querySelector('[data-action="theme"]');
  if (!button) return;
  const dark = document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  button.innerHTML = icon(dark ? 'sun' : 'moon');
}

function countBy(predicate) {
  let count = 0;
  for (const model of state.models) if (predicate(model)) count += 1;
  return count;
}

function renderSidebar() {
  const f = state.filters;
  const categoryCounts = new Map();
  const formatCounts = new Map();
  for (const model of state.models) {
    categoryCounts.set(model.category, (categoryCounts.get(model.category) || 0) + 1);
    for (const format of model.formats) formatCounts.set(format, (formatCounts.get(format) || 0) + 1);
  }
  const views = Object.entries(VIEWS).filter(([, view]) => !view.manage || (view.manage === 'admin' ? state.admin : state.canEdit));
  const tags = allTags();
  const collections = new Map();
  for (const model of state.models) {
    if (model.collectionId) collections.set(model.collectionId, { name: model.collection, count: (collections.get(model.collectionId)?.count || 0) + 1 });
  }
  const navItem = (active, action, value, iconHtml, label, count, extraClass = '') => `
    <button type="button" class="nav-item ${extraClass}" data-action="${action}" data-value="${esc(value)}" aria-current="${active}">
      ${iconHtml}<span class="nav-label">${esc(label)}</span><span class="nav-count">${formatNumber(count)}</span>
    </button>`;

  const viewItems = views.filter(([key]) => !VIEWS[key].manage).map(([key, view]) => navItem(
    !f.category && f.view === key && !f.tag && !f.collection,
    'view', key, `<span class="nav-icon">${icon(view.icon)}</span>`, view.label,
    key === 'all' ? state.models.length : countBy((model) => matchesView(model, key)),
  )).join('');
  const adminItems = views.filter(([key]) => VIEWS[key].manage).map(([key, view]) => navItem(
    f.view === key, 'view', key, `<span class="nav-icon">${icon(view.icon)}</span>`, view.label, countBy((model) => matchesView(model, key)),
  )).join('');
  const categoryItems = categories.map((category) => {
    const count = categoryCounts.get(category.key) || 0;
    if (!count && !state.canEdit) return '';
    return navItem(
      f.category === category.key, 'category', category.key,
      `<span class="cat-dot" style="${categoryStyle(category.key)}">${icon(category.icon)}</span>`,
      category.label, count, count ? '' : 'is-empty',
    );
  }).join('');
  const formatChips = [...formatCounts.entries()].sort((a, b) => b[1] - a[1]).map(([format, count]) => `
    <button type="button" class="chip" data-action="format" data-value="${esc(format)}" aria-pressed="${f.formats.has(format)}">${esc(format.toUpperCase())}<span class="count">${count}</span></button>`).join('');
  const flagChips = FLAGS.map(([key, label]) => {
    const count = countBy((model) => model.flags[key]);
    if (!count) return '';
    return `<button type="button" class="chip" data-action="flag" data-value="${key}" aria-pressed="${f.flags.has(key)}">${esc(label)}<span class="count">${count}</span></button>`;
  }).join('');
  const tagChips = tags.slice(0, state.showAllTags ? 200 : 14).map(([tag, count]) => `
    <button type="button" class="chip" data-action="tag" data-value="${esc(tag)}" aria-pressed="${f.tag === tag}">${esc(tag)}<span class="count">${count}</span></button>`).join('');

  el.sidebar.innerHTML = `
    <div class="side-section">
      <h2 class="side-title">Keşfet</h2>
      ${viewItems}
    </div>
    ${state.canEdit ? `<div class="side-section"><h2 class="side-title">Yönetim</h2>${adminItems}</div>` : ''}
    <div class="side-section">
      <h2 class="side-title">Kategoriler</h2>
      ${categoryItems}
    </div>
    ${collections.size ? `
      <div class="side-section">
        <h2 class="side-title">Koleksiyonlar</h2>
        ${[...collections.entries()].map(([id, item]) => navItem(f.collection === id, 'collection', id, `<span class="nav-icon">${icon('layers')}</span>`, item.name, item.count)).join('')}
      </div>` : ''}
    <div class="side-section">
      <h2 class="side-title">Format</h2>
      <div class="chip-cloud">${formatChips}</div>
    </div>
    ${flagChips ? `<div class="side-section"><h2 class="side-title">Özellikler</h2><div class="chip-cloud">${flagChips}</div></div>` : ''}
    ${tags.length ? `
      <div class="side-section">
        <h2 class="side-title">Etiketler ${tags.length > 14 ? `<button type="button" data-action="toggle-tags">${state.showAllTags ? 'Daha az' : `Tümü (${tags.length})`}</button>` : ''}</h2>
        <div class="chip-cloud">${tagChips}</div>
      </div>` : ''}
    <div class="side-footer">
      <span>${formatNumber(state.stats.total || 0)} model · ${formatNumber(state.stats.files || 0)} dosya · ${esc(state.stats.totalSize || '')}</span>
      <span>3D Model Arşivi</span>
    </div>`;
}

function pageHeading() {
  const f = state.filters;
  if (f.category) {
    return `<span class="cat-dot" style="${categoryStyle(f.category)}">${icon(categoryIcon(f.category))}</span>${esc(categoryLabel(f.category))}`;
  }
  if (f.collection) {
    const model = state.models.find((item) => item.collectionId === f.collection);
    return `${icon('layers', 'icon-lg')}${esc(model?.collection || 'Koleksiyon')}`;
  }
  if (f.tag) return `${icon('tag', 'icon-lg')}${esc(f.tag)}`;
  if (f.q && f.view === 'all') return `“${esc(f.q)}” için sonuçlar`;
  return esc(VIEWS[f.view]?.label || 'Tüm modeller');
}

function activeFilterPills() {
  const f = state.filters;
  const pills = [];
  if (f.q) pills.push(['q', `Arama: ${f.q}`]);
  if (f.category) pills.push(['category', categoryLabel(f.category)]);
  if (f.view !== 'all') pills.push(['view', VIEWS[f.view].label]);
  if (f.tag) pills.push(['tag', `#${f.tag}`]);
  if (f.collection) pills.push(['collection', 'Koleksiyon']);
  for (const format of f.formats) pills.push([`format:${format}`, format.toUpperCase()]);
  for (const flag of f.flags) pills.push([`flag:${flag}`, FLAGS.find(([key]) => key === flag)?.[1] || flag]);
  if (!pills.length) return '';
  return `<div class="active-filters">
    ${pills.map(([key, label]) => `<button type="button" class="chip is-active" data-action="remove-filter" data-value="${esc(key)}">${esc(label)}<span class="chip-remove">${icon('x', 'icon-xs')}</span></button>`).join('')}
    ${pills.length > 1 ? `<button type="button" class="chip" data-action="clear-filters">Tümünü temizle</button>` : ''}
  </div>`;
}

function renderMain() {
  if (!state.loaded) {
    el.content.innerHTML = `<div class="page-head"><div><div class="skeleton" style="width:220px;height:30px"></div><div class="skeleton" style="width:160px;height:14px;margin-top:10px"></div></div></div>
      <div class="grid">${Array.from({ length: 12 }, () => '<div class="skeleton-card"><div class="skeleton skeleton-media"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div></div>').join('')}</div>`;
    return;
  }
  const f = state.filters;
  const total = state.visible.length;
  const size = state.visible.reduce((sum, model) => sum + model.size, 0);
  const featured = state.models.filter((model) => model.featured);
  const showRail = !hasActiveFilters() && featured.length > 0;
  const hiddenCount = state.canEdit ? state.visible.filter((model) => model.public === false).length : 0;
  const categoryChips = `
    <div class="mobile-cats">
      <button type="button" class="chip" data-action="category" data-value="" aria-pressed="${!f.category}">Tümü</button>
      ${categories.filter((category) => state.models.some((model) => model.category === category.key)).map((category) => `
        <button type="button" class="chip" data-action="category" data-value="${category.key}" aria-pressed="${f.category === category.key}">${icon(category.icon, 'icon-xs')}${esc(category.label)}</button>`).join('')}
    </div>`;

  el.content.innerHTML = `
    ${categoryChips}
    <div class="page-head">
      <div>
        <h1 class="page-title">${pageHeading()}</h1>
        <p class="page-sub">
          <span>${icon('box', 'icon-sm')}${formatNumber(total)} model</span>
          <span>${icon('hard-drive', 'icon-sm')}${esc(formatBytes(size))}</span>
          ${hiddenCount ? `<span>${icon('eye-off', 'icon-sm')}${formatNumber(hiddenCount)} ziyaretçilere kapalı</span>` : ''}
        </p>
      </div>
      <div class="toolbar">
        <label class="sr-only" for="sortSelect">Sıralama</label>
        <select class="select" id="sortSelect" data-action="sort">
          ${SORTS.map(([key, label]) => `<option value="${key}" ${state.sort === key ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
        <div class="segmented" role="group" aria-label="Görünüm">
          <button type="button" data-action="layout" data-value="grid" aria-pressed="${state.layout === 'grid'}" title="Izgara">${icon('layout-grid', 'icon-sm')}</button>
          <button type="button" data-action="layout" data-value="compact" aria-pressed="${state.layout === 'compact'}" title="Sıkı ızgara">${icon('grid-3x3', 'icon-sm')}</button>
          <button type="button" data-action="layout" data-value="list" aria-pressed="${state.layout === 'list'}" title="Liste">${icon('list', 'icon-sm')}</button>
        </div>
      </div>
    </div>
    ${activeFilterPills()}
    ${showRail ? `
      <section class="rail" aria-label="Öne çıkanlar">
        <div class="rail-head"><h2 class="rail-title">${icon('star')}Öne çıkanlar</h2>${featured.length > 4 ? `<button type="button" class="btn btn-ghost btn-sm" data-action="view" data-value="featured">Tümünü gör${icon('arrow-right', 'icon-sm')}</button>` : ''}</div>
        <div class="rail-track scroll-thin">${featured.slice(0, 12).map(cardHtml).join('')}</div>
      </section>
      <div class="rail-head"><h2 class="rail-title" style="font-size:15px">${icon('layout-grid')}Tüm modeller</h2></div>` : ''}
    <div class="grid ${state.layout === 'compact' ? 'is-compact' : ''} ${state.layout === 'list' ? 'is-list' : ''}" id="grid" role="list"></div>
    <div class="grid-sentinel" id="sentinel"></div>`;

  state.rendered = 0;
  const grid = $('#grid');
  if (!total) {
    grid.innerHTML = `
      <div class="empty">
        <div class="empty-art">${icon(state.models.length ? 'search' : 'box', 'icon-xl')}</div>
        <h3>${state.models.length ? 'Eşleşen model bulunamadı' : 'Arşiv henüz boş'}</h3>
        <p>${state.models.length ? 'Arama terimini veya filtreleri değiştirmeyi dene.' : state.canEdit ? 'İlk modelini yükleyerek başla.' : 'Yakında burada modeller olacak.'}</p>
        ${state.models.length ? `<button type="button" class="btn" data-action="clear-filters">${icon('x')}Filtreleri temizle</button>` : state.canEdit ? `<button type="button" class="btn btn-primary" data-action="upload">${icon('cloud-upload')}Model yükle</button>` : ''}
      </div>`;
    return;
  }
  renderMore();
  observeSentinel();
  markLoadedImages(el.content);
}

function renderMore() {
  const grid = $('#grid');
  if (!grid) return;
  const next = state.visible.slice(state.rendered, state.rendered + PAGE_SIZE);
  grid.insertAdjacentHTML('beforeend', next.map(cardHtml).join(''));
  state.rendered += next.length;
  markLoadedImages(grid);
}

let sentinelObserver = null;
function observeSentinel() {
  sentinelObserver?.disconnect();
  const sentinel = $('#sentinel');
  if (!sentinel) return;
  sentinelObserver = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting) && state.rendered < state.visible.length) renderMore();
  }, { rootMargin: '900px 0px' });
  sentinelObserver.observe(sentinel);
}

function markLoadedImages(root) {
  root.querySelectorAll('.card-media img:not(.is-loaded)').forEach((img) => {
    if (img.complete && img.naturalWidth) img.classList.add('is-loaded');
  });
}

function mediaHtml(model) {
  if (model.thumb) {
    return `<img src="${esc(model.thumb)}" alt="" loading="lazy" decoding="async">`;
  }
  return `<div class="card-placeholder"><span class="cat-dot" style="${categoryStyle(model.category)}">${icon(categoryIcon(model.category))}</span><span class="fmt">${esc(model.mainFormat.toUpperCase())}</span>${model.thumbPending ? '<span>Önizleme hazırlanıyor…</span>' : ''}</div>`;
}

function cardHtml(model) {
  const veil = model.nsfw && !state.revealed.has(model.id);
  const classes = ['card', veil ? 'nsfw-veil' : '', model.thumbPending && !model.thumb ? 'is-pending' : ''].join(' ');
  const formats = model.formats.slice(0, 2).map((format) => format.toUpperCase()).join(' · ');
  const tags = model.tags.slice(0, 2);
  return `
    <article class="${classes}" data-id="${esc(model.id)}" tabindex="0" role="listitem" aria-label="${esc(model.title)}">
      <div class="card-media" data-media>
        ${mediaHtml(model)}
        <div class="card-badges">
          <div><span class="badge badge-glass">${esc(formats)}</span>${model.fileCount > 1 ? `<span class="badge badge-glass">${model.fileCount} parça</span>` : ''}</div>
          <div>
            ${model.featured ? `<span class="badge badge-glass" title="Öne çıkan">${icon('star', 'icon-xs filled')}</span>` : ''}
            ${model.printed ? `<span class="badge badge-glass" title="Basıldı">${icon('check', 'icon-xs')}</span>` : ''}
            ${state.canEdit && model.public ? `<span class="badge badge-glass" title="Herkese açık">${icon('globe', 'icon-xs')}</span>` : ''}
            ${state.canEdit && model.hidden ? `<span class="badge badge-glass" title="Gizli">${icon('eye-off', 'icon-xs')}</span>` : ''}
          </div>
        </div>
        <div class="card-actions">
          <button type="button" class="card-action" data-card-action="share" title="Paylaş" aria-label="Paylaş">${icon('share-2', 'icon-sm')}</button>
          ${state.canEdit ? `<button type="button" class="card-action ${model.featured ? 'is-starred' : ''}" data-card-action="feature" title="${model.featured ? 'Öne çıkanlardan çıkar' : 'Öne çıkar'}" aria-label="Öne çıkar">${icon('star', 'icon-sm')}</button>` : ''}
        </div>
      </div>
      <div class="card-body">
        <h3 class="card-title">${esc(model.title)}</h3>
        <div class="card-meta">
          <span class="card-cat" style="${categoryStyle(model.category)}">${icon(categoryIcon(model.category))}${esc(categoryLabel(model.category))}</span>
          <span class="sep"></span><span class="card-size">${esc(model.sizeLabel)}</span>
          ${model.dims && state.layout === 'list' ? `<span class="sep"></span><span>${esc(model.dims)}</span>` : ''}
        </div>
        ${tags.length || model.author ? `<div class="card-tags">${tags.map((tag) => `<span class="badge">${esc(tag)}</span>`).join('')}${model.author && !tags.length ? `<span class="badge">${icon('user-round', 'icon-xs')}${esc(model.author)}</span>` : ''}</div>` : ''}
      </div>
    </article>`;
}

function patchCards(previous) {
  for (const model of state.models) {
    const old = previous.get(model.id);
    if (!old || (old.thumb === model.thumb && old.thumbPending === model.thumbPending)) continue;
    document.querySelectorAll(`.card[data-id="${CSS.escape(model.id)}"]`).forEach((card) => {
      const media = card.querySelector('[data-media]');
      media.querySelectorAll('img, .card-placeholder').forEach((node) => node.remove());
      media.insertAdjacentHTML('afterbegin', mediaHtml(model));
      card.classList.toggle('is-pending', model.thumbPending && !model.thumb);
    });
  }
}

function renderLocked() {
  state.locked = true;
  el.sidebar.hidden = true;
  $('#layout').style.gridTemplateColumns = '1fr';
  el.search.closest('.search').style.visibility = 'hidden';
  el.menuButton.hidden = true;
  el.topActions.innerHTML = `<button type="button" class="btn btn-icon btn-ghost" data-action="theme" aria-label="Temayı değiştir" title="Temayı değiştir">${icon('moon')}</button>`;
  updateThemeIcon();
  renderLockedScreen(el.content, { onSuccess: () => window.location.reload() });
}

// ─── Detay ──────────────────────────────────────────────────────────

let detail = null;

function ensureDetail() {
  if (detail) return detail;
  detail = new DetailView({
    root: el.detailRoot,
    mode: 'modal',
    role: state.user?.role || null,
    onClose: () => closeDetail(),
    onNavigate: (direction) => navigateDetail(direction),
    onUpdated: (updated, { quiet } = {}) => {
      mergeCard(updated);
      if (!quiet) renderDetail(updated);
    },
    onShare: (model) => openShare(model, { admin: state.canEdit, onChange: () => refreshDetail() }),
    onEdit: (model) => openEdit(model, { allTags: allTags().map(([tag]) => tag), onSaved: (updated) => { mergeCard(updated); renderDetail(updated); } }),
    onUpload: (model) => openUpload({ target: model, allTags: allTags().map(([tag]) => tag), onDone: async (_, { open }) => { await loadLibrary({ quiet: true }); if (open) refreshDetail(); } }),
    onDeleted: (model) => trashModel(model),
    onOrganize: (model) => openOrganize(model, {
      models: state.models,
      admin: state.admin,
      onDone: (result) => afterOrganize(model, result),
    }),
    onOpenModel: (id) => openDetail(id),
    onTag: (tag) => { closeDetail(); setFilter({ tag, category: null, view: 'all' }); },
  });
  return detail;
}

function mergeCard(updated) {
  const card = state.byId.get(updated.id);
  if (!card) return;
  const fields = ['title', 'category', 'tags', 'featured', 'printed', 'nsfw', 'hidden', 'public', 'author', 'thumb', 'thumbPending', 'search', 'flags'];
  for (const field of fields) if (field in updated) card[field] = updated[field];
  applyFilters();
  renderSidebar();
  document.querySelectorAll(`.card[data-id="${CSS.escape(updated.id)}"]`).forEach((node) => {
    node.outerHTML = cardHtml(card);
  });
  markLoadedImages(el.content);
}

function neighbors(id) {
  const list = state.visible.length ? state.visible : state.models;
  const index = list.findIndex((model) => model.id === id);
  return {
    prev: index > 0 ? list[index - 1].id : null,
    next: index >= 0 && index < list.length - 1 ? list[index + 1].id : null,
  };
}

function similarModels(model) {
  const tokens = new Set(fold(model.title).split(/[^a-z0-9]+/).filter((token) => token.length > 2));
  const score = (other) => {
    let value = 0;
    if (model.collectionId && other.collectionId === model.collectionId) value += 10;
    if (other.category === model.category) value += 4;
    for (const token of fold(other.title).split(/[^a-z0-9]+/)) if (tokens.has(token)) value += 2;
    for (const tag of other.tags) if (model.tags.includes(tag)) value += 1;
    return value;
  };
  return state.models
    .filter((other) => other.id !== model.id && !(other.nsfw && !model.nsfw))
    .map((other) => [score(other), other])
    .filter(([value]) => value >= 4)
    .sort((a, b) => b[0] - a[0])
    .slice(0, 10)
    .map(([, other]) => other);
}

function renderDetail(model) {
  ensureDetail().render(model, { ...neighbors(model.id), similar: similarModels(model) });
}

async function openDetail(id, { push = true } = {}) {
  const view = ensureDetail();
  view.setRole(state.user?.role || null);
  if (!el.detailDialog.open) {
    el.detailRoot.innerHTML = `<div style="display:grid;place-items:center;height:100%"><div class="spinner" style="color:var(--accent)"></div></div>`;
    el.detailDialog.showModal();
    document.body.classList.add('is-locked');
  }
  const wasOpen = state.detailId !== null;
  state.detailId = id;
  if (push) {
    const url = `/m/${id}${window.location.search}`;
    if (wasOpen) history.replaceState({ model: id }, '', url);
    else {
      history.pushState({ model: id }, '', url);
      state.pushedDetail = true;
    }
  }
  try {
    const model = await api(`/api/models/${encodeURIComponent(id)}`);
    if (state.detailId !== id) return;
    renderDetail(model);
    document.title = `${model.title} · ${boot.site?.title || '3D Model Arşivi'}`;
  } catch (error) {
    toast(error.message, 'error');
    closeDetail();
  }
}

async function refreshDetail() {
  if (!state.detailId) return;
  try {
    const model = await api(`/api/models/${encodeURIComponent(state.detailId)}`);
    mergeCard(model);
    renderDetail(model);
  } catch { /* yoksay */ }
}

function navigateDetail(direction) {
  const { prev, next } = neighbors(state.detailId);
  const target = direction < 0 ? prev : next;
  if (target) openDetail(target);
}

function closeDetail({ fromHistory = false } = {}) {
  if (!state.detailId) return;
  state.detailId = null;
  detail?.deactivate();
  if (el.detailDialog.open) el.detailDialog.close();
  document.body.classList.remove('is-locked');
  document.title = boot.site?.title || '3D Model Arşivi';
  if (!fromHistory) {
    if (state.pushedDetail) {
      state.pushedDetail = false;
      history.back();
    } else {
      syncUrl();
    }
  }
}

async function afterOrganize(model, result) {
  await loadLibrary({ quiet: false });
  if (result.source) {
    if (state.detailId === model.id) refreshDetail();
  } else if (result.created?.[0]) {
    openDetail(result.created[0]);
  } else if (result.targets?.[0]) {
    openDetail(result.targets[0]);
  } else {
    closeDetail();
  }
}

async function trashModel(model) {
  const ok = await confirmDialog({
    title: 'Model çöp kutusuna taşınsın mı?',
    message: `“${model.title}” ve dosyaları arşivden kaldırılıp sunucudaki .trash klasörüne taşınacak. Paylaşım bağlantıları iptal olur.`,
    confirmText: 'Çöp kutusuna taşı',
    danger: true,
    iconName: 'trash-2',
  });
  if (!ok) return;
  try {
    await api(`/api/models/${encodeURIComponent(model.id)}`, { method: 'DELETE' });
    toast('Model çöp kutusuna taşındı', 'success');
    closeDetail();
    await loadLibrary();
  } catch (error) {
    toast(error.message, 'error');
  }
}

// ─── Oturum ─────────────────────────────────────────────────────────

async function afterLogin(result) {
  setUser(result?.user);
  toast(`Hoş geldin, ${state.user?.name || ''}! ${state.user?.roleLabel || ''} olarak giriş yaptın.`, 'success');
  await loadLibrary();
  if (state.detailId) refreshDetail();
}

async function logout() {
  try {
    const result = await api('/api/auth/logout', { method: 'POST' });
    setCsrf(result.csrf);
  } catch { /* yoksay */ }
  setUser(null);
  toast('Çıkış yapıldı', 'info');
  if (!boot.publicBrowsing) {
    window.location.href = '/';
    return;
  }
  await loadLibrary();
  if (state.detailId) {
    if (state.byId.has(state.detailId)) refreshDetail();
    else closeDetail();
  }
}

function startUpload() {
  openUpload({
    allTags: allTags().map(([tag]) => tag),
    onDone: async (models, { open, silent }) => {
      await loadLibrary({ quiet: silent });
      if (open && models[0]) openDetail(models[0].id);
    },
  });
}

function openAdminMenu(trigger) {
  const user = state.user;
  const items = [];
  if (state.canEdit) items.push({ label: 'Model yükle', icon: 'cloud-upload', onClick: startUpload });
  if (state.admin) {
    items.push(
      { label: 'Ayarlar', icon: 'settings', onClick: () => openSettings({ onChanged: () => loadLibrary({ quiet: true }) }) },
      { label: 'Kullanıcılar', icon: 'user-round', onClick: () => openSettings({ initialTab: 'users' }) },
      { label: 'Paylaşım bağlantıları', icon: 'link', onClick: () => openSettings({ initialTab: 'shares' }) },
      { label: 'Bakım ve önizlemeler', icon: 'wand-sparkles', onClick: () => openSettings({ initialTab: 'maintenance', onChanged: () => loadLibrary({ quiet: true }) }) },
    );
  } else {
    items.push({ label: 'Şifremi değiştir', icon: 'lock', onClick: () => openAccount() });
  }
  items.push({ separator: true }, { label: 'Çıkış yap', icon: 'log-out', danger: true, onClick: logout });
  openMenu(trigger, items, {
    header: `<div class="menu-header"><strong>${esc(user.name)}</strong><span>@${esc(user.username)} · ${esc(user.roleLabel)}</span></div>`,
  });
}

// ─── Olaylar ────────────────────────────────────────────────────────

function setSidebar(open) {
  el.sidebar.classList.toggle('is-open', open);
  let backdrop = $('.drawer-backdrop');
  if (open && !backdrop) {
    backdrop = document.createElement('div');
    backdrop.className = 'drawer-backdrop';
    backdrop.addEventListener('click', () => setSidebar(false));
    document.body.append(backdrop);
  } else if (!open) {
    backdrop?.remove();
  }
}

function handleAction(target, event) {
  const { action, value } = target.dataset;
  const f = state.filters;
  switch (action) {
    case 'view': setFilter({ view: value, category: null, tag: null, collection: null }); break;
    case 'category': setFilter({ category: value && f.category !== value ? value : null, view: 'all', tag: null, collection: null }); break;
    case 'collection': setFilter({ collection: f.collection === value ? null : value, category: null, view: 'all', tag: null }); break;
    case 'tag': setFilter({ tag: f.tag === value ? null : value }); break;
    case 'format': {
      const formats = new Set(f.formats);
      if (formats.has(value)) formats.delete(value); else formats.add(value);
      setFilter({ formats }, { keepScroll: true });
      break;
    }
    case 'flag': {
      const flags = new Set(f.flags);
      if (flags.has(value)) flags.delete(value); else flags.add(value);
      setFilter({ flags }, { keepScroll: true });
      break;
    }
    case 'remove-filter': {
      if (value === 'q') { el.search.value = ''; setFilter({ q: '' }); } else if (value.startsWith('format:')) {
        const formats = new Set(f.formats); formats.delete(value.slice(7)); setFilter({ formats });
      } else if (value.startsWith('flag:')) {
        const flags = new Set(f.flags); flags.delete(value.slice(5)); setFilter({ flags });
      } else setFilter({ [value]: value === 'view' ? 'all' : null });
      break;
    }
    case 'clear-filters': clearFilters(); break;
    case 'toggle-tags': state.showAllTags = !state.showAllTags; renderSidebar(); break;
    case 'layout': state.layout = value; store('layout', value); renderMain(); break;
    case 'theme': toggleTheme(); updateThemeIcon(); break;
    case 'login': openLogin({ onSuccess: afterLogin }); break;
    case 'upload': startUpload(); break;
    case 'admin-menu': openAdminMenu(target); break;
    case 'reload': loadLibrary(); break;
    default: return false;
  }
  event.preventDefault();
  return true;
}

function bindEvents() {
  document.addEventListener('click', (event) => {
    const cardAction = event.target.closest('[data-card-action]');
    if (cardAction) {
      event.stopPropagation();
      const model = state.byId.get(cardAction.closest('.card').dataset.id);
      if (cardAction.dataset.cardAction === 'share') {
        if (state.canEdit) api(`/api/models/${encodeURIComponent(model.id)}`).then((full) => openShare(full, { admin: true })).catch((error) => toast(error.message, 'error'));
        else openShare(model, { admin: false });
      } else if (cardAction.dataset.cardAction === 'feature') {
        api(`/api/models/${encodeURIComponent(model.id)}`, { method: 'PATCH', body: { favorite: !model.featured } })
          .then((updated) => { mergeCard(updated); toast(updated.featured ? 'Öne çıkanlara eklendi' : 'Öne çıkanlardan çıkarıldı', 'success', { duration: 1800 }); renderMain(); })
          .catch((error) => toast(error.message, 'error'));
      }
      return;
    }
    const actionTarget = event.target.closest('[data-action]');
    if (actionTarget && !el.detailRoot.contains(actionTarget) && handleAction(actionTarget, event)) return;
    const card = event.target.closest('.card');
    if (card && !el.detailRoot.contains(card)) {
      const model = state.byId.get(card.dataset.id);
      if (model?.nsfw && !state.revealed.has(model.id)) {
        state.revealed.add(model.id);
        card.classList.remove('nsfw-veil');
      }
      openDetail(card.dataset.id);
    }
  });

  el.content.addEventListener('change', (event) => {
    if (event.target.matches('[data-action="sort"]')) {
      state.sort = event.target.value;
      store('sort', state.sort);
      render();
    }
  });

  el.content.addEventListener('load', (event) => {
    if (event.target.tagName === 'IMG') event.target.classList.add('is-loaded');
  }, true);
  el.content.addEventListener('error', (event) => {
    if (event.target.tagName === 'IMG' && event.target.closest('.card-media')) {
      const card = event.target.closest('.card');
      const model = state.byId.get(card?.dataset.id);
      if (model) event.target.replaceWith(document.createRange().createContextualFragment(mediaHtml({ ...model, thumb: null })));
    }
  }, true);

  const onSearch = debounce(() => {
    state.filters.q = el.search.value.trim();
    syncUrl();
    render();
  }, 120);
  el.search.addEventListener('input', () => {
    el.searchClear.hidden = !el.search.value;
    onSearch();
  });
  el.search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      el.search.value = '';
      onSearch();
      el.search.blur();
    } else if (event.key === 'Enter' && state.visible[0]) {
      openDetail(state.visible[0].id);
    }
  });
  el.searchClear.addEventListener('click', () => {
    el.search.value = '';
    el.search.focus();
    onSearch();
  });

  el.menuButton?.addEventListener('click', () => setSidebar(!el.sidebar.classList.contains('is-open')));

  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest('input, textarea, select, [contenteditable="true"]');
    if ((event.key === 'k' && (event.metaKey || event.ctrlKey)) || (event.key === '/' && !typing)) {
      event.preventDefault();
      if (el.detailDialog.open) return;
      el.search.focus();
      el.search.select();
      return;
    }
    if (typing) return;
    if (el.detailDialog.open) {
      if (document.querySelector('dialog.modal:not(.viewer-dialog)[open]')) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        const direction = event.key === 'ArrowLeft' ? -1 : 1;
        // Shift + ok: aynı modelin parçaları arasında; düz ok: modeller arasında.
        if (event.shiftKey) {
          event.preventDefault();
          detail?.stepPart(direction);
        } else {
          navigateDetail(direction);
        }
      }
      return;
    }
    if (event.key === 'u' && state.canEdit && !document.querySelector('dialog[open]')) startUpload();
    if (event.key === 'Enter' && event.target.classList?.contains('card')) openDetail(event.target.dataset.id);
  });

  el.detailDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeDetail();
  });
  el.detailDialog.addEventListener('click', (event) => {
    if (event.target === el.detailDialog) closeDetail();
  });

  window.addEventListener('popstate', () => {
    const match = window.location.pathname.match(/^\/m\/([^/]+)/);
    if (match) {
      openDetail(decodeURIComponent(match[1]), { push: false });
    } else if (state.detailId) {
      state.pushedDetail = false;
      closeDetail({ fromHistory: true });
    }
    readUrl();
    render();
  });

  window.addEventListener('themechange', updateThemeIcon);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', updateThemeIcon);
  window.addEventListener('resize', debounce(() => { if (!isMobile()) setSidebar(false); }, 150));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setSidebar(false); });
}

// ─── Başlat ─────────────────────────────────────────────────────────

function fitSearchPlaceholder() {
  el.search.placeholder = window.innerWidth < 640 ? 'Ara…' : 'Model, kategori, etiket veya tasarımcı ara…';
}

fitSearchPlaceholder();
window.addEventListener('resize', debounce(fitSearchPlaceholder, 200));
readUrl();
bindEvents();
render();
if (!boot.publicBrowsing && !state.user) {
  renderLocked();
} else {
  loadLibrary().then(() => {
    if (boot.initialModel) {
      state.pushedDetail = false;
      openDetail(boot.initialModel, { push: false });
      state.detailId = boot.initialModel;
    }
  });
}
