/**
 * Yönetici diyalogları: giriş, yükleme, düzenleme, paylaşım ve ayarlar.
 */

import {
  $, $$, absoluteUrl, api, boot, categories, categoryLabel, confirmDialog, copyText, createModal, debounce, esc,
  fold, formatBytes, formatDate, formatRelative, getCsrf, icon, qrSvg, setCsrf, shareTargets, toast,
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
      <h2>Giriş yap</h2>
      <p>Kullanıcı adın ve şifrenle giriş yap.</p>
      <div class="input-group" style="margin-bottom:10px">
        ${icon('user-round')}
        <input class="input" type="text" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="Kullanıcı adı" required aria-label="Kullanıcı adı">
      </div>
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
  const userInput = form.querySelector('input[name="username"]');
  try { userInput.value = localStorage.getItem('lastUsername') || ''; } catch { /* yoksay */ }
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
    if (!userInput.value.trim()) {
      error.textContent = 'Kullanıcı adını gir.';
      userInput.focus();
      return;
    }
    if (!input.value) {
      error.textContent = 'Şifreni gir.';
      input.focus();
      return;
    }
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner"></span>Kontrol ediliyor…';
    error.textContent = '';
    try {
      const username = userInput.value.trim().toLowerCase();
      const result = await api('/api/auth/login', { method: 'POST', body: { username, password: input.value } });
      setCsrf(result.csrf);
      try { localStorage.setItem('lastUsername', username); } catch { /* yoksay */ }
      onSuccess?.(result);
    } catch (err) {
      error.textContent = err.message;
      input.select();
      submit.disabled = false;
      submit.innerHTML = `${icon('log-in')}Giriş yap`;
    }
  });
  setTimeout(() => (userInput.value ? input : userInput).focus(), 60);
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
  bindLoginForm($('form', dialog), (result) => {
    dialog.close();
    onSuccess?.(result);
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

const MODEL_EXTS = new Set(['stl', '3mf', 'obj', 'ply', 'glb', 'gltf', 'fbx', 'zip']);
const isModelFile = (file) => MODEL_EXTS.has(file.name.split('.').pop().toLowerCase());

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
        ${target ? '' : `
          <div class="upload-mode" data-mode-box hidden>
            <div class="segmented" role="radiogroup" aria-label="Dosyalar nasıl eklensin">
              <button type="button" role="radio" data-mode="single" aria-checked="true">${icon('box', 'icon-sm')}Tek model</button>
              <button type="button" role="radio" data-mode="separate" aria-checked="false">${icon('layers', 'icon-sm')}Ayrı modeller <span class="count" data-group-count></span></button>
            </div>
            <span class="field-hint" data-mode-hint></span>
          </div>`}
        <div class="upload-files scroll-thin" data-files></div>
        <div class="upload-summary" data-summary hidden></div>
        <label class="switch switch-compact" style="margin-top:8px">
          <span class="switch-text"><span class="switch-title">Arşivde zaten olan dosyaları atla</span><span class="switch-desc">Birebir aynı dosya başka bir modelde varsa tekrar eklenmez</span></span>
          <input type="checkbox" name="skip_duplicates" checked><span class="switch-track"></span>
        </label>
      </div>
      ${target ? '' : `
        <form data-meta novalidate>
          <div data-single-only>
            <div class="field">
              <label class="field-label" for="up-title">Başlık</label>
              <input class="input" id="up-title" name="title" maxlength="160" placeholder="Dosya adından otomatik doldurulur">
            </div>
          </div>
          <div class="notice" data-separate-only hidden>${icon('info')}<div>Her grup ayrı bir model olur; adlarını soldaki listeden değiştirebilir, dosyaları gruplar arasında taşıyabilirsin. Kategori her model için ayrı belirlenir.</div></div>
          <div class="field">
            <label class="field-label" for="up-category">Kategori <span class="suggest-hint" data-suggest hidden>${icon('sparkles', 'icon-xs')}<span></span></span></label>
            <select class="select" id="up-category" name="category"><option value="">Otomatik belirle</option>${categoryOptions(null)}</select>
          </div>
          <div class="field">
            <span class="field-label">Etiketler <span class="field-hint" data-separate-only hidden>· tüm modellere eklenir</span></span>
            <div data-tags></div>
          </div>
          <div data-single-only>
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
          </div>
          <div style="margin-top:8px">
            ${switchHtml('hidden', 'Ziyaretçilerden gizle', boot.newModelsHidden ? 'Yeni modeller varsayılan olarak gizli (Ayarlar → Gizlilik)' : 'Yalnızca sen ve paylaşım bağlantısı olanlar görür', Boolean(boot.newModelsHidden))}
            ${switchHtml('nsfw', '18+ içerik', 'Ayarlarına göre ziyaretçilerden gizlenir', false)}
          </div>
        </form>`}
    </div>`;

  const dialog = createModal({
    title: target ? 'Dosya ekle' : 'Model yükle',
    description: target ? `“${target.title}” modeline yeni dosyalar ekle` : 'Arşivine yeni modeller ekle',
    iconName: 'cloud-upload',
    className: target ? '' : 'modal-wide',
    body,
    footer: `
      <span class="field-hint" data-status></span>
      <span class="spacer"></span>
      <button type="button" class="btn btn-ghost" data-cancel>Vazgeç</button>
      <button type="button" class="btn btn-primary" data-submit disabled>${icon('upload')}<span data-submit-label>Yükle</span></button>`,
  });

  let files = [];
  let controller = null;
  let busy = false;
  // Ayrı modeller modu: her grup bir model. groupsTouched: kullanıcı grupları elle değiştirdi mi.
  let mode = 'single';
  let modeTouched = false;
  let groups = [];
  let groupsTouched = false;
  let tagsTouched = false;
  const list = $('[data-files]', dialog);
  const summary = $('[data-summary]', dialog);
  const submit = $('[data-submit]', dialog);
  const status = $('[data-status]', dialog);
  const form = $('[data-meta]', dialog);
  const modeBox = $('[data-mode-box]', dialog);
  const tags = form ? tagEditor($('[data-tags]', dialog), [], allTags) : null;
  const titleInput = form?.querySelector('[name="title"]');
  let titleTouched = false;
  titleInput?.addEventListener('input', () => { titleTouched = true; suggest(); });
  $('[data-tags]', dialog)?.addEventListener('keydown', () => { tagsTouched = true; });

  const modelCount = () => files.filter(isModelFile).length;
  const fromFolder = () => files.some((file) => file.webkitRelativePath && file.webkitRelativePath.includes('/'));
  const separate = () => mode === 'separate' && groups.length > 0;

  const setGroupsFromSuggestion = (suggestion) => {
    groups = (suggestion || [])
      .map((group) => ({ title: group.title, files: group.files.map((index) => files[index]).filter(Boolean) }))
      .filter((group) => group.files.length);
    const assigned = new Set(groups.flatMap((group) => group.files));
    const stray = files.filter((file) => !assigned.has(file));
    if (stray.length && groups.length) groups[0].files.push(...stray);
    groupsTouched = false;
  };

  const updateMode = () => {
    if (!modeBox) return;
    const many = modelCount() >= 2 && groups.length >= 2;
    modeBox.hidden = !many;
    if (!many) mode = 'single';
    else if (!modeTouched) mode = !fromFolder() && modelCount() >= 6 && groups.length >= 3 ? 'separate' : 'single';
    modeBox.querySelectorAll('[data-mode]').forEach((button) => button.setAttribute('aria-checked', String(button.dataset.mode === mode)));
    $('[data-group-count]', dialog).textContent = groups.length ? String(groups.length) : '';
    $('[data-mode-hint]', dialog).textContent = mode === 'separate'
      ? `${files.length} dosya ${groups.length} ayrı model olarak eklenecek. Gruplar dosya adlarından önerildi.`
      : `${files.length} dosyanın hepsi tek bir modelin parçası olacak.`;
    dialog.querySelectorAll('[data-single-only]').forEach((node) => { node.hidden = mode === 'separate'; });
    dialog.querySelectorAll('[data-separate-only]').forEach((node) => { node.hidden = mode !== 'separate'; });
    const hint = $('[data-suggest]', dialog);
    if (hint && mode === 'separate') hint.hidden = true;
  };

  const suggest = debounce(async () => {
    if (!form || !files.length) return;
    const snapshot = [...files];
    try {
      const result = await api('/api/classify', {
        method: 'POST',
        body: { title: titleInput.value, files: snapshot.map((file) => file.webkitRelativePath || file.name) },
      });
      if (snapshot.length !== files.length || snapshot.some((file, index) => file !== files[index])) return;
      if (!groupsTouched) setGroupsFromSuggestion(result.groups);
      updateMode();
      if (!titleTouched && !titleInput.value && result.title) titleInput.placeholder = result.title;
      const hint = $('[data-suggest]', dialog);
      hint.hidden = !result.category || mode === 'separate';
      hint.querySelector('span').textContent = `Önerilen: ${categoryLabel(result.category)}`;
      hint.dataset.value = result.category;
      if (result.nsfw) form.querySelector('[name="nsfw"]').checked = true;
      if (mode !== 'separate' && result.tags?.length && !tags.get().length && !tagsTouched) tags.set(result.tags);
      renderFiles();
    } catch { /* öneri opsiyonel */ }
  }, 350);

  $('[data-suggest]', dialog)?.addEventListener('click', (event) => {
    const value = event.currentTarget.dataset.value;
    if (value) form.querySelector('[name="category"]').value = value;
  });

  modeBox?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-mode]');
    if (!button || busy) return;
    mode = button.dataset.mode;
    modeTouched = true;
    // Tüm dosyalardan çıkarılan etiket önerisi ayrı modellere uymaz.
    if (mode === 'separate' && !tagsTouched) tags?.set([]);
    updateMode();
    renderFiles();
  });

  const fileRow = (file) => {
    const index = files.indexOf(file);
    const groupSelect = separate() ? `
      <select class="select select-sm upload-group-select" data-group-of="${index}" ${busy ? 'disabled' : ''} aria-label="${esc(file.name)} hangi modele">
        ${groups.map((group, groupIndex) => `<option value="${groupIndex}" ${group.files.includes(file) ? 'selected' : ''}>${esc(group.title)}</option>`).join('')}
        <option value="new">＋ Yeni model</option>
      </select>` : '';
    return `
      <div class="upload-file" data-file="${index}">
        <span class="file-ext is-model">${icon(fileIconName(file.name), 'icon-sm')}</span>
        <div class="file-meta">
          <div class="file-name" title="${esc(file.webkitRelativePath || file.name)}">${esc(file.webkitRelativePath || file.name)}</div>
          <div class="upload-bar"><div></div></div>
        </div>
        <span class="file-size">${esc(formatBytes(file.size))}</span>
        ${groupSelect}
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-remove="${index}" aria-label="Kaldır" ${busy ? 'disabled' : ''}>${icon('x', 'icon-sm')}</button>
      </div>`;
  };

  const renderFiles = () => {
    const total = files.reduce((sum, file) => sum + file.size, 0);
    if (separate()) {
      list.classList.add('is-grouped');
      list.innerHTML = groups.map((group, groupIndex) => `
        <div class="upload-group">
          <div class="upload-group-head">
            ${icon('box', 'icon-sm')}
            <input class="input input-sm" value="${esc(group.title)}" maxlength="160" data-group-title="${groupIndex}" aria-label="Model adı" ${busy ? 'disabled' : ''}>
            <span class="count">${group.files.length}</span>
          </div>
          ${group.files.map(fileRow).join('')}
        </div>`).join('');
    } else {
      list.classList.remove('is-grouped');
      list.innerHTML = files.map(fileRow).join('');
    }
    summary.hidden = !files.length;
    summary.innerHTML = `<span>${files.length} dosya${separate() ? ` · ${groups.length} model` : ''}</span><span>${esc(formatBytes(total))}</span>`;
    submit.disabled = !files.length || busy;
    $('[data-submit-label]', dialog).textContent = separate() ? `Yükle · ${groups.length} model` : 'Yükle';
  };

  list.addEventListener('change', (event) => {
    const select = event.target.closest('[data-group-of]');
    if (select) {
      const file = files[Number(select.dataset.groupOf)];
      groups.forEach((group) => { group.files = group.files.filter((item) => item !== file); });
      if (select.value === 'new') groups.push({ title: fileTitle(file.name), files: [file] });
      else groups[Number(select.value)].files.push(file);
      groups = groups.filter((group) => group.files.length);
      groupsTouched = true;
      updateMode();
      renderFiles();
      return;
    }
    const title = event.target.closest('[data-group-title]');
    if (title) {
      const group = groups[Number(title.dataset.groupTitle)];
      if (group) group.title = title.value.trim() || group.title;
      groupsTouched = true;
    }
  });

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
    groupsTouched = false;
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
      const file = files[Number(remove.dataset.remove)];
      files = files.filter((item) => item !== file);
      groups.forEach((group) => { group.files = group.files.filter((item) => item !== file); });
      groups = groups.filter((group) => group.files.length);
      updateMode();
      renderFiles();
      suggest();
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
    dialog.querySelectorAll('input, select, textarea, [data-pick], [data-mode]').forEach((element) => { element.disabled = value; });
    submit.disabled = value || !files.length;
    $$('[data-remove]', list).forEach((button) => { button.disabled = busy; });
  };

  const collectMeta = () => {
    const skip = $('[name="skip_duplicates"]', dialog).checked;
    if (!form) return { target: target.id, skip_duplicates: skip };
    const data = new FormData(form);
    const meta = {
      category: data.get('category') || null,
      tags: tags.get(),
      hidden: form.querySelector('[name="hidden"]').checked,
      nsfw: form.querySelector('[name="nsfw"]').checked || undefined,
      skip_duplicates: skip,
    };
    if (separate()) {
      meta.groups = groups.map((group) => ({ title: group.title, files: group.files.map((file) => files.indexOf(file)) }));
      return meta;
    }
    return {
      ...meta,
      title: (data.get('title') || '').trim(),
      description: (data.get('description') || '').trim(),
      author: (data.get('author') || '').trim(),
      license: (data.get('license') || '').trim(),
      source_url: (data.get('source_url') || '').trim(),
    };
  };

  submit.addEventListener('click', async () => {
    if (!files.length || busy) return;
    const meta = collectMeta();
    if (meta.source_url && !/^https?:\/\//i.test(meta.source_url)) {
      toast('Kaynak bağlantısı http:// veya https:// ile başlamalı', 'error');
      return;
    }
    const empty = separate() && groups.find((group) => !group.files.some(isModelFile));
    if (empty) {
      toast(`“${empty.title}” grubunda 3D model dosyası yok; dosyalarını başka bir gruba taşı`, 'error', { duration: 6000 });
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
      status.textContent = meta.skip_duplicates ? 'Kopyalar kontrol ediliyor, önizleme hazırlanıyor…' : 'Dosyalar işleniyor, önizleme hazırlanıyor…';
      const result = await api(`/api/uploads/${uploadId}/complete`, { method: 'POST', body: meta });
      showSuccess(result.models, result.skipped || []);
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

  const showSuccess = (models, skipped) => {
    busy = false;
    const first = models[0];
    const heading = !models.length ? 'Yeni dosya eklenmedi'
      : target ? 'Dosyalar eklendi' : models.length > 1 ? `${models.length} model eklendi` : 'Model yüklendi';
    const skippedHtml = skipped.length ? `
      <div class="notice is-warning skipped-list">${icon('copy')}<div>
        <strong>${skipped.length} dosya arşivde zaten vardı, tekrar eklenmedi:</strong>
        <ul>${skipped.slice(0, 12).map((item) => `<li>${esc(item.name)}${item.models[0] ? ` → <button type="button" class="link-btn" data-open-existing="${esc(item.models[0].id)}">${esc(item.models[0].title)}</button>` : ''}</li>`).join('')}${skipped.length > 12 ? `<li>… ve ${skipped.length - 12} dosya daha</li>` : ''}</ul>
      </div></div>` : '';
    $('.modal-body', dialog).innerHTML = `
      <div class="success-state">
        <div class="empty-art">${icon(models.length ? 'circle-check' : 'info', 'icon-xl')}</div>
        <h3 style="margin:0;font-size:18px">${heading}</h3>
        ${first ? `<p style="margin:0;color:var(--text-3)">${models.length > 1 ? models.slice(0, 4).map((item) => esc(item.title)).join(' · ') + (models.length > 4 ? ' …' : '') : `${esc(first.title)} · ${esc(categoryLabel(first.category))}`}</p>` : ''}
      </div>
      ${skippedHtml}`;
    $('.modal-foot', dialog).innerHTML = `
      <span class="spacer"></span>
      ${target ? '' : '<button type="button" class="btn" data-again>Yeni yükleme</button>'}
      ${first ? `<button type="button" class="btn btn-primary" data-open>${icon('eye')}${models.length > 1 ? 'İlk modeli aç' : 'Modeli aç'}</button>` : '<button type="button" class="btn btn-primary" data-close>Tamam</button>'}`;
    $('[data-open]', dialog)?.addEventListener('click', () => {
      dialog.close();
      onDone?.(models, { open: true });
    });
    dialog.querySelectorAll('[data-open-existing]').forEach((button) => button.addEventListener('click', () => {
      dialog.close();
      onDone?.([{ id: button.dataset.openExisting }], { open: true });
    }));
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

// ─── Dosyaları yeniden gruplama ─────────────────────────────────────

/** Klasör modelleri arasından arama yaparak bir hedef seç. Seçilen kartla (veya null) çözülür. */
export function pickModel({ models, exclude = null, title = 'Hedef model seç' } = {}) {
  return new Promise((resolve) => {
    const candidates = models.filter((item) => item.kind === 'folder' && item.id !== exclude);
    const dialog = createModal({
      title,
      description: 'Dosyalar seçtiğin modelin klasörüne taşınır. Yalnızca klasör tabanlı modeller listelenir.',
      iconName: 'folder',
      body: `
        <div class="input-group" style="margin-bottom:12px">${icon('search')}<input class="input" type="search" data-q placeholder="Model ara…" aria-label="Model ara"></div>
        <div class="picker-list scroll-thin" data-results></div>`,
      footer: '<span class="spacer"></span><button type="button" class="btn btn-ghost" data-close>Vazgeç</button>',
    });
    let chosen = null;
    const input = $('[data-q]', dialog);
    const results = $('[data-results]', dialog);
    const render = () => {
      const query = fold(input.value.trim());
      const words = query.split(/\s+/).filter(Boolean);
      const matches = candidates.filter((item) => words.every((word) => (item.search || fold(item.title)).includes(word))).slice(0, 80);
      results.innerHTML = matches.length ? matches.map((item) => `
        <button type="button" class="picker-item" data-id="${esc(item.id)}">
          <span class="picker-thumb">${item.thumb ? `<img src="${esc(item.thumb)}" alt="" loading="lazy">` : icon('box')}</span>
          <span class="picker-meta"><strong>${esc(item.title)}</strong><small>${esc(categoryLabel(item.category))} · ${item.fileCount} dosya${item.hidden ? ' · gizli' : ''}</small></span>
        </button>`).join('') : `<p class="field-hint" style="padding:12px 4px">Eşleşen klasör modeli yok.</p>`;
    };
    input.addEventListener('input', debounce(render, 90));
    results.addEventListener('click', (event) => {
      const button = event.target.closest('[data-id]');
      if (!button) return;
      chosen = candidates.find((item) => item.id === button.dataset.id) || null;
      dialog.close();
    });
    dialog.addEventListener('close', () => resolve(chosen));
    render();
    setTimeout(() => input.focus(), 50);
  });
}

function fileTitle(name) {
  return name.replace(/\.[^.]+$/, '').replace(/[+_]+/g, ' ').replace(/\s*\(\d+\)\s*$/, '').replace(/\s+/g, ' ').trim() || name;
}

/**
 * Bir modelin dosyalarını yeni modellere böl, başka modele taşı veya çöp kutusuna at.
 * onDone(result): sunucunun yanıtı ({source, created, targets, trashed, ...}).
 */
export async function openOrganize(model, { models = [], onDone } = {}) {
  const dialog = createModal({
    title: 'Dosyaları düzenle',
    description: `${model.title} · yanlış gruplanan dosyaları ayır, başka modele taşı veya kopyaları ayıkla`,
    iconName: 'layers',
    className: 'modal-wide organize-dialog',
    body: `<div class="organize-loading"><span class="spinner"></span>Dosyalar ve arşivdeki kopyaları kontrol ediliyor…</div>`,
    footer: `
      <span class="organize-summary" data-summary></span>
      <span class="spacer"></span>
      <button type="button" class="btn btn-ghost" data-close>Vazgeç</button>
      <button type="button" class="btn btn-primary" data-apply disabled>${icon('check')}Uygula</button>`,
  });
  let info;
  try {
    info = await api(`/api/models/${encodeURIComponent(model.id)}/organize`);
  } catch (error) {
    toast(error.message, 'error');
    dialog.close();
    return;
  }
  if (!dialog.open) return;

  const files = info.files;
  const byPath = new Map(files.map((file) => [file.path, file]));
  const dest = new Map(files.map((file) => [file.path, 'keep']));
  const selected = new Set();
  let groups = [];
  const targets = [];
  let counter = 0;

  const newGroup = (title) => {
    counter += 1;
    const group = { key: `g${counter}`, title: title.slice(0, 160) };
    groups.push(group);
    return group.key;
  };
  const targetKey = (card) => {
    let target = targets.find((item) => item.id === card.id);
    if (!target) {
      target = { key: `m:${card.id}`, id: card.id, title: card.title };
      targets.push(target);
    }
    return target.key;
  };
  const isModel = (file) => file.kind === 'model';
  const otherCopies = (file) => file.copies.filter((copy) => !copy.sameModel);
  const pruneGroups = () => {
    const used = new Set(dest.values());
    groups = groups.filter((group) => used.has(group.key));
  };

  const presets = {
    smart() {
      groups = [];
      dest.forEach((_, path) => dest.set(path, 'keep'));
      // Modelin adını taşıyan (yoksa ana dosyayı içeren) grup yerinde kalır; model kimliği ve paylaşımları korunur.
      const sourceTitle = fold(info.title);
      const titleMatch = info.suggestion.findIndex((group) => fold(group.title) === sourceTitle);
      const mainGroup = info.suggestion.findIndex((group) => group.files.includes(info.main));
      const keep = titleMatch >= 0 ? titleMatch : Math.max(0, mainGroup);
      info.suggestion.forEach((group, index) => {
        const key = index === keep ? 'keep' : newGroup(group.title);
        group.files.forEach((path) => dest.set(path, key));
      });
      if (info.canTrash) {
        // Başka bir modelde birebir aynısı olan dosyalar çöpe; aynı modeldeki ikizlerden yalnızca biri kalır.
        const kept = new Set();
        for (const file of files) {
          if (otherCopies(file).length) dest.set(file.path, 'trash');
          else if (file.copies.some((copy) => copy.sameModel && kept.has(copy.path))) dest.set(file.path, 'trash');
          else kept.add(file.path);
        }
      }
      pruneGroups();
    },
    each() {
      groups = [];
      dest.forEach((_, path) => dest.set(path, 'keep'));
      const byStem = new Map();
      files.filter(isModel).forEach((file) => {
        if (file.path === info.main) {
          byStem.set(fold(fileTitle(file.name)), 'keep');
          return;
        }
        const key = newGroup(file.title || fileTitle(file.name));
        dest.set(file.path, key);
        byStem.set(fold(fileTitle(file.name)), key);
      });
      files.filter((file) => !isModel(file)).forEach((file) => {
        dest.set(file.path, byStem.get(fold(fileTitle(file.name))) || 'keep');
      });
      pruneGroups();
    },
    reset() {
      groups = [];
      dest.forEach((_, path) => dest.set(path, 'keep'));
    },
  };

  const optionsHtml = (value) => `
    <option value="keep" ${value === 'keep' ? 'selected' : ''}>Bu modelde kalsın</option>
    <optgroup label="Yeni model">
      ${groups.map((group) => `<option value="${group.key}" ${value === group.key ? 'selected' : ''}>＋ ${esc(group.title)}</option>`).join('')}
      <option value="new">＋ Yeni model oluştur</option>
    </optgroup>
    <optgroup label="Başka modele taşı">
      ${targets.map((target) => `<option value="${target.key}" ${value === target.key ? 'selected' : ''}>→ ${esc(target.title)}</option>`).join('')}
      <option value="pick">→ Model seç…</option>
    </optgroup>
    ${info.canTrash ? `<option value="trash" ${value === 'trash' ? 'selected' : ''}>Çöp kutusuna at</option>` : ''}`;

  $('.modal-body', dialog).innerHTML = `
    <div class="organize">
      <div class="organize-presets">
        <button type="button" class="btn btn-sm" data-preset="smart">${icon('sparkles', 'icon-sm')}Akıllı öneri</button>
        <button type="button" class="btn btn-sm" data-preset="each">${icon('files', 'icon-sm')}Her dosya ayrı model</button>
        <button type="button" class="btn btn-sm btn-ghost" data-preset="reset">${icon('refresh-cw', 'icon-sm')}Sıfırla</button>
        <span class="field-hint">Akıllı öneri, adı benzeyen dosyaları bir arada tutar${info.canTrash ? ' ve arşivde aynısı olanları çöpe ayırır' : ''}. Uygulamadan önce her satırı değiştirebilirsin.</span>
      </div>
      <div class="organize-body">
        <div class="organize-main">
          <div class="organize-bulk" data-bulk hidden>
            <label class="organize-check"><input type="checkbox" data-check-all aria-label="Tümünü seç"></label>
            <span data-bulk-count></span>
            <select class="select select-sm" data-bulk-dest aria-label="Seçilenleri taşı"></select>
          </div>
          <ul class="organize-list scroll-thin" data-list></ul>
        </div>
        <aside class="organize-groups scroll-thin" data-groups></aside>
      </div>
    </div>`;

  const list = $('[data-list]', dialog);
  const groupsBox = $('[data-groups]', dialog);
  const bulk = $('[data-bulk]', dialog);
  const summary = $('[data-summary]', dialog);
  const apply = $('[data-apply]', dialog);

  const renderGroups = () => {
    const counts = new Map();
    dest.forEach((value) => counts.set(value, (counts.get(value) || 0) + 1));
    const chips = [
      ...groups.map((group) => `
        <div class="organize-group">
          ${icon('plus', 'icon-sm')}
          <input class="input input-sm" value="${esc(group.title)}" maxlength="160" data-group-title="${group.key}" aria-label="Yeni model adı">
          <span class="count">${counts.get(group.key) || 0}</span>
        </div>`),
      ...targets.filter((target) => counts.get(target.key)).map((target) => `
        <div class="organize-group is-target">${icon('arrow-right', 'icon-sm')}<span class="organize-group-title">${esc(target.title)}</span><span class="count">${counts.get(target.key)}</span></div>`),
    ];
    groupsBox.innerHTML = `<div class="field-label">Oluşacak modeller ve hedefler${chips.length ? ` <span class="count">${chips.length}</span>` : ''}</div>
      ${chips.length ? `<div class="organize-group-list">${chips.join('')}</div>`
        : '<p class="field-hint">Henüz değişiklik yok. Bir dosyanın hedefini “＋ Yeni model oluştur” ya da “→ Model seç…” yap veya Akıllı öneri’yi kullan.</p>'}`;
  };

  const renderList = () => {
    list.innerHTML = files.map((file) => {
      const copies = otherCopies(file);
      const twin = file.copies.find((copy) => copy.sameModel);
      const value = dest.get(file.path);
      return `
        <li class="organize-row ${value === 'trash' ? 'is-trash' : value === 'keep' ? '' : 'is-moving'}">
          <label class="organize-check"><input type="checkbox" data-check="${esc(file.path)}" ${selected.has(file.path) ? 'checked' : ''} aria-label="${esc(file.name)} seç"></label>
          <span class="file-ext ${isModel(file) ? 'is-model' : ''}">${esc(file.format)}</span>
          <span class="organize-name">
            <span class="file-name" title="${esc(file.path)}">${esc(file.name)}</span>
            <span class="file-size">${esc(file.sizeLabel)}${file.path === info.main ? ' · ana dosya' : ''}
              ${copies.length ? `<span class="badge badge-warning" title="${esc(copies.map((copy) => `${copy.title}: ${copy.path}`).join('\n'))}">${icon('copy', 'icon-xs')}Arşivde var: ${esc(copies[0].title)}${copies.length > 1 ? ` +${copies.length - 1}` : ''}</span>` : ''}
              ${twin ? `<span class="badge" title="${esc(twin.path)}">${icon('copy', 'icon-xs')}Bu modelde aynısı var</span>` : ''}
              ${file.shared ? '<span class="badge">Ortak dosya</span>' : ''}
            </span>
          </span>
          <select class="select select-sm" data-dest="${esc(file.path)}" ${file.shared ? 'disabled' : ''} aria-label="${esc(file.name)} nereye">${optionsHtml(value)}</select>
        </li>`;
    }).join('');
  };

  const renderSummary = () => {
    const values = [...dest.values()];
    const moving = values.filter((value) => value.startsWith('m:')).length;
    const trashed = values.filter((value) => value === 'trash').length;
    const remainingModels = files.filter((file) => isModel(file) && dest.get(file.path) === 'keep').length;
    const changes = values.filter((value) => value !== 'keep').length;
    const parts = [];
    if (groups.length) parts.push(`${groups.length} yeni model`);
    if (moving) parts.push(`${moving} dosya başka modele`);
    if (trashed) parts.push(`${trashed} dosya çöpe`);
    if (changes) parts.push(remainingModels ? `${remainingModels} model dosyası burada kalıyor` : '<strong>bu model kaldırılacak</strong>');
    summary.innerHTML = changes ? parts.join(' · ') : 'Henüz değişiklik yok';
    summary.classList.toggle('is-warning', Boolean(changes) && !remainingModels);
    apply.disabled = !changes;
    bulk.hidden = false;
    $('[data-bulk-count]', dialog).textContent = selected.size ? `${selected.size} dosya seçili →` : 'Seçtiklerini topluca taşı:';
    const bulkSelect = $('[data-bulk-dest]', dialog);
    bulkSelect.disabled = !selected.size;
    bulkSelect.innerHTML = `<option value="" selected disabled>Hedef seç…</option>${optionsHtml('')}`;
    $('[data-check-all]', dialog).checked = selected.size === files.length && files.length > 0;
  };

  const render = () => {
    pruneGroups();
    renderGroups();
    renderList();
    renderSummary();
  };

  const assign = async (paths, value, select) => {
    let key = value;
    if (value === 'new') {
      const first = byPath.get(paths[0]);
      key = newGroup(first.title || fileTitle(first.name));
    } else if (value === 'pick') {
      const card = await pickModel({ models, exclude: model.id, title: paths.length > 1 ? `${paths.length} dosya için hedef model` : `“${byPath.get(paths[0]).name}” için hedef model` });
      if (!card) {
        if (select) select.value = dest.get(paths[0]);
        return;
      }
      key = targetKey(card);
    }
    paths.forEach((path) => dest.set(path, key));
    render();
  };

  dialog.addEventListener('click', (event) => {
    const preset = event.target.closest('[data-preset]');
    if (preset) {
      presets[preset.dataset.preset]();
      render();
    }
  });
  dialog.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('[data-dest]')) assign([target.dataset.dest], target.value, target);
    else if (target.matches('[data-bulk-dest]') && target.value && selected.size) assign([...selected], target.value, null);
    else if (target.matches('[data-check]')) {
      if (target.checked) selected.add(target.dataset.check);
      else selected.delete(target.dataset.check);
      renderSummary();
    } else if (target.matches('[data-check-all]')) {
      files.forEach((file) => (target.checked && !file.shared ? selected.add(file.path) : selected.delete(file.path)));
      renderList();
      renderSummary();
    } else if (target.matches('[data-group-title]')) {
      const group = groups.find((item) => item.key === target.dataset.groupTitle);
      if (group) group.title = target.value.trim() || group.title;
      renderList();
    }
  });

  apply.addEventListener('click', async () => {
    const payload = { groups: [], moves: [], trash: [] };
    for (const group of groups) {
      const paths = files.filter((file) => dest.get(file.path) === group.key).map((file) => file.path);
      if (!paths.some((path) => isModel(byPath.get(path)))) {
        toast(`“${group.title}” içinde 3D model dosyası yok; görselleri bir model dosyasıyla birlikte taşı`, 'error', { duration: 6000 });
        return;
      }
      payload.groups.push({ title: group.title, files: paths });
    }
    for (const target of targets) {
      const paths = files.filter((file) => dest.get(file.path) === target.key).map((file) => file.path);
      if (paths.length) payload.moves.push({ target: target.id, files: paths });
    }
    payload.trash = files.filter((file) => dest.get(file.path) === 'trash').map((file) => file.path);
    apply.disabled = true;
    apply.innerHTML = '<span class="spinner"></span>Uygulanıyor…';
    try {
      const result = await api(`/api/models/${encodeURIComponent(model.id)}/organize`, { method: 'POST', body: payload });
      const parts = [];
      if (result.created.length) parts.push(`${result.created.length} yeni model`);
      if (result.targets.length) parts.push(`${result.targets.length} modele dosya taşındı`);
      if (result.trashed) parts.push(`${result.trashed} dosya çöp kutusunda`);
      toast(parts.join(' · ') || 'Güncellendi', 'success', { duration: 5000 });
      dialog.close();
      onDone?.(result);
    } catch (error) {
      toast(error.message, 'error', { duration: 6000 });
      apply.disabled = false;
      apply.innerHTML = `${icon('check')}Uygula`;
    }
  });

  render();
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
    ['general', 'Genel'], ['privacy', 'Gizlilik'], ['users', 'Kullanıcılar'], ['maintenance', 'Bakım'], ['shares', 'Paylaşımlar'], ['security', 'Şifrem'],
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
      boot.newModelsHidden = settings.new_models_hidden;
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
        ${switchHtml('new_models_hidden', 'Yeni modeller varsayılan olarak gizli', 'Yüklediğin veya klasöre eklenen modeller, sen yayınlayana kadar ziyaretçilere görünmez', settings.new_models_hidden)}
        <div class="section">
          <h3 class="section-title">Toplu görünürlük</h3>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn" data-bulk="hide">${icon('eye-off')}Tüm modelleri gizle</button>
            <button type="button" class="btn" data-bulk="show">${icon('globe')}Tüm modelleri yayınla</button>
          </div>
          <p class="field-hint" style="margin:8px 0 0">Tek tek yayınlamak için modelin detayındaki “Ziyaretçilerden gizle” anahtarını kullan.</p>
        </div>
        <div class="notice is-warning" style="margin-top:14px">${icon('triangle-alert')}<div>Bazı modeller (ör. MakerWorld “Standart Dijital Dosya Lisansı”, NC/ND lisanslar) yeniden dağıtıma izin vermeyebilir. Bu modelleri gizleyebilir veya ziyaretçi indirmelerini kapatabilirsin.</div></div>`;
      panel.querySelectorAll('input[type="checkbox"]').forEach((input) => input.addEventListener('change', () => save({ [input.name]: input.checked })));
      panel.querySelectorAll('[data-bulk]').forEach((button) => button.addEventListener('click', async () => {
        const hide = button.dataset.bulk === 'hide';
        const ok = await confirmDialog({
          title: hide ? 'Tüm modeller gizlensin mi?' : 'Tüm modeller yayınlansın mı?',
          message: hide
            ? 'Ziyaretçiler hiçbir modeli göremez; paylaşım bağlantıları çalışmaya devam eder.'
            : 'Gizli işaretli tüm modeller ziyaretçilere açılır (18+ ayarı ayrıca uygulanır).',
          confirmText: hide ? 'Tümünü gizle' : 'Tümünü yayınla',
          danger: !hide,
          iconName: hide ? 'eye-off' : 'globe',
        });
        if (!ok) return;
        try {
          const result = await api('/api/admin/bulk', { method: 'POST', body: { ids: 'all', changes: { hidden: hide } } });
          toast(`${result.updated} model ${hide ? 'gizlendi' : 'yayınlandı'}`, 'success');
          onChanged?.(settings);
        } catch (error) {
          toast(error.message, 'error');
        }
      }));
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
      renderPasswordForm(panel);
    },
    async users() {
      const { users, roles } = await api('/api/users');
      const me = boot.user?.username;
      const roleOptions = (selected) => roles.map((role) => `<option value="${role.key}" ${role.key === selected ? 'selected' : ''}>${esc(role.label)}</option>`).join('');
      panel.innerHTML = `
        <div class="notice" style="margin-bottom:14px">${icon('info')}<div><strong>Yönetici</strong> her şeyi yapar. <strong>Editör</strong> model yükler, düzenler, görünürlüğü ve paylaşımları yönetir. <strong>Üye</strong> gizliler dahil tüm arşivi görür ve indirir (18+ hariç).</div></div>
        ${users.map((user) => `
          <div class="share-row" data-user="${esc(user.username)}">
            <span class="admin-avatar" style="flex:none">${user.role === 'admin' ? icon('shield-check') : `<span class="avatar-initial">${esc(user.name.charAt(0).toLocaleUpperCase('tr'))}</span>`}</span>
            <div class="share-row-meta">
              <strong style="font-family:var(--font)">${esc(user.name)} <span style="color:var(--text-3);font-weight:500">@${esc(user.username)}</span>${user.username === me ? ' · sen' : ''}</strong>
              ${user.disabled ? '<span class="badge badge-warning">Devre dışı</span> · ' : ''}${user.lastLogin ? `son giriş ${esc(formatRelative(user.lastLogin))}` : 'hiç giriş yapmadı'}
            </div>
            <select class="select" data-role style="width:auto;min-height:32px;height:32px;padding-top:0;padding-bottom:0;font-size:12.5px" aria-label="Rol" ${user.username === me ? 'disabled' : ''}>${roleOptions(user.role)}</select>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" data-reset title="Şifre belirle" aria-label="Şifre belirle">${icon('key-round', 'icon-sm')}</button>
            ${user.username === me ? '' : `
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-toggle-user title="${user.disabled ? 'Etkinleştir' : 'Devre dışı bırak'}" aria-label="${user.disabled ? 'Etkinleştir' : 'Devre dışı bırak'}">${icon(user.disabled ? 'circle-check' : 'circle-x', 'icon-sm')}</button>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-delete-user title="Sil" aria-label="Kullanıcıyı sil">${icon('trash-2', 'icon-sm')}</button>`}
          </div>`).join('')}
        <form class="section" data-new-user novalidate>
          <h3 class="section-title">Yeni kullanıcı</h3>
          <div class="field-row">
            <div class="field"><label class="field-label" for="nu-username">Kullanıcı adı</label><input class="input" id="nu-username" name="username" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="32" placeholder="ornek.kullanici" required></div>
            <div class="field"><label class="field-label" for="nu-name">Görünen ad</label><input class="input" id="nu-name" name="name" maxlength="60" placeholder="Örn. Ayşe"></div>
          </div>
          <div class="field-row" style="margin-top:14px">
            <div class="field"><label class="field-label" for="nu-password">Şifre</label><input class="input" id="nu-password" name="password" type="password" autocomplete="new-password" minlength="8" required></div>
            <div class="field"><label class="field-label" for="nu-role">Rol</label><select class="select" id="nu-role" name="role">${roleOptions('member')}</select></div>
          </div>
          <div class="form-error" data-error></div>
          <button type="submit" class="btn btn-primary">${icon('plus')}Kullanıcı oluştur</button>
        </form>`;
      const refresh = () => views.users();
      const update = async (username, changes, message) => {
        try {
          await api(`/api/users/${encodeURIComponent(username)}`, { method: 'PATCH', body: changes });
          toast(message, 'success');
        } catch (error) {
          toast(error.message, 'error');
        }
        refresh();
      };
      panel.querySelectorAll('[data-user]').forEach((row) => {
        const username = row.dataset.user;
        row.querySelector('[data-role]')?.addEventListener('change', (event) => update(username, { role: event.target.value }, 'Rol güncellendi'));
        row.querySelector('[data-toggle-user]')?.addEventListener('click', () => {
          const user = users.find((item) => item.username === username);
          update(username, { disabled: !user.disabled }, user.disabled ? 'Hesap etkinleştirildi' : 'Hesap devre dışı bırakıldı');
        });
        row.querySelector('[data-reset]')?.addEventListener('click', () => {
          const box = createModal({
            title: 'Şifre belirle',
            description: `@${username} için yeni şifre (hesabın açık oturumları kapanır)`,
            iconName: 'key-round',
            body: '<div class="field"><label class="field-label" for="rp-password">Yeni şifre</label><input class="input" id="rp-password" type="password" autocomplete="new-password" minlength="8"></div><div class="form-error" data-error></div>',
            footer: `<button type="button" class="btn btn-ghost" data-close>Vazgeç</button><button type="button" class="btn btn-primary" data-save>${icon('check')}Kaydet</button>`,
          });
          box.querySelector('[data-save]').addEventListener('click', async () => {
            const value = box.querySelector('#rp-password').value;
            if (value.length < 8) { box.querySelector('[data-error]').textContent = 'Şifre en az 8 karakter olmalı.'; return; }
            box.close();
            update(username, { password: value }, 'Şifre güncellendi');
          });
        });
        row.querySelector('[data-delete-user]')?.addEventListener('click', async () => {
          const ok = await confirmDialog({ title: 'Kullanıcı silinsin mi?', message: `@${username} hesabı kalıcı olarak silinecek.`, confirmText: 'Sil', danger: true, iconName: 'trash-2' });
          if (!ok) return;
          try {
            await api(`/api/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
            toast('Kullanıcı silindi', 'success');
          } catch (error) {
            toast(error.message, 'error');
          }
          refresh();
        });
      });
      panel.querySelector('[data-new-user]').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = Object.fromEntries(new FormData(form));
        const error = form.querySelector('[data-error]');
        if ((data.password || '').length < 8) { error.textContent = 'Şifre en az 8 karakter olmalı.'; return; }
        try {
          await api('/api/users', { method: 'POST', body: { ...data, username: data.username.trim().toLowerCase() } });
          toast('Kullanıcı oluşturuldu', 'success');
          refresh();
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

// ─── Hesap ──────────────────────────────────────────────────────────

function renderPasswordForm(panel) {
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
      <p class="field-hint" style="margin:10px 0 0">En az 8 karakter. Şifre değişince diğer cihazlardaki oturumların kapanır.</p>
      <div class="form-error" data-error></div>
      <button type="submit" class="btn btn-primary">${icon('lock')}Şifreyi değiştir</button>
    </form>`;
  panel.querySelector('[data-password]').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = panel.querySelector('[data-error]');
    const next = panel.querySelector('#pw-new').value;
    if (next.length < 8) { error.textContent = 'Yeni şifre en az 8 karakter olmalı.'; return; }
    if (next !== panel.querySelector('#pw-repeat').value) { error.textContent = 'Yeni şifreler eşleşmiyor.'; return; }
    try {
      await api('/api/auth/password', { method: 'POST', body: { current: panel.querySelector('#pw-current').value, new: next } });
      error.textContent = '';
      event.target.reset();
      toast('Şifre değiştirildi', 'success');
    } catch (err) {
      error.textContent = err.message;
    }
  });
}

export function openAccount() {
  const user = boot.user || {};
  const dialog = createModal({
    title: 'Şifremi değiştir',
    description: `${user.name || ''} · @${user.username || ''} · ${user.roleLabel || ''}`,
    iconName: 'lock',
    body: '<div data-panel></div>',
  });
  renderPasswordForm(dialog.querySelector('[data-panel]'));
  return dialog;
}
