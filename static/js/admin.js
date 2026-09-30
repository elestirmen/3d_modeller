/**
 * Yönetici diyalogları: giriş, yükleme, düzenleme, paylaşım ve ayarlar.
 */

import {
  $, $$, absoluteUrl, api, boot, categories, categoryLabel, confirmDialog, copyText, createModal, debounce, esc,
  formatBytes, formatDate, formatRelative, getCsrf, icon, qrSvg, setCsrf, shareTargets, toast,
} from './core.js';

const LICENSES = ['CC BY', 'CC BY-SA', 'CC BY-NC', 'CC BY-NC-SA', 'CC BY-ND', 'CC BY-NC-ND', 'CC0 / Kamu malı', 'GPL', 'Standart Dijital Dosya Lisansı', 'Kişisel kullanım'];
const EXPIRY_OPTIONS = [
  ['', 'Süresiz'], ['1', '1 gün'], ['7', '7 gün'], ['30', '30 gün'], ['90', '90 gün'], ['365', '1 yıl'],
];

// ─── Giriş ──────────────────────────────────────────────────────────

function loginFormHtml() {
  return `
    <form class="login-form" novalidate>
      <div class="login-lock">${icon('lock', 'icon-lg')}</div>
      <h2>Yönetici girişi</h2>
      <p>Yükleme, düzenleme ve paylaşım için şifreni gir.</p>
      <div class="input-group">
        ${icon('key-round')}
        <input class="input" type="password" name="password" autocomplete="current-password" placeholder="Şifre" required aria-label="Şifre">
        <button type="button" class="btn btn-ghost btn-icon btn-sm input-action" data-reveal aria-label="Şifreyi göster">${icon('eye', 'icon-sm')}</button>
      </div>
      <div class="caps-warning" data-caps hidden>Caps Lock açık</div>
      <div class="form-error" data-error role="alert"></div>
      <button type="submit" class="btn btn-primary btn-lg btn-block" style="margin-top:6px">${icon('log-in')}Giriş yap</button>
    </form>`;
}

function bindLoginForm(form, onSuccess) {
  const input = form.querySelector('input[name="password"]');
  const error = form.querySelector('[data-error]');
  const caps = form.querySelector('[data-caps]');
  const submit = form.querySelector('button[type="submit"]');
  form.querySelector('[data-reveal]').addEventListener('click', (event) => {
    const reveal = input.type === 'password';
    input.type = reveal ? 'text' : 'password';
    event.currentTarget.innerHTML = icon(reveal ? 'eye-off' : 'eye', 'icon-sm');
    input.focus();
  });
  input.addEventListener('keydown', (event) => {
    caps.hidden = !event.getModifierState?.('CapsLock');
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!input.value) {
      error.textContent = 'Şifreni gir.';
      input.focus();
      return;
    }
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner"></span>Kontrol ediliyor…';
    error.textContent = '';
    try {
      const result = await api('/api/auth/login', { method: 'POST', body: { password: input.value } });
      setCsrf(result.csrf);
      onSuccess?.();
    } catch (err) {
      error.textContent = err.message;
      input.select();
      submit.disabled = false;
      submit.innerHTML = `${icon('log-in')}Giriş yap`;
    }
  });
  setTimeout(() => input.focus(), 60);
}

export function openLogin({ onSuccess } = {}) {
  const dialog = createModal({ body: loginFormHtml(), className: 'login-card' });
  dialog.style.maxWidth = '400px';
  const close = document.createElement('button');
  close.className = 'btn btn-ghost btn-icon btn-sm';
  close.style.cssText = 'position:absolute;top:14px;right:14px';
  close.setAttribute('aria-label', 'Kapat');
  close.dataset.close = '';
  close.innerHTML = icon('x');
  $('.modal-card', dialog).style.position = 'relative';
  $('.modal-card', dialog).prepend(close);
  bindLoginForm($('form', dialog), () => {
    dialog.close();
    onSuccess?.();
  });
  return dialog;
}

export function renderLockedScreen(container, { onSuccess }) {
  container.innerHTML = `
    <div class="locked-screen">
      <div class="modal-card login-card">
        <div class="modal-body">
          <div class="notice" style="margin-bottom:18px;text-align:left">${icon('lock')}<div>Bu arşiv şu an özel. Paylaşılan bir bağlantın varsa doğrudan onu açabilirsin.</div></div>
          ${loginFormHtml()}
        </div>
      </div>
    </div>`;
  bindLoginForm($('form', container), onSuccess);
}

// ─── Etiket düzenleyici ─────────────────────────────────────────────

function tagEditor(root, initial = [], suggestions = []) {
  let tags = [...initial];
  const listId = `tags-${Math.random().toString(36).slice(2)}`;
  root.innerHTML = `<div class="tag-editor"><input type="text" list="${listId}" placeholder="Etiket yaz, Enter'a bas" aria-label="Etiket ekle"><datalist id="${listId}">${suggestions.map((tag) => `<option value="${esc(tag)}"></option>`).join('')}</datalist></div>`;
  const editor = root.firstElementChild;
  const input = editor.querySelector('input');
  const render = () => {
    editor.querySelectorAll('.tag-token').forEach((token) => token.remove());
    tags.forEach((tag, index) => {
      const token = document.createElement('span');
      token.className = 'tag-token';
      token.innerHTML = `${esc(tag)}<button type="button" aria-label="${esc(tag)} etiketini kaldır" data-remove="${index}">${icon('x', 'icon-xs')}</button>`;
      editor.insertBefore(token, input);
    });
  };
  const add = (value) => {
    const tag = value.trim().replace(/,$/, '').trim();
    if (!tag) return;
    if (!tags.some((item) => item.toLocaleLowerCase('tr') === tag.toLocaleLowerCase('tr'))) tags.push(tag.slice(0, 40));
    input.value = '';
    render();
  };
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      add(input.value);
    } else if (event.key === 'Backspace' && !input.value && tags.length) {
      tags.pop();
      render();
    }
  });
  input.addEventListener('change', () => {
    if (suggestions.includes(input.value)) add(input.value);
  });
  input.addEventListener('blur', () => add(input.value));
  editor.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      tags.splice(Number(remove.dataset.remove), 1);
      render();
    } else {
      input.focus();
    }
  });
  render();
  return {
    get: () => {
      add(input.value);
      return [...tags];
    },
    set: (value) => {
      tags = [...value];
      render();
    },
  };
}

function categoryOptions(selected, { autoKey = null } = {}) {
  const autoOption = autoKey !== null ? `<option value="">Otomatik (${esc(categoryLabel(autoKey))})</option>` : '';
  return autoOption + categories.map((category) => `<option value="${esc(category.key)}" ${category.key === selected ? 'selected' : ''}>${esc(category.label)}</option>`).join('');
}

function switchHtml(name, title, description, checked) {
  return `<label class="switch"><span class="switch-text"><span class="switch-title">${esc(title)}</span>${description ? `<span class="switch-desc">${esc(description)}</span>` : ''}</span><input type="checkbox" name="${name}" ${checked ? 'checked' : ''}><span class="switch-track"></span></label>`;
}

// ─── Yükleme ────────────────────────────────────────────────────────

function sendChunk(url, blob, offset, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.setRequestHeader('X-CSRF-Token', getCsrf());
    xhr.setRequestHeader('X-Upload-Offset', String(offset));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (event) => onProgress?.(event.loaded);
    xhr.onload = () => {
      let payload = {};
      try { payload = JSON.parse(xhr.responseText || '{}'); } catch { /* yoksay */ }
      if (xhr.status === 200 || xhr.status === 409) resolve(payload);
      else reject(Object.assign(new Error(payload.error || `Yükleme hatası (${xhr.status})`), { status: xhr.status }));
    };
    xhr.onerror = () => reject(new Error('Ağ bağlantısı kesildi'));
    xhr.onabort = () => reject(Object.assign(new Error('İptal edildi'), { aborted: true }));
    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(blob);
  });
}

async function uploadAll(files, { onFileProgress, signal }) {
  const session = await api('/api/uploads', {
    method: 'POST',
    body: { files: files.map((file) => ({ name: file.name, size: file.size, path: file.webkitRelativePath || '' })) },
    signal,
  });
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    let offset = 0;
    onFileProgress(index, 0);
    while (offset < file.size) {
      const end = Math.min(offset + session.chunkSize, file.size);
      let attempt = 0;
      for (;;) {
        try {
          const result = await sendChunk(
            `/api/uploads/${session.id}/${index}`,
            file.slice(offset, end),
            offset,
            (loaded) => onFileProgress(index, Math.min(offset + loaded, file.size)),
            signal,
          );
          offset = result.received ?? end;
          break;
        } catch (error) {
          if (error.aborted || signal?.aborted) throw error;
          if (error.status && error.status < 500 && error.status !== 408) throw error;
          attempt += 1;
          if (attempt > 5) throw error;
          await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
        }
      }
      onFileProgress(index, offset);
    }
    onFileProgress(index, file.size, true);
  }
  return session.id;
}

function fileIconName(name) {
  const ext = name.split('.').pop().toLowerCase();
  if (['stl', '3mf', 'obj', 'ply', 'glb', 'gltf', 'fbx'].includes(ext)) return 'box';
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) return 'image';
  if (ext === 'zip') return 'package';
  return 'file-text';
}

export function openUpload({ target = null, allTags = [], onDone } = {}) {
  const formats = boot.uploadFormats || [];
  const accept = formats.map((ext) => `.${ext}`).join(',');
  const body = `
    <div class="${target ? '' : 'upload-grid'}">
      <div>
        <div class="dropzone" data-dropzone tabindex="0" role="button" aria-label="Dosya seç veya sürükle bırak">
          <div class="dropzone-art">${icon('cloud-upload', 'icon-lg')}</div>
          <strong>Dosyaları buraya sürükle</strong>
          <small>STL, 3MF, OBJ, PLY, GLB, görseller, PDF ve ZIP. ZIP arşivleri otomatik açılır. Büyük dosyalar parça parça gönderilir.</small>
          <div class="dropzone-actions">
            <button type="button" class="btn btn-sm" data-pick="files">${icon('file-plus', 'icon-sm')}Dosya seç</button>
            <button type="button" class="btn btn-sm" data-pick="folder">${icon('folder-plus', 'icon-sm')}Klasör seç</button>
          </div>
          <input type="file" multiple accept="${esc(accept)}" data-input="files" hidden>
          <input type="file" multiple webkitdirectory data-input="folder" hidden>
        </div>
        <div class="upload-files scroll-thin" data-files></div>
        <div class="upload-summary" data-summary hidden></div>
      </div>
      ${target ? '' : `
        <form data-meta novalidate>
          <div class="field">
            <label class="field-label" for="up-title">Başlık</label>
            <input class="input" id="up-title" name="title" maxlength="160" placeholder="Dosya adından otomatik doldurulur">
          </div>
          <div class="field">
            <label class="field-label" for="up-category">Kategori <span class="suggest-hint" data-suggest hidden>${icon('sparkles', 'icon-xs')}<span></span></span></label>
            <select class="select" id="up-category" name="category"><option value="">Otomatik belirle</option>${categoryOptions(null)}</select>
          </div>
          <div class="field">
            <span class="field-label">Etiketler</span>
            <div data-tags></div>
          </div>
          <div class="field">
            <label class="field-label" for="up-desc">Açıklama</label>
            <textarea class="textarea" id="up-desc" name="description" rows="3" maxlength="6000" placeholder="Baskı notları, parça listesi, montaj..."></textarea>
          </div>
          <div class="field-row" style="margin-top:14px">
            <div class="field">
              <label class="field-label" for="up-author">Tasarımcı</label>
              <input class="input" id="up-author" name="author" maxlength="120" placeholder="Opsiyonel">
            </div>
            <div class="field">
              <label class="field-label" for="up-license">Lisans</label>
              <input class="input" id="up-license" name="license" maxlength="120" list="license-options" placeholder="Opsiyonel">
              <datalist id="license-options">${LICENSES.map((item) => `<option value="${esc(item)}"></option>`).join('')}</datalist>
            </div>
          </div>
          <div class="field">
            <label class="field-label" for="up-source">Kaynak bağlantısı</label>
            <input class="input" id="up-source" name="source_url" type="url" maxlength="500" placeholder="https://www.printables.com/model/...">
          </div>
          <div style="margin-top:8px">
            ${switchHtml('hidden', 'Ziyaretçilerden gizle', 'Yalnızca sen ve paylaşım bağlantısı olanlar görür', false)}
            ${switchHtml('nsfw', '18+ içerik', 'Ayarlarına göre ziyaretçilerden gizlenir', false)}
          </div>
        </form>`}
    </div>`;

  const dialog = createModal({
    title: target ? 'Dosya ekle' : 'Model yükle',
    description: target ? `“${target.title}” modeline yeni dosyalar ekle` : 'Arşivine yeni bir model ekle',
    iconName: 'cloud-upload',
    className: target ? '' : 'modal-wide',
    body,
    footer: `
      <span class="field-hint" data-status></span>
      <span class="spacer"></span>
      <button type="button" class="btn btn-ghost" data-cancel>Vazgeç</button>
      <button type="button" class="btn btn-primary" data-submit disabled>${icon('upload')}Yükle</button>`,
  });

  let files = [];
  let controller = null;
  let busy = false;
  const list = $('[data-files]', dialog);
  const summary = $('[data-summary]', dialog);
  const submit = $('[data-submit]', dialog);
  const status = $('[data-status]', dialog);
  const form = $('[data-meta]', dialog);
  const tags = form ? tagEditor($('[data-tags]', dialog), [], allTags) : null;
  const titleInput = form?.querySelector('[name="title"]');
  let titleTouched = false;
  titleInput?.addEventListener('input', () => { titleTouched = true; suggest(); });

  const suggest = debounce(async () => {
    if (!form || !files.length) return;
    try {
      const result = await api('/api/classify', {
        method: 'POST',
        body: { title: titleInput.value, files: files.map((file) => file.webkitRelativePath || file.name) },
      });
      if (!titleTouched && !titleInput.value && result.title) titleInput.placeholder = result.title;
      const hint = $('[data-suggest]', dialog);
      hint.hidden = !result.category;
      hint.querySelector('span').textContent = `Önerilen: ${categoryLabel(result.category)}`;
      hint.dataset.value = result.category;
      if (result.nsfw) form.querySelector('[name="nsfw"]').checked = true;
      if (result.tags?.length && !tags.get().length) tags.set(result.tags);
    } catch { /* öneri opsiyonel */ }
  }, 350);

  $('[data-suggest]', dialog)?.addEventListener('click', (event) => {
    const value = event.currentTarget.dataset.value;
    if (value) form.querySelector('[name="category"]').value = value;
  });

  const renderFiles = () => {
    const total = files.reduce((sum, file) => sum + file.size, 0);
    list.innerHTML = files.map((file, index) => `
      <div class="upload-file" data-file="${index}">
        <span class="file-ext is-model">${icon(fileIconName(file.name), 'icon-sm')}</span>
        <div class="file-meta">
          <div class="file-name" title="${esc(file.webkitRelativePath || file.name)}">${esc(file.webkitRelativePath || file.name)}</div>
          <div class="upload-bar"><div></div></div>
        </div>
        <span class="file-size">${esc(formatBytes(file.size))}</span>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-remove="${index}" aria-label="Kaldır" ${busy ? 'disabled' : ''}>${icon('x', 'icon-sm')}</button>
      </div>`).join('');
    summary.hidden = !files.length;
    summary.innerHTML = `<span>${files.length} dosya</span><span>${esc(formatBytes(total))}</span>`;
    submit.disabled = !files.length || busy;
  };

  const addFiles = (incoming) => {
    const allowed = new Set(formats);
    const skipped = [];
    for (const file of incoming) {
      const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
      if (!allowed.has(ext) || file.name.startsWith('.')) {
        skipped.push(file.name);
        continue;
      }
      if (!files.some((item) => item.name === file.name && item.size === file.size && (item.webkitRelativePath || '') === (file.webkitRelativePath || ''))) {
        files.push(file);
      }
    }
    if (skipped.length) toast(`${skipped.length} dosya desteklenmediği için atlandı`, 'info');
    renderFiles();
    suggest();
  };

  const dropzone = $('[data-dropzone]', dialog);
  const inputs = { files: $('[data-input="files"]', dialog), folder: $('[data-input="folder"]', dialog) };
  dialog.addEventListener('click', (event) => {
    const pick = event.target.closest('[data-pick]');
    if (pick) {
      event.stopPropagation();
      inputs[pick.dataset.pick].click();
      return;
    }
    const remove = event.target.closest('[data-remove]');
    if (remove && !busy) {
      files.splice(Number(remove.dataset.remove), 1);
      renderFiles();
    }
  });
  dropzone.addEventListener('click', (event) => {
    if (!event.target.closest('button')) inputs.files.click();
  });
  dropzone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      inputs.files.click();
    }
  });
  Object.values(inputs).forEach((input) => input.addEventListener('change', () => {
    addFiles([...input.files]);
    input.value = '';
  }));
  ['dragenter', 'dragover'].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add('is-over');
  }));
  ['dragleave', 'drop'].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove('is-over');
  }));
  dropzone.addEventListener('drop', async (event) => {
    const items = [...(event.dataTransfer?.items || [])];
    const entries = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
    if (entries.some((entry) => entry.isDirectory)) {
      addFiles(await readEntries(entries));
    } else {
      addFiles([...(event.dataTransfer?.files || [])]);
    }
  });

  const setBusy = (value) => {
    busy = value;
    dialog.querySelectorAll('input, select, textarea, [data-pick]').forEach((element) => { element.disabled = value; });
    submit.disabled = value || !files.length;
    renderFilesProgressOnly();
  };
  const renderFilesProgressOnly = () => {
    $$('[data-remove]', list).forEach((button) => { button.disabled = busy; });
  };

  const collectMeta = () => {
    if (!form) return { target: target.id };
    const data = new FormData(form);
    return {
      title: (data.get('title') || '').trim(),
      category: data.get('category') || null,
      tags: tags.get(),
      description: (data.get('description') || '').trim(),
      author: (data.get('author') || '').trim(),
      license: (data.get('license') || '').trim(),
      source_url: (data.get('source_url') || '').trim(),
      hidden: form.querySelector('[name="hidden"]').checked,
      nsfw: form.querySelector('[name="nsfw"]').checked || undefined,
    };
  };

  submit.addEventListener('click', async () => {
    if (!files.length || busy) return;
    const meta = collectMeta();
    if (meta.source_url && !/^https?:\/\//i.test(meta.source_url)) {
      toast('Kaynak bağlantısı http:// veya https:// ile başlamalı', 'error');
      return;
    }
    controller = new AbortController();
    setBusy(true);
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0) || 1;
    const sent = files.map(() => 0);
    const started = performance.now();
    status.textContent = 'Yükleniyor…';
    try {
      const uploadId = await uploadAll(files, {
        signal: controller.signal,
        onFileProgress: (index, bytes, done) => {
          sent[index] = bytes;
          const row = list.querySelector(`[data-file="${index}"]`);
          if (row) {
            row.querySelector('.upload-bar > div').style.width = `${files[index].size ? Math.round((bytes / files[index].size) * 100) : 100}%`;
            row.classList.toggle('is-done', Boolean(done));
          }
          const total = sent.reduce((sum, value) => sum + value, 0);
          const seconds = (performance.now() - started) / 1000;
          const speed = seconds > 1 ? total / seconds : 0;
          status.textContent = `%${Math.round((total / totalBytes) * 100)} · ${formatBytes(total)} / ${formatBytes(totalBytes)}${speed ? ` · ${formatBytes(speed)}/sn` : ''}`;
        },
      });
      status.textContent = 'Dosyalar işleniyor, önizleme hazırlanıyor…';
      const result = await api(`/api/uploads/${uploadId}/complete`, { method: 'POST', body: meta });
      showSuccess(result.models);
    } catch (error) {
      if (error.aborted) {
        status.textContent = 'İptal edildi';
      } else {
        status.textContent = '';
        toast(error.message || 'Yükleme başarısız', 'error', { duration: 6000 });
      }
      setBusy(false);
    }
  });

  $('[data-cancel]', dialog).addEventListener('click', () => {
    if (busy && controller) {
      controller.abort();
      return;
    }
    dialog.close();
  });
  dialog.addEventListener('cancel', (event) => {
    if (busy) event.preventDefault();
  });

  const showSuccess = (models) => {
    busy = false;
    const first = models[0];
    $('.modal-body', dialog).innerHTML = `
      <div class="success-state">
        <div class="empty-art">${icon('circle-check', 'icon-xl')}</div>
        <h3 style="margin:0;font-size:18px">${target ? 'Dosyalar eklendi' : models.length > 1 ? `${models.length} model eklendi` : 'Model yüklendi'}</h3>
        <p style="margin:0;color:var(--text-3)">${esc(first?.title || '')}${first ? ` · ${esc(categoryLabel(first.category))}` : ''}</p>
      </div>`;
    $('.modal-foot', dialog).innerHTML = `
      <span class="spacer"></span>
      ${target ? '' : '<button type="button" class="btn" data-again>Yeni yükleme</button>'}
      <button type="button" class="btn btn-primary" data-open>${icon('eye')}Modeli aç</button>`;
    $('[data-open]', dialog).addEventListener('click', () => {
      dialog.close();
      onDone?.(models, { open: true });
    });
    $('[data-again]', dialog)?.addEventListener('click', () => {
      dialog.close();
      onDone?.(models, { open: false });
      openUpload({ target, allTags, onDone });
    });
    onDone?.(models, { open: false, silent: true });
  };

  renderFiles();
  return dialog;
}

async function readEntries(entries, prefix = '') {
  const files = [];
  for (const entry of entries) {
    if (entry.isFile) {
      const file = await new Promise((resolve) => entry.file(resolve, () => resolve(null)));
      if (file) {
        Object.defineProperty(file, 'webkitRelativePath', { value: `${prefix}${file.name}` });
        files.push(file);
      }
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const children = [];
      for (;;) {
        const batch = await new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
        if (!batch.length) break;
        children.push(...batch);
      }
      files.push(...(await readEntries(children, `${prefix}${entry.name}/`)));
    }
  }
  return files;
}

// ─── Düzenleme ──────────────────────────────────────────────────────

export function openEdit(model, { allTags = [], onSaved } = {}) {
  const images = model.images || [];
  const body = `
    <form data-edit novalidate>
      <div class="field">
        <label class="field-label" for="ed-title">Başlık ${model.overrides?.title ? '' : '<span class="badge">Otomatik</span>'}</label>
        <input class="input" id="ed-title" name="title" maxlength="160" value="${esc(model.title)}" placeholder="${esc(model.auto?.title || '')}">
        <span class="field-hint">Boş bırakırsan klasör adından üretilen başlık kullanılır: ${esc(model.auto?.title || '')}</span>
      </div>
      <div class="field-row" style="margin-top:14px">
        <div class="field">
          <label class="field-label" for="ed-category">Kategori</label>
          <select class="select" id="ed-category" name="category">${categoryOptions(model.overrides?.category ? model.category : '', { autoKey: model.auto?.category })}</select>
        </div>
        <div class="field">
          <label class="field-label" for="ed-author">Tasarımcı</label>
          <input class="input" id="ed-author" name="author" maxlength="120" value="${esc(model.author || '')}">
        </div>
      </div>
      <div class="field">
        <span class="field-label">Etiketler ${model.overrides?.tags ? '<button type="button" class="link-btn" data-reset-tags style="margin:0 0 0 auto">Otomatiğe dön</button>' : '<span class="badge">Otomatik</span>'}</span>
        <div data-tags></div>
      </div>
      <div class="field">
        <label class="field-label" for="ed-desc">Açıklama</label>
        <textarea class="textarea" id="ed-desc" name="description" rows="4" maxlength="6000">${esc(model.description || '')}</textarea>
      </div>
      <div class="field-row" style="margin-top:14px">
        <div class="field">
          <label class="field-label" for="ed-source">Kaynak bağlantısı</label>
          <input class="input" id="ed-source" name="source_url" type="url" maxlength="500" value="${esc(model.sourceUrl || '')}" placeholder="https://">
        </div>
        <div class="field">
          <label class="field-label" for="ed-license">Lisans</label>
          <input class="input" id="ed-license" name="license" maxlength="120" list="ed-license-options" value="${esc(model.license || '')}">
          <datalist id="ed-license-options">${LICENSES.map((item) => `<option value="${esc(item)}"></option>`).join('')}</datalist>
        </div>
      </div>
      ${images.length ? `
        <div class="field">
          <span class="field-label">Kapak görseli</span>
          <div class="cover-grid">
            <button type="button" class="cover-option" data-cover="" aria-pressed="${!model.cover}">${icon('wand-sparkles')}Otomatik</button>
            ${images.map((image) => `<button type="button" class="cover-option" data-cover="${esc(image.path)}" aria-pressed="${model.cover === image.path}" title="${esc(image.name)}"><img src="${esc(image.url)}" alt="" loading="lazy"></button>`).join('')}
          </div>
        </div>` : ''}
      <div style="margin-top:12px">
        ${switchHtml('favorite', 'Öne çıkar', 'Ana sayfadaki “Öne çıkanlar” bölümünde gösterilir', model.featured)}
        ${switchHtml('printed', 'Basıldı', '', model.printed)}
        ${switchHtml('hidden', 'Ziyaretçilerden gizle', '', model.hidden)}
        ${switchHtml('nsfw', '18+ içerik', model.auto?.nsfw ? 'Otomatik olarak algılandı' : '', model.nsfw)}
      </div>
    </form>`;
  const dialog = createModal({
    title: 'Modeli düzenle',
    description: model.path,
    iconName: 'pencil',
    className: 'modal-wide',
    body,
    footer: `<span class="spacer"></span><button type="button" class="btn btn-ghost" data-close>Vazgeç</button><button type="button" class="btn btn-primary" data-save>${icon('check')}Kaydet</button>`,
  });
  const form = $('[data-edit]', dialog);
  const tags = tagEditor($('[data-tags]', dialog), model.tags, allTags);
  let resetTags = false;
  let cover = model.cover || '';
  $('[data-reset-tags]', dialog)?.addEventListener('click', (event) => {
    resetTags = true;
    tags.set(model.auto?.tags || []);
    event.currentTarget.remove();
  });
  dialog.querySelectorAll('[data-cover]').forEach((button) => button.addEventListener('click', () => {
    cover = button.dataset.cover;
    dialog.querySelectorAll('[data-cover]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
  }));
  $('[data-save]', dialog).addEventListener('click', async () => {
    const data = new FormData(form);
    const changes = {};
    const title = (data.get('title') || '').trim();
    if (title !== model.title) changes.title = title || null;
    const category = data.get('category') || null;
    if (category !== (model.overrides?.category ? model.category : null)) changes.category = category;
    const nextTags = tags.get();
    if (resetTags && JSON.stringify(nextTags) === JSON.stringify(model.auto?.tags || [])) changes.tags = null;
    else if (JSON.stringify(nextTags) !== JSON.stringify(model.tags)) changes.tags = nextTags;
    for (const [field, current] of [['description', model.description || ''], ['author', model.author || ''], ['license', model.license || ''], ['source_url', model.sourceUrl || '']]) {
      const value = (data.get(field) || '').trim();
      if (value !== current) changes[field] = value;
    }
    for (const [field, current] of [['favorite', model.featured], ['printed', model.printed], ['hidden', model.hidden], ['nsfw', model.nsfw]]) {
      const value = form.querySelector(`[name="${field}"]`).checked;
      if (value !== Boolean(current)) changes[field] = value;
    }
    if ((cover || '') !== (model.cover || '')) changes.cover = cover || null;
    if (!Object.keys(changes).length) {
      dialog.close();
      return;
    }
    const button = $('[data-save]', dialog);
    button.disabled = true;
    try {
      const updated = await api(`/api/models/${encodeURIComponent(model.id)}`, { method: 'PATCH', body: changes });
      toast('Model güncellendi', 'success');
      dialog.close();
      onSaved?.(updated);
    } catch (error) {
      toast(error.message, 'error');
      button.disabled = false;
    }
  });
  return dialog;
}

// ─── Paylaşım ───────────────────────────────────────────────────────

function shareBoxHtml(url, title) {
  return `
    <div class="share-box">
      <div style="min-width:0;width:100%">
        <div class="share-link">
          <input class="input" value="${esc(url)}" readonly aria-label="Paylaşım bağlantısı" data-share-url>
          <button type="button" class="btn btn-primary" data-copy="${esc(url)}">${icon('copy')}Kopyala</button>
        </div>
        <div class="share-targets">
          ${navigator.share ? `<button type="button" class="btn btn-sm" data-native>${icon('share-2', 'icon-sm')}Paylaş…</button>` : ''}
          ${shareTargets(url, title).map((item) => `<a class="btn btn-sm" href="${esc(item.href)}" target="_blank" rel="noopener">${icon(item.icon, 'icon-sm')}${esc(item.label)}</a>`).join('')}
          <a class="btn btn-sm btn-ghost" href="${esc(url)}" target="_blank" rel="noopener">${icon('external-link', 'icon-sm')}Aç</a>
        </div>
      </div>
      <div class="qr" aria-label="QR kod">${qrSvg(url)}</div>
    </div>`;
}

function bindShareBox(root, url, title) {
  root.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', async () => {
    if (await copyText(button.dataset.copy)) {
      toast('Bağlantı kopyalandı', 'success', { duration: 1800 });
      button.innerHTML = `${icon('check')}Kopyalandı`;
      setTimeout(() => { button.innerHTML = `${icon('copy')}Kopyala`; }, 1600);
    }
  }));
  root.querySelector('[data-native]')?.addEventListener('click', () => {
    navigator.share({ title, url }).catch(() => {});
  });
  root.querySelector('[data-share-url]')?.addEventListener('focus', (event) => event.target.select());
}

export function openShare(model, { admin = false, onChange } = {}) {
  if (!admin) {
    const url = absoluteUrl(`/m/${model.id}`);
    const dialog = createModal({
      title: 'Modeli paylaş',
      description: model.title,
      iconName: 'share-2',
      body: shareBoxHtml(url, model.title),
    });
    bindShareBox(dialog, url, model.title);
    return dialog;
  }

  const dialog = createModal({
    title: 'Paylaşım bağlantısı',
    description: model.title,
    iconName: 'link',
    className: 'modal-wide',
    body: '<div data-share-body></div>',
  });
  let shares = [...(model.shares || [])];
  const bodyEl = $('[data-share-body]', dialog);

  const render = (highlight = null) => {
    const active = shares.filter((share) => !share.expired);
    const featured = highlight || active[0];
    bodyEl.innerHTML = `
      ${featured ? shareBoxHtml(absoluteUrl(featured.url), model.title) : `
        <div class="notice">${icon('info')}<div>Bu model için henüz bağlantı yok. Oluşturduğun bağlantı, model gizli olsa veya arşiv özel olsa bile çalışır. İstediğin zaman iptal edebilirsin.</div></div>`}
      <div class="section">
        <h3 class="section-title">Yeni bağlantı</h3>
        <div class="share-options">
          <div class="field">
            <label class="field-label" for="sh-exp">Geçerlilik süresi</label>
            <select class="select" id="sh-exp" data-exp>${EXPIRY_OPTIONS.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select>
          </div>
          <div class="field">
            <label class="field-label" for="sh-note">Not (sadece sen görürsün)</label>
            <input class="input" id="sh-note" data-note maxlength="120" placeholder="Örn. Ahmet için">
          </div>
        </div>
        ${switchHtml('allow_download', 'İndirmeye izin ver', 'Kapalıyken indirme düğmeleri ve CAD/PDF/ZIP gibi ek dosyalar gizlenir; 3D önizleme için model verisi yine tarayıcıya aktarılır', true)}
        <button type="button" class="btn btn-primary" data-create style="margin-top:6px">${icon('plus')}Bağlantı oluştur</button>
      </div>
      ${shares.length ? `
        <div class="section">
          <h3 class="section-title">Bu modelin bağlantıları <span class="count">${shares.length}</span></h3>
          ${shares.map((share) => `
            <div class="share-row">
              ${icon(share.expired ? 'clock' : 'link', 'icon-sm')}
              <div class="share-row-meta">
                <strong>${esc(absoluteUrl(share.url))}</strong>
                ${share.note ? `${esc(share.note)} · ` : ''}${share.views} görüntülenme${share.lastViewedAt ? ` (son: ${esc(formatRelative(share.lastViewedAt))})` : ''} · ${share.expired ? 'süresi doldu' : share.expiresAt ? `${esc(formatDate(share.expiresAt))} tarihine kadar` : 'süresiz'} · ${share.allowDownload ? 'indirilebilir' : 'yalnızca görüntüleme'}
              </div>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-copy="${esc(absoluteUrl(share.url))}" title="Kopyala" aria-label="Bağlantıyı kopyala">${icon('copy', 'icon-sm')}</button>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-toggle-dl="${esc(share.token)}" title="${share.allowDownload ? 'İndirmeyi kapat' : 'İndirmeyi aç'}" aria-label="İndirme iznini değiştir">${icon(share.allowDownload ? 'download' : 'eye', 'icon-sm')}</button>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-revoke="${esc(share.token)}" title="İptal et" aria-label="Bağlantıyı iptal et">${icon('trash-2', 'icon-sm')}</button>
            </div>`).join('')}
        </div>` : ''}`;
    if (featured) bindShareBox(bodyEl, absoluteUrl(featured.url), model.title);
    else bodyEl.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', () => copyText(button.dataset.copy).then(() => toast('Bağlantı kopyalandı', 'success'))));
    $('[data-create]', bodyEl).addEventListener('click', async (event) => {
      event.currentTarget.disabled = true;
      try {
        const share = await api(`/api/models/${encodeURIComponent(model.id)}/shares`, {
          method: 'POST',
          body: {
            expires_days: $('[data-exp]', bodyEl).value ? Number($('[data-exp]', bodyEl).value) : null,
            allow_download: $('[name="allow_download"]', bodyEl).checked,
            note: $('[data-note]', bodyEl).value,
          },
        });
        shares = [share, ...shares];
        render(share);
        await copyText(absoluteUrl(share.url));
        toast('Bağlantı oluşturuldu ve kopyalandı', 'success');
        onChange?.();
      } catch (error) {
        toast(error.message, 'error');
        event.currentTarget.disabled = false;
      }
    });
    bodyEl.querySelectorAll('[data-revoke]').forEach((button) => button.addEventListener('click', async () => {
      const ok = await confirmDialog({ title: 'Bağlantı iptal edilsin mi?', message: 'Bu bağlantıyı kullanan kişiler artık modeli göremez.', confirmText: 'İptal et', danger: true, iconName: 'trash-2' });
      if (!ok) return;
      try {
        await api(`/api/shares/${encodeURIComponent(button.dataset.revoke)}`, { method: 'DELETE' });
        shares = shares.filter((share) => share.token !== button.dataset.revoke);
        render();
        toast('Bağlantı iptal edildi', 'success');
        onChange?.();
      } catch (error) {
        toast(error.message, 'error');
      }
    }));
    bodyEl.querySelectorAll('[data-toggle-dl]').forEach((button) => button.addEventListener('click', async () => {
      const share = shares.find((item) => item.token === button.dataset.toggleDl);
      try {
        const updated = await api(`/api/shares/${encodeURIComponent(share.token)}`, { method: 'PATCH', body: { allow_download: !share.allowDownload } });
        shares = shares.map((item) => (item.token === updated.token ? updated : item));
        render(featured && featured.token === updated.token ? updated : featured);
        onChange?.();
      } catch (error) {
        toast(error.message, 'error');
      }
    }));
  };
  render();
  return dialog;
}

// ─── Ayarlar ────────────────────────────────────────────────────────

export function openSettings({ onChanged, initialTab = 'general' } = {}) {
  const tabs = [
    ['general', 'Genel'], ['privacy', 'Gizlilik'], ['maintenance', 'Bakım'], ['shares', 'Paylaşımlar'], ['security', 'Güvenlik'],
  ];
  const dialog = createModal({
    title: 'Ayarlar',
    description: 'Arşivini yönet',
    iconName: 'settings',
    className: 'modal-wide',
    body: '<div data-panel></div>',
  });
  const card = $('.modal-card', dialog);
  const tabBar = document.createElement('div');
  tabBar.className = 'tabs';
  tabBar.setAttribute('role', 'tablist');
  tabBar.innerHTML = tabs.map(([key, label]) => `<button type="button" class="tab" role="tab" data-tab="${key}" aria-selected="false">${label}</button>`).join('');
  card.insertBefore(tabBar, $('.modal-body', dialog));
  const panel = $('[data-panel]', dialog);
  let settings = null;
  let poll = null;

  const save = async (changes) => {
    try {
      settings = await api('/api/settings', { method: 'PATCH', body: changes });
      toast('Ayarlar kaydedildi', 'success', { duration: 1600 });
      onChanged?.(settings);
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  const views = {
    async general() {
      settings = settings || await api('/api/settings');
      panel.innerHTML = `
        <div class="field">
          <label class="field-label" for="st-title">Site başlığı</label>
          <input class="input" id="st-title" maxlength="60" value="${esc(settings.site_title)}">
        </div>
        <div class="field">
          <label class="field-label" for="st-tagline">Alt başlık</label>
          <input class="input" id="st-tagline" maxlength="140" value="${esc(settings.site_tagline)}">
        </div>
        <button type="button" class="btn btn-primary" data-save-general style="margin-top:16px">${icon('check')}Kaydet</button>`;
      $('[data-save-general]', panel).addEventListener('click', () => save({ site_title: $('#st-title', panel).value, site_tagline: $('#st-tagline', panel).value }));
    },
    async privacy() {
      settings = settings || await api('/api/settings');
      panel.innerHTML = `
        ${switchHtml('public_browsing', 'Arşiv herkese açık', 'Kapalıyken ziyaretçiler giriş ekranı görür; paylaşım bağlantıları çalışmaya devam eder', settings.public_browsing)}
        ${switchHtml('public_downloads', 'Ziyaretçiler dosya indirebilsin', 'Kapalıyken indirme düğmeleri ve ek dosyalar (CAD, PDF, ZIP) ziyaretçilere kapanır; 3D önizleme için model verisi yine tarayıcıya aktarılır.', settings.public_downloads)}
        ${switchHtml('hide_nsfw', '18+ içeriği ziyaretçilerden gizle', 'Otomatik algılanan veya elle işaretlenen modeller', settings.hide_nsfw)}
        <div class="notice is-warning" style="margin-top:14px">${icon('triangle-alert')}<div>Bazı modeller (ör. MakerWorld “Standart Dijital Dosya Lisansı”, NC/ND lisanslar) yeniden dağıtıma izin vermeyebilir. Bu modelleri gizleyebilir veya ziyaretçi indirmelerini kapatabilirsin.</div></div>`;
      panel.querySelectorAll('input[type="checkbox"]').forEach((input) => input.addEventListener('change', () => save({ [input.name]: input.checked })));
    },
    async maintenance() {
      panel.innerHTML = '<div class="status-grid" data-status-grid></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px"></div>';
      const actions = panel.lastElementChild;
      actions.innerHTML = `
        <button type="button" class="btn" data-scan>${icon('refresh-cw')}Kütüphaneyi tara</button>
        <button type="button" class="btn" data-thumbs>${icon('image')}Eksik önizlemeleri üret</button>
        <button type="button" class="btn btn-ghost" data-thumbs-all>${icon('wand-sparkles')}Tümünü yeniden üret</button>`;
      const renderStatus = async () => {
        const status = await api('/api/admin/status');
        const done = status.thumbnails.done;
        const total = status.models || 1;
        $('[data-status-grid]', panel).innerHTML = `
          <div class="status-card"><div class="stat-label">${icon('box')}Model</div><div class="stat-value">${status.models}</div></div>
          <div class="status-card"><div class="stat-label">${icon('image')}Önizleme</div><div class="stat-value">${done} / ${status.models}${status.thumbnails.queued ? ` · ${status.thumbnails.queued} sırada` : ''}</div><div class="progress-line"><div style="width:${Math.round((done / total) * 100)}%"></div></div></div>
          <div class="status-card"><div class="stat-label">${icon('clock')}Son tarama</div><div class="stat-value">${status.lastScan ? esc(formatRelative(status.lastScan)) : '—'}</div></div>
          <div class="status-card"><div class="stat-label">${icon('hard-drive')}Boş disk</div><div class="stat-value">${status.disk ? `${esc(status.disk.free)} / ${esc(status.disk.total)}` : '—'}</div></div>
          ${status.thumbnails.failed ? `<div class="status-card" style="grid-column:1/-1"><div class="stat-label">${icon('triangle-alert')}Önizlemesi üretilemeyen</div><div class="stat-value">${status.thumbnails.failed} model</div></div>` : ''}`;
      };
      await renderStatus();
      poll = setInterval(() => renderStatus().catch(() => {}), 3000);
      $('[data-scan]', panel).addEventListener('click', async (event) => {
        event.currentTarget.disabled = true;
        try {
          const result = await api('/api/scan', { method: 'POST' });
          toast(`Tarama tamamlandı: ${result.total} model · ${result.added} yeni · ${result.removed} kaldırıldı`, 'success');
          onChanged?.();
          renderStatus();
        } catch (error) {
          toast(error.message, 'error');
        }
        event.currentTarget.disabled = false;
      });
      $('[data-thumbs]', panel).addEventListener('click', async () => {
        const result = await api('/api/admin/thumbnails', { method: 'POST', body: { all: false } });
        toast(result.queued ? `${result.queued} önizleme kuyruğa alındı` : 'Tüm önizlemeler güncel', 'success');
      });
      $('[data-thumbs-all]', panel).addEventListener('click', async () => {
        const ok = await confirmDialog({ title: 'Tüm önizlemeler yeniden üretilsin mi?', message: 'Büyük arşivlerde birkaç dakika sürebilir. Bu sırada site kullanılabilir.', confirmText: 'Yeniden üret' });
        if (!ok) return;
        const result = await api('/api/admin/thumbnails', { method: 'POST', body: { all: true } });
        toast(`${result.queued} önizleme kuyruğa alındı`, 'success');
      });
    },
    async shares() {
      const { shares } = await api('/api/shares');
      panel.innerHTML = shares.length ? shares.map((share) => `
        <div class="share-row">
          ${icon(share.expired ? 'clock' : 'link', 'icon-sm')}
          <div class="share-row-meta">
            <strong style="font-family:var(--font)">${esc(share.modelTitle)}</strong>
            ${esc(absoluteUrl(share.url))} · ${share.views} görüntülenme · ${share.expired ? 'süresi doldu' : share.expiresAt ? `${esc(formatDate(share.expiresAt))} tarihine kadar` : 'süresiz'}${share.note ? ` · ${esc(share.note)}` : ''}
          </div>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-copy="${esc(absoluteUrl(share.url))}" aria-label="Kopyala">${icon('copy', 'icon-sm')}</button>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-revoke="${esc(share.token)}" aria-label="İptal et">${icon('trash-2', 'icon-sm')}</button>
        </div>`).join('') : `<div class="empty" style="padding:30px 0"><div class="empty-art">${icon('link', 'icon-xl')}</div><h3>Henüz paylaşım yok</h3><p>Bir modelin detayında “Paylaş” ile bağlantı oluşturabilirsin.</p></div>`;
      panel.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', () => copyText(button.dataset.copy).then(() => toast('Bağlantı kopyalandı', 'success'))));
      panel.querySelectorAll('[data-revoke]').forEach((button) => button.addEventListener('click', async () => {
        const ok = await confirmDialog({ title: 'Bağlantı iptal edilsin mi?', message: 'Bu bağlantıyı kullanan kişiler artık modeli göremez.', confirmText: 'İptal et', danger: true, iconName: 'trash-2' });
        if (!ok) return;
        await api(`/api/shares/${encodeURIComponent(button.dataset.revoke)}`, { method: 'DELETE' });
        toast('Bağlantı iptal edildi', 'success');
        views.shares();
      }));
    },
    async security() {
      panel.innerHTML = `
        <form data-password novalidate>
          <div class="field">
            <label class="field-label" for="pw-current">Mevcut şifre</label>
            <input class="input" id="pw-current" type="password" autocomplete="current-password" required>
          </div>
          <div class="field-row" style="margin-top:14px">
            <div class="field">
              <label class="field-label" for="pw-new">Yeni şifre</label>
              <input class="input" id="pw-new" type="password" autocomplete="new-password" minlength="8" required>
            </div>
            <div class="field">
              <label class="field-label" for="pw-repeat">Yeni şifre (tekrar)</label>
              <input class="input" id="pw-repeat" type="password" autocomplete="new-password" minlength="8" required>
            </div>
          </div>
          <p class="field-hint" style="margin:10px 0 0">En az 8 karakter. Şifre değişince diğer cihazlardaki oturumlar kapanır.</p>
          <div class="form-error" data-error></div>
          <button type="submit" class="btn btn-primary">${icon('lock')}Şifreyi değiştir</button>
        </form>`;
      $('[data-password]', panel).addEventListener('submit', async (event) => {
        event.preventDefault();
        const error = $('[data-error]', panel);
        const next = $('#pw-new', panel).value;
        if (next.length < 8) { error.textContent = 'Yeni şifre en az 8 karakter olmalı.'; return; }
        if (next !== $('#pw-repeat', panel).value) { error.textContent = 'Yeni şifreler eşleşmiyor.'; return; }
        try {
          await api('/api/auth/password', { method: 'POST', body: { current: $('#pw-current', panel).value, new: next } });
          error.textContent = '';
          event.target.reset();
          toast('Şifre değiştirildi', 'success');
        } catch (err) {
          error.textContent = err.message;
        }
      });
    },
  };

  const show = async (key) => {
    clearInterval(poll);
    tabBar.querySelectorAll('[data-tab]').forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.tab === key)));
    panel.innerHTML = '<div style="display:grid;place-items:center;padding:40px"><div class="spinner" style="color:var(--accent)"></div></div>';
    try {
      await views[key]();
    } catch (error) {
      panel.innerHTML = `<div class="notice is-danger">${icon('triangle-alert')}<div>${esc(error.message)}</div></div>`;
    }
  };
  tabBar.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-tab]');
    if (tab) show(tab.dataset.tab);
  });
  dialog.addEventListener('close', () => clearInterval(poll));
  show(initialTab);
  return dialog;
}
