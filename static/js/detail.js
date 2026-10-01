/**
 * Model detay görünümü: 3D sahne, galeri, bilgiler ve (yöneticiye) hızlı düzenleme.
 * Hem galeri penceresinde hem paylaşım sayfasında kullanılır.
 */

import {
  $, api, categories, categoryIcon, categoryLabel, categoryStyle, debounce, esc, formatBytes, formatDate,
  formatNumber, icon, isMobile, openMenu, toast,
} from './core.js';
import { ModelViewer, SWATCHES, webglAvailable } from './viewer.js';

const KIND_GROUPS = [
  ['model', 'Model dosyaları'],
  ['image', 'Görseller'],
  ['document', 'Belgeler'],
  ['readme', 'Belgeler'],
  ['license', 'Belgeler'],
  ['cad', 'CAD kaynakları'],
  ['gcode', 'G-code'],
  ['archive', 'Arşivler'],
];
const PLATFORM_LABELS = { Thingiverse: 'Thingiverse', Printables: 'Printables', MakerWorld: 'MakerWorld' };

function autoLoadLimit() {
  const connection = navigator.connection;
  if (connection?.saveData) return 3 * 1024 * 1024;
  return isMobile() ? 25 * 1024 * 1024 : 80 * 1024 * 1024;
}

export class DetailView {
  constructor({ root, mode = 'modal', role = null, onClose, onNavigate, onUpdated, onShare, onEdit, onUpload, onDeleted, onOpenModel, onTag, onOrganize }) {
    this.root = root;
    this.mode = mode;
    this.setRole(role);
    this.handlers = { onClose, onNavigate, onUpdated, onShare, onEdit, onUpload, onDeleted, onOpenModel, onTag, onOrganize };
    // Parça önizlemeleri sunucuda ilk istekte üretilir (202); hazır olana kadar birkaç kez yeniden denenir.
    root.addEventListener('error', (event) => {
      const image = event.target;
      if (image.tagName !== 'IMG') return;
      if (image.classList.contains('part-img')) this.retryPartImage(image);
      else if (image.classList.contains('stage-poster')) image.remove();
    }, true);
    root.addEventListener('load', (event) => {
      if (event.target.classList?.contains('part-img')) event.target.closest('.part-media')?.classList.add('has-image');
    }, true);
    this.model = null;
    this.viewer = null;
    this.current = null;
    this.saveNote = debounce((value) => this.patch({ note: value }, { quiet: true }), 700);
    root.addEventListener('click', (event) => this.handleClick(event));
    root.addEventListener('input', (event) => {
      if (event.target.matches('[data-field="note"]')) this.saveNote(event.target.value);
    });
    root.addEventListener('change', (event) => {
      const toggle = event.target.closest('[data-toggle]');
      if (toggle) this.patch({ [toggle.dataset.toggle]: toggle.checked });
    });
  }

  setRole(role) {
    this.role = role;
    this.canEdit = role === 'admin' || role === 'editor';
    this.isAdmin = role === 'admin';
  }

  render(model, { prev = null, next = null, similar = [] } = {}) {
    const sameModel = this.model?.id === model.id;
    const scroller = $('.detail-info-scroll', this.root);
    const scrollTop = sameModel && scroller ? scroller.scrollTop : 0;
    this.model = model;
    this.neighbors = { prev, next };
    this.similar = similar;
    this.root.innerHTML = this.template(model);
    this.stage = $('[data-stage]', this.root);
    if (!this.viewer) this.viewer = new ModelViewer(this.stage);
    else this.viewer.setContainer(this.stage);
    if (scrollTop) $('.detail-info-scroll', this.root).scrollTop = scrollTop;
    this.viewer.onChange = () => this.syncToolbar();
    this.syncToolbar();
    if (!sameModel || !this.current) {
      this.current = model.main;
      this.showFile(model.main);
    } else {
      this.showFile(this.current, { keepLoaded: true });
    }
  }

  // ─── Şablon ──────────────────────────────────────────────────────

  template(model) {
    const catKey = model.category;
    const admin = this.canEdit;
    const stats = model.stats || {};
    const hasImages = model.images.length > 0;
    const downloadLabel = model.fileCount > 1 || model.assets.some((item) => !item.member && item.kind !== 'archive')
      ? 'Tümünü indir' : 'İndir';
    const downloadHref = model.fileCount > 1 || model.kind === 'archive' ? model.downloadAllUrl : (model.main.downloadUrl || model.downloadAllUrl);
    const platform = PLATFORM_LABELS[model.platform];
    const multi = model.files.length > 1;

    const fileValue = model.assets.length ? `${model.fileCount} + ${model.assets.length} ek` : `${model.fileCount} model`;
    const formatValue = model.formats.map((item) => item.toUpperCase()).join(' · ');
    const statTiles = stats.dims ? [
      { label: 'Boyutlar', iconName: 'ruler', value: stats.dims, span: 'span-2' },
      { label: 'Hacim', iconName: 'box', value: stats.volumeCm3 ? `${formatNumber(stats.volumeCm3)} cm³` : '—' },
      { label: 'Dosya', iconName: 'files', value: fileValue },
      { label: 'Toplam', iconName: 'hard-drive', value: model.sizeLabel },
      { label: 'Üçgen', iconName: 'shapes', value: stats.triangles ? formatNumber(stats.triangles) : '—' },
      { label: 'Format', iconName: 'layers', value: formatValue, span: 'span-3' },
    ] : [
      { label: 'Dosya', iconName: 'files', value: fileValue },
      { label: 'Toplam', iconName: 'hard-drive', value: model.sizeLabel },
      { label: 'Format', iconName: 'layers', value: formatValue },
    ];

    return `
      <div class="detail">
        <div class="detail-stage-col">
          <div class="stage" data-stage>
            <div class="stage-image" data-stage-image hidden><img alt=""></div>
            <div class="stage-overlay" data-stage-overlay hidden></div>
            <div class="stage-top">
              <div class="stage-parts">
                ${multi ? `<button type="button" class="stage-step" data-action="part-prev" title="Önceki parça (Shift + ←)" aria-label="Önceki parça">${icon('chevron-left', 'icon-sm')}</button>` : ''}
                <div class="menu-wrap">
                  <button type="button" class="stage-file" data-action="pick-file" ${multi ? '' : 'disabled'} aria-haspopup="menu" title="${multi ? 'Parça seç' : ''}">
                    ${icon('box', 'icon-sm')}<span data-stage-name>${esc(model.main.name)}</span>
                    ${multi ? '<span class="stage-count" data-stage-count></span>' : ''}
                    <span class="stage-dims" data-stage-dims></span>
                    ${multi ? icon('chevron-down', 'icon-xs') : ''}
                  </button>
                </div>
                ${multi ? `<button type="button" class="stage-step" data-action="part-next" title="Sonraki parça (Shift + →)" aria-label="Sonraki parça">${icon('chevron-right', 'icon-sm')}</button>` : ''}
              </div>
            </div>
            ${this.mode === 'modal' ? `
              <div class="stage-nav prev" ${this.neighbors.prev ? '' : 'hidden'}><button type="button" class="btn btn-icon" data-action="prev" aria-label="Önceki model">${icon('chevron-left')}</button></div>
              <div class="stage-nav next" ${this.neighbors.next ? '' : 'hidden'}><button type="button" class="btn btn-icon" data-action="next" aria-label="Sonraki model">${icon('chevron-right')}</button></div>` : ''}
            <div class="stage-toolbar" data-toolbar hidden>
              <button type="button" class="tool-btn" data-tool="autoRotate" title="Otomatik döndür" aria-label="Otomatik döndür">${icon('rotate-3d')}</button>
              <button type="button" class="tool-btn" data-tool="wireframe" title="Tel kafes" aria-label="Tel kafes">${icon('grid-3x3')}</button>
              <button type="button" class="tool-btn" data-tool="showBox" title="Ölçü kutusu" aria-label="Ölçü kutusu">${icon('scan-line')}</button>
              <div class="menu-wrap" style="position:relative">
                <button type="button" class="tool-btn" data-action="swatches" title="Filament rengi" aria-label="Filament rengi">${icon('droplet')}</button>
              </div>
              <span class="tool-sep"></span>
              <button type="button" class="tool-btn" data-action="reset-view" title="Görünümü sıfırla" aria-label="Görünümü sıfırla">${icon('refresh-cw')}</button>
              <button type="button" class="tool-btn" data-action="fullscreen" title="Tam ekran" aria-label="Tam ekran">${icon('maximize')}</button>
            </div>
          </div>
          ${multi || hasImages ? `
            <div class="gallery-strip scroll-thin" data-strip role="toolbar" aria-label="${multi ? 'Parçalar ve görseller' : 'Görseller'}">
              ${multi ? model.files.map((entry, index) => `
                <button type="button" class="part-thumb" data-action="view-part" data-index="${index}" aria-pressed="false" title="${esc(entry.name)} · ${esc(entry.sizeLabel)}">
                  <span class="part-media">
                    ${entry.thumbUrl ? `<img class="part-img" src="${esc(entry.thumbUrl)}" alt="" loading="lazy" decoding="async">` : ''}
                    <span class="part-ext">${esc(entry.format)}</span>
                  </span>
                  <span class="part-label">${esc(entry.name.replace(/\.[^.]+$/, ''))}</span>
                </button>`).join('') : '<button type="button" class="gallery-thumb" data-action="show-3d" aria-pressed="true" title="3D görünüm">3D</button>'}
              ${multi && hasImages ? '<span class="strip-sep" aria-hidden="true"></span>' : ''}
              ${model.images.map((image, index) => `
                <button type="button" class="gallery-thumb" data-action="show-image" data-index="${index}" aria-pressed="false" title="${esc(image.name)}">
                  <img src="${esc(image.url)}" alt="" loading="lazy">
                </button>`).join('')}
            </div>` : ''}
        </div>

        <aside class="detail-info">
          ${this.mode === 'modal' ? `<button type="button" class="btn btn-ghost btn-icon detail-close" data-action="close" aria-label="Kapat (Esc)">${icon('x')}</button>` : ''}
          <div class="detail-info-scroll scroll-thin">
            <div class="detail-kicker">
              <div class="menu-wrap">
                ${admin
                  ? `<button type="button" class="cat-chip" style="${categoryStyle(catKey)}" data-action="pick-category" aria-haspopup="menu" title="Kategoriyi değiştir">${icon(categoryIcon(catKey))}${esc(categoryLabel(catKey))}${icon('chevron-down', 'icon-xs')}</button>`
                  : `<span class="cat-chip" style="${categoryStyle(catKey)}">${icon(categoryIcon(catKey))}${esc(categoryLabel(catKey))}</span>`}
              </div>
              ${admin && !model.overrides?.category ? '<span class="badge" title="Kategori otomatik belirlendi">Otomatik</span>' : ''}
              ${model.collection ? `<span class="badge">${icon('layers', 'icon-xs')}${esc(model.collection)}</span>` : ''}
              ${model.printed ? `<span class="badge badge-success">${icon('check', 'icon-xs')}Basıldı</span>` : ''}
              ${model.nsfw ? '<span class="badge badge-danger">18+</span>' : ''}
              ${admin && model.public ? `<span class="badge badge-success">${icon('globe', 'icon-xs')}Herkese açık</span>` : ''}
              ${admin && model.hidden ? `<span class="badge badge-warning">${icon('eye-off', 'icon-xs')}Gizli</span>` : ''}
              ${admin && !model.hidden && model.public === false ? `<span class="badge badge-warning" title="Ziyaretçilere görünmüyor">${icon('lock', 'icon-xs')}Özel</span>` : ''}
            </div>
            <h1 class="detail-title">${esc(model.title)}</h1>
            ${model.originalTitle ? `<p class="detail-subtitle">Orijinal ad: ${esc(model.originalTitle)}</p>` : ''}
            <div class="detail-byline">
              ${model.author ? `<span>${icon('user-round', 'icon-sm')}${esc(model.author)}</span>` : ''}
              ${model.sourceUrl ? `<a href="${esc(model.sourceUrl)}" target="_blank" rel="noopener noreferrer">${icon('globe', 'icon-sm')}${esc(platform || 'Kaynak')}${icon('external-link', 'icon-xs')}</a>` : (platform ? `<span>${icon('globe', 'icon-sm')}${esc(platform)}</span>` : '')}
              ${model.added ? `<span title="${esc(formatDate(model.added))}">${icon('calendar', 'icon-sm')}${esc(formatDate(model.added))}</span>` : ''}
            </div>

            <div class="detail-actions">
              ${model.canDownload && downloadHref ? `<a class="btn btn-primary" href="${esc(downloadHref)}" download>${icon('download')}${downloadLabel}<span style="opacity:.75;font-weight:500">· ${esc(model.sizeLabel)}</span></a>` : ''}
              <button type="button" class="btn" data-action="share">${icon('share-2')}Paylaş</button>
              ${admin ? `
                <button type="button" class="btn btn-icon ${model.featured ? 'is-starred' : ''}" data-action="toggle-featured" title="${model.featured ? 'Öne çıkanlardan çıkar' : 'Öne çıkar'}" aria-pressed="${model.featured}">${icon('star')}</button>
                <div class="menu-wrap">
                  <button type="button" class="btn btn-icon" data-action="more" aria-haspopup="menu" aria-label="Diğer işlemler">${icon('settings')}</button>
                </div>` : ''}
            </div>

            <div class="stat-grid">
              ${statTiles.map((tile) => `
                <div class="stat ${tile.span || ''}">
                  <div class="stat-label">${icon(tile.iconName)}${esc(tile.label)}</div>
                  <div class="stat-value" title="${esc(tile.value)}">${esc(tile.value)}</div>
                </div>`).join('')}
            </div>

            ${model.printProfile.length || model.slicer ? `
              <div class="section">
                <h3 class="section-title">Baskı profili</h3>
                <div class="profile-list">
                  ${model.printProfile.map((item) => `<span class="profile-item"><span>${esc(item.label)}</span><strong>${esc(item.value)}</strong></span>`).join('')}
                  ${model.slicer ? `<span class="profile-item"><span>Dilimleyici</span><strong>${esc(model.slicer)}</strong></span>` : ''}
                </div>
              </div>` : ''}

            ${model.description ? `
              <div class="section">
                <h3 class="section-title">Açıklama</h3>
                <div class="prose ${model.description.length > 420 ? 'is-clamped' : ''}" data-description>${esc(model.description)}</div>
                ${model.description.length > 420 ? '<button type="button" class="link-btn" data-action="expand">Devamını göster</button>' : ''}
              </div>` : ''}

            ${model.tags.length ? `
              <div class="section">
                <h3 class="section-title">Etiketler</h3>
                <div class="chip-cloud" style="padding:0">
                  ${model.tags.map((tag) => `<button type="button" class="chip" data-action="tag" data-tag="${esc(tag)}">${icon('tag', 'icon-xs')}${esc(tag)}</button>`).join('')}
                </div>
              </div>` : ''}

            <div class="section">
              <h3 class="section-title">Dosyalar
                <span class="section-tail">
                  ${admin && model.kind !== 'archive' && this.handlers.onOrganize ? `<button type="button" class="link-btn section-action" data-action="organize" title="Dosyaları ayrı modellere böl, başka modele taşı veya kopyaları ayıkla">${icon('layers', 'icon-xs')}Düzenle</button>` : ''}
                  <span class="count">${model.files.length + model.assets.length}</span>
                </span>
              </h3>
              ${this.filesTemplate(model)}
            </div>

            ${model.license ? `
              <div class="section">
                <h3 class="section-title">Lisans</h3>
                <div class="notice">${icon('badge-check')}<div><strong>${esc(model.license)}</strong>${model.licenseText && model.licenseText !== model.license ? `<div style="color:var(--text-3);font-size:12.5px">${esc(model.licenseText)}</div>` : ''}</div></div>
              </div>` : ''}

            ${admin ? this.adminTemplate(model) : ''}

            ${this.similar.length ? `
              <div class="section">
                <h3 class="section-title">Benzer modeller</h3>
                <div class="similar-track scroll-thin">
                  ${this.similar.map((item) => `
                    <button type="button" class="mini-card" data-action="open-model" data-id="${esc(item.id)}">
                      <div class="mini-media">${item.thumb ? `<img src="${esc(item.thumb)}" alt="" loading="lazy" class="${item.flags?.images ? '' : 'is-render'}">` : ''}</div>
                      <span>${esc(item.title)}</span>
                    </button>`).join('')}
                </div>
              </div>` : ''}
          </div>
        </aside>
      </div>`;
  }

  filesTemplate(model) {
    const groups = new Map();
    for (const entry of [...model.files, ...model.assets]) {
      const label = (KIND_GROUPS.find(([kind]) => kind === entry.kind) || [null, 'Diğer'])[1];
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(entry);
    }
    return [...groups.entries()].map(([label, entries]) => `
      <div class="file-group">
        ${groups.size > 1 ? `<div class="file-group-title">${esc(label)} · ${entries.length}</div>` : ''}
        <ul class="file-list">
          ${entries.map((entry) => {
            const isCurrent = this.current && entry.path === this.current.path && entry.member === this.current.member;
            const index = [...model.files, ...model.assets].indexOf(entry);
            const action = entry.viewable ? 'view-file' : entry.kind === 'image' ? 'view-image-file' : '';
            const inner = `
                  <span class="file-ext ${entry.kind === 'model' ? 'is-model' : ''}">${esc(entry.format || '?')}</span>
                  <span class="file-meta">
                    <span class="file-name">${esc(entry.name)}</span>
                    <span class="file-size">${esc(entry.sizeLabel)}${isCurrent ? ' · <strong>görüntüleniyor</strong>' : ''}</span>
                  </span>`;
            return `
              <li class="file-row ${isCurrent ? 'is-current' : ''}" data-file-index="${index}">
                ${action
                  ? `<button type="button" class="file-main" data-action="${action}" data-index="${index}" title="${esc(entry.member || entry.path)}" aria-label="${esc(entry.name)} ${action === 'view-file' ? '3D görüntüle' : 'görseli göster'}">${inner}${icon(action === 'view-file' ? 'eye' : 'image', 'icon-sm file-go')}</button>`
                  : `<div class="file-main" title="${esc(entry.member || entry.path)}">${inner}</div>`}
                ${entry.url && ['document', 'readme', 'license'].includes(entry.kind) ? `<a class="btn btn-ghost btn-sm btn-icon" href="${esc(entry.url)}" target="_blank" rel="noopener" title="Aç" aria-label="Aç">${icon('external-link', 'icon-sm')}</a>` : ''}
                ${entry.downloadUrl ? `<a class="btn btn-ghost btn-sm btn-icon" href="${esc(entry.downloadUrl)}" download title="İndir" aria-label="${esc(entry.name)} indir">${icon('download', 'icon-sm')}</a>` : ''}
              </li>`;
          }).join('')}
        </ul>
      </div>`).join('');
  }

  adminTemplate(model) {
    return `
      <div class="admin-panel">
        <h3 class="section-title">${icon('shield-check', 'icon-sm')} Yönetim</h3>
        <label class="switch">
          <span class="switch-text"><span class="switch-title">Ziyaretçilerden gizle</span><span class="switch-desc">Sadece sen ve paylaşım bağlantısı olanlar görür</span></span>
          <input type="checkbox" data-toggle="hidden" ${model.hidden ? 'checked' : ''}><span class="switch-track"></span>
        </label>
        <label class="switch">
          <span class="switch-text"><span class="switch-title">Basıldı</span><span class="switch-desc">Bu modeli yazdırdığını işaretle</span></span>
          <input type="checkbox" data-toggle="printed" ${model.printed ? 'checked' : ''}><span class="switch-track"></span>
        </label>
        <label class="switch">
          <span class="switch-text"><span class="switch-title">18+ içerik</span><span class="switch-desc">${model.auto?.nsfw ? 'Otomatik algılandı · ' : ''}Ayarlara göre ziyaretçilerden gizlenir</span></span>
          <input type="checkbox" data-toggle="nsfw" ${model.nsfw ? 'checked' : ''}><span class="switch-track"></span>
        </label>
        <div class="field" style="margin-top:12px">
          <label class="field-label" for="note-${esc(model.id)}">Özel not <span class="field-hint">· sadece sen görürsün, otomatik kaydedilir</span></label>
          <textarea class="textarea" id="note-${esc(model.id)}" data-field="note" rows="3" placeholder="Baskı ayarları, filament, hatırlatmalar...">${esc(model.note || '')}</textarea>
        </div>
        ${model.shares?.length ? `
          <div class="section" style="margin-top:16px">
            <h3 class="section-title">Paylaşım bağlantıları <span class="count">${model.shares.length}</span></h3>
            ${model.shares.map((share) => `
              <div class="share-row">
                ${icon('link', 'icon-sm')}
                <div class="share-row-meta"><strong>${esc(share.url)}</strong>${share.views} görüntülenme${share.expired ? ' · süresi doldu' : share.expiresAt ? ` · ${esc(formatDate(share.expiresAt))} tarihine kadar` : ' · süresiz'}</div>
              </div>`).join('')}
            <button type="button" class="link-btn" data-action="share">Bağlantıları yönet</button>
          </div>` : ''}
        ${model.thumbError ? `<div class="notice is-warning" style="margin-top:12px">${icon('triangle-alert')}<div>Önizleme üretilemedi: ${esc(model.thumbError)}</div></div>` : ''}
      </div>`;
  }

  // ─── Sahne ───────────────────────────────────────────────────────

  syncToolbar() {
    if (!this.viewer) return;
    this.root.querySelectorAll('[data-tool]').forEach((button) => {
      button.setAttribute('aria-pressed', String(Boolean(this.viewer.settings[button.dataset.tool])));
    });
  }

  setOverlay(html) {
    const overlay = $('[data-stage-overlay]', this.root);
    if (!overlay) return;
    overlay.hidden = !html;
    overlay.innerHTML = html || '';
  }

  poster(entry = null) {
    const model = this.model;
    const isMain = !entry || (entry.path === model.main.path && entry.member === model.main.member);
    const src = (!isMain && entry.thumbUrl) || model.thumb || model.mainPreview;
    return src ? `<img class="stage-poster" src="${esc(src)}" alt="">` : `<div class="empty-art">${icon('box', 'icon-xl')}</div>`;
  }

  isCurrent(entry) {
    return Boolean(entry && this.current && entry.path === this.current.path && entry.member === this.current.member);
  }

  partIndex() {
    return this.model.files.findIndex((entry) => this.isCurrent(entry));
  }

  markCurrentFile() {
    const all = [...this.model.files, ...this.model.assets];
    this.root.querySelectorAll('.file-row').forEach((row) => {
      const entry = all[Number(row.dataset.fileIndex)];
      const current = entry?.viewable && this.isCurrent(entry);
      row.classList.toggle('is-current', Boolean(current));
      const size = row.querySelector('.file-size');
      if (size && entry) size.innerHTML = `${esc(entry.sizeLabel)}${current ? ' · <strong>görüntüleniyor</strong>' : ''}`;
    });
    const index = this.partIndex();
    const count = $('[data-stage-count]', this.root);
    if (count) count.textContent = index >= 0 ? `${index + 1}/${this.model.files.length}` : '';
    const strip = $('[data-strip]', this.root);
    strip?.querySelectorAll('.part-thumb').forEach((chip) => {
      const active = Number(chip.dataset.index) === index;
      chip.setAttribute('aria-pressed', String(active));
      // Yalnızca şeridin kendisini yatay kaydır; üst kapsayıcıları (panel, pencere) oynatma.
      if (active && strip.scrollWidth > strip.clientWidth) {
        const left = chip.offsetLeft - (strip.clientWidth - chip.offsetWidth) / 2;
        strip.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
      }
    });
  }

  stepPart(direction) {
    const files = this.model?.files || [];
    if (files.length < 2) return;
    const index = this.partIndex();
    const next = files[((index < 0 ? 0 : index + direction) + files.length) % files.length];
    this.showFile(next);
  }

  retryPartImage(image) {
    const tries = Number(image.dataset.tries || 0) + 1;
    if (tries > 8) {
      image.remove();
      return;
    }
    image.dataset.tries = String(tries);
    const base = image.dataset.base || image.getAttribute('src');
    image.dataset.base = base;
    setTimeout(() => {
      if (image.isConnected) image.src = `${base}${base.includes('?') ? '&' : '?'}r=${tries}`;
    }, Math.min(1500 * tries, 6000));
  }

  revealStage() {
    // Dar ekranda sahne yukarıda kalır: yalnızca dikey kaydırarak sahneyi görünür yap.
    const rect = this.stage.getBoundingClientRect();
    if (rect.top >= 0 && rect.top < window.innerHeight * 0.4) return;
    let node = this.stage.parentElement;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) {
        node.scrollBy({ top: rect.top - node.getBoundingClientRect().top - 8, behavior: 'smooth' });
        return;
      }
      node = node.parentElement;
    }
    window.scrollBy({ top: rect.top - 72, behavior: 'smooth' });
  }

  showFile(entry, { force = false, keepLoaded = false } = {}) {
    if (!entry) return;
    this.current = entry;
    const imagePane = $('[data-stage-image]', this.root);
    if (imagePane) imagePane.hidden = true;
    this.root.querySelectorAll('.gallery-thumb').forEach((thumb) => thumb.setAttribute('aria-pressed', String(thumb.dataset.action === 'show-3d')));
    const name = $('[data-stage-name]', this.root);
    if (name) name.textContent = entry.name;
    const dims = $('[data-stage-dims]', this.root);
    if (dims) dims.textContent = '';
    const toolbar = $('[data-toolbar]', this.root);
    this.markCurrentFile();

    if (keepLoaded && this.viewer.object && this.loadedKey === `${entry.path}|${entry.member}`) {
      this.viewer.init();
      this.viewer.start();
      if (toolbar) toolbar.hidden = false;
      const isMain = entry.path === this.model.main.path && entry.member === this.model.main.member;
      if (dims && (this.viewer.dims || this.model.stats?.dims)) {
        dims.textContent = isMain && this.model.stats?.dims ? this.model.stats.dims.replace(/\./g, ',') : this.formatDims(this.viewer.dims);
      }
      return;
    }

    if (!entry.viewable) {
      this.viewer.detach();
      if (toolbar) toolbar.hidden = true;
      this.setOverlay(`${this.poster(entry)}<p><strong>${esc(entry.format.toUpperCase())}</strong> dosyası tarayıcıda 3D olarak önizlenemiyor.</p>
        ${entry.downloadUrl ? `<a class="btn btn-soft" href="${esc(entry.downloadUrl)}" download>${icon('download')}Dosyayı indir</a>` : ''}`);
      return;
    }
    if (!webglAvailable()) {
      if (toolbar) toolbar.hidden = true;
      this.setOverlay(`${this.poster()}<p>Tarayıcınız WebGL desteklemediği için 3D önizleme gösterilemiyor.</p>`);
      return;
    }
    if (!force && entry.size > autoLoadLimit()) {
      this.viewer.detach();
      if (toolbar) toolbar.hidden = true;
      this.setOverlay(`${this.poster(entry)}
        <p>Bu parça <strong>${esc(entry.sizeLabel)}</strong>. 3D önizleme için dosyanın indirilmesi gerekiyor.</p>
        <button type="button" class="btn btn-primary" data-action="load-anyway">${icon('move-3d')}3D önizlemeyi yükle</button>`);
      return;
    }

    if (toolbar) toolbar.hidden = true;
    this.setOverlay(`<div class="spinner" style="color:var(--accent)"></div>
      <div class="stage-progress is-indeterminate"><div data-progress></div></div>
      <p data-progress-text>Model yükleniyor…</p>`);
    const key = `${entry.path}|${entry.member}`;
    this.loadedKey = null;
    this.viewer.load(entry.url, entry.format, {
      meshUrl: entry.meshUrl,
      onProgress: (fraction) => {
        const bar = $('[data-progress]', this.root);
        const text = $('[data-progress-text]', this.root);
        if (!bar || fraction === null) return;
        bar.parentElement.classList.remove('is-indeterminate');
        bar.style.width = `${Math.round(fraction * 100)}%`;
        if (text) text.textContent = `%${Math.round(fraction * 100)} yüklendi`;
      },
    }).then((modelDims) => {
      if (this.current !== entry) return;
      this.loadedKey = key;
      this.setOverlay('');
      if (toolbar) toolbar.hidden = false;
      const isMain = entry.path === this.model.main.path && entry.member === this.model.main.member;
      if (dims) dims.textContent = isMain && this.model.stats?.dims ? this.model.stats.dims.replace(/\./g, ',') : (modelDims ? this.formatDims(modelDims) : '');
    }).catch((error) => {
      if (this.current !== entry) return;
      console.warn('Önizleme hatası', error);
      this.viewer.detach();
      if (entry.format === '3mf' && this.model.mainPreview && entry.path === this.model.main.path) {
        this.setOverlay(`<img class="stage-poster" src="${esc(this.model.mainPreview)}" alt=""><p>3D mesh açılamadı; dosyadaki gömülü önizleme gösteriliyor.</p>`);
        return;
      }
      this.setOverlay(`${this.poster(entry)}<p>${esc(error?.message || 'Model yüklenemedi')}</p>
        <button type="button" class="btn btn-soft" data-action="retry">${icon('refresh-cw')}Tekrar dene</button>`);
    });
  }

  formatDims(values) {
    return `${values.map((value) => (Math.round(value * 10) / 10).toLocaleString('tr-TR')).join(' × ')} mm`;
  }

  showImage(image) {
    const pane = $('[data-stage-image]', this.root);
    if (!pane) return;
    this.viewer.stop();
    this.root.querySelectorAll('.part-thumb').forEach((chip) => chip.setAttribute('aria-pressed', 'false'));
    pane.hidden = false;
    pane.querySelector('img').src = image.url;
    pane.querySelector('img').alt = image.name;
    this.setOverlay('');
    const toolbar = $('[data-toolbar]', this.root);
    if (toolbar) toolbar.hidden = true;
  }

  // ─── Etkileşimler ────────────────────────────────────────────────

  async patch(changes, { quiet = false } = {}) {
    try {
      const updated = await api(`/api/models/${encodeURIComponent(this.model.id)}`, { method: 'PATCH', body: changes });
      if (quiet) this.model = { ...this.model, ...updated };
      this.handlers.onUpdated?.(updated, { quiet });
      if (!quiet) toast('Kaydedildi', 'success', { duration: 1800 });
      return updated;
    } catch (error) {
      toast(error.message, 'error');
      return null;
    }
  }

  handleClick(event) {
    const tool = event.target.closest('[data-tool]');
    if (tool) {
      const option = tool.dataset.tool;
      this.viewer.set(option, !this.viewer.settings[option]);
      return;
    }
    const target = event.target.closest('[data-action]');
    if (!target || !this.root.contains(target)) return;
    const model = this.model;
    const all = [...model.files, ...model.assets];
    switch (target.dataset.action) {
      case 'close': this.handlers.onClose?.(); break;
      case 'prev': this.handlers.onNavigate?.(-1); break;
      case 'next': this.handlers.onNavigate?.(1); break;
      case 'share': this.handlers.onShare?.(model); break;
      case 'load-anyway': this.showFile(this.current, { force: true }); break;
      case 'retry': this.showFile(this.current, { force: true }); break;
      case 'view-file': {
        const entry = all[Number(target.dataset.index)];
        this.showFile(entry, { keepLoaded: this.isCurrent(entry) });
        this.revealStage();
        break;
      }
      case 'view-part': {
        const entry = model.files[Number(target.dataset.index)];
        this.showFile(entry, { keepLoaded: this.isCurrent(entry) });
        break;
      }
      case 'part-prev': this.stepPart(-1); break;
      case 'part-next': this.stepPart(1); break;
      case 'organize': this.handlers.onOrganize?.(model); break;
      case 'view-image-file': this.showImage(all[Number(target.dataset.index)]); this.revealStage(); break;
      case 'show-3d': this.showFile(this.current, { keepLoaded: true }); break;
      case 'show-image': {
        this.root.querySelectorAll('.gallery-thumb').forEach((thumb) => thumb.setAttribute('aria-pressed', String(thumb === target)));
        this.showImage(model.images[Number(target.dataset.index)]);
        break;
      }
      case 'reset-view': this.viewer.resetView(); break;
      case 'fullscreen': {
        const stage = this.stage;
        if (document.fullscreenElement) document.exitFullscreen();
        else stage.requestFullscreen?.().catch(() => toast('Tam ekran desteklenmiyor', 'error'));
        break;
      }
      case 'swatches': this.openSwatches(target); break;
      case 'expand': {
        const prose = $('[data-description]', this.root);
        prose.classList.toggle('is-clamped');
        target.textContent = prose.classList.contains('is-clamped') ? 'Devamını göster' : 'Daha az göster';
        break;
      }
      case 'tag': this.handlers.onTag?.(target.dataset.tag); break;
      case 'open-model': this.handlers.onOpenModel?.(target.dataset.id); break;
      case 'toggle-featured': this.patch({ favorite: !model.featured }); break;
      case 'pick-category': this.openCategoryMenu(target); break;
      case 'pick-file': this.openFileMenu(target); break;
      case 'more': this.openMoreMenu(target); break;
      default: break;
    }
  }

  openSwatches(trigger) {
    const wrap = trigger.parentElement;
    const existing = wrap.querySelector('.swatch-pop');
    if (existing) {
      existing.remove();
      return;
    }
    const pop = document.createElement('div');
    pop.className = 'swatch-pop';
    const options = [...SWATCHES];
    pop.innerHTML = `<div class="swatch-label">Filament rengi</div>
      ${this.viewer.hasOriginalColors ? `<button type="button" class="swatch swatch-original" data-swatch="original" title="Dosyadaki renkler" aria-pressed="${this.viewer.settings.swatch === 'original'}"></button>` : ''}
      ${options.map((item) => `<button type="button" class="swatch" style="background:${item.color}" data-swatch="${item.key}" title="${esc(item.label)}" aria-pressed="${this.viewer.settings.swatch === item.key}"></button>`).join('')}`;
    pop.addEventListener('click', (event) => {
      const button = event.target.closest('[data-swatch]');
      if (!button) return;
      this.viewer.set('swatch', button.dataset.swatch);
      pop.querySelectorAll('[data-swatch]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
    });
    wrap.append(pop);
    const close = (event) => {
      if (!wrap.contains(event.target)) {
        pop.remove();
        document.removeEventListener('pointerdown', close);
      }
    };
    setTimeout(() => document.addEventListener('pointerdown', close), 0);
  }

  openCategoryMenu(trigger) {
    const model = this.model;
    const items = [
      { heading: 'Kategori seç' },
      ...categories.map((category) => ({
        label: category.label,
        icon: category.icon,
        checked: category.key === model.category,
        onClick: () => this.patch({ category: category.key }),
      })),
    ];
    if (model.overrides?.category) {
      items.push({ separator: true });
      items.push({ label: `Otomatiğe dön (${categoryLabel(model.auto.category)})`, icon: 'wand-sparkles', onClick: () => this.patch({ category: null }) });
    }
    openMenu(trigger, items, { align: 'left' });
  }

  openFileMenu(trigger) {
    const items = this.model.files.map((entry) => ({
      label: `${entry.name} · ${entry.sizeLabel}`,
      icon: entry.viewable ? 'box' : 'file',
      checked: this.current && entry.path === this.current.path && entry.member === this.current.member,
      onClick: () => this.showFile(entry),
    }));
    openMenu(trigger, [{ heading: `Parçalar · ${items.length}` }, ...items], { align: 'left' });
  }

  openMoreMenu(trigger) {
    const model = this.model;
    const items = [
      { label: 'Bilgileri düzenle', icon: 'pencil', onClick: () => this.handlers.onEdit?.(model) },
      model.kind === 'folder' && { label: 'Dosya ekle', icon: 'file-plus', onClick: () => this.handlers.onUpload?.(model) },
      model.kind !== 'archive' && this.handlers.onOrganize && { label: 'Dosyaları düzenle / böl', icon: 'layers', onClick: () => this.handlers.onOrganize(model) },
      { label: 'Önizlemeyi yeniden oluştur', icon: 'refresh-cw', onClick: () => this.refreshThumbnail() },
      this.isAdmin && { separator: true },
      this.isAdmin && { label: 'Çöp kutusuna taşı', icon: 'trash-2', danger: true, onClick: () => this.handlers.onDeleted?.(model) },
    ].filter(Boolean);
    openMenu(trigger, items);
  }

  async refreshThumbnail() {
    try {
      await api(`/api/models/${encodeURIComponent(this.model.id)}/thumbnail`, { method: 'POST' });
      toast('Önizleme kuyruğa alındı; birkaç saniye içinde yenilenecek', 'success');
      this.handlers.onUpdated?.({ ...this.model, thumbPending: true });
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  activate() {
    if (this.viewer?.object) this.viewer.start();
  }

  deactivate() {
    this.viewer?.stop();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }

  destroy() {
    this.viewer?.detach();
    this.root.innerHTML = '';
    this.model = null;
    this.current = null;
  }
}
