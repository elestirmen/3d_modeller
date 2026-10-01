/**
 * Paylaşım sayfası: tek bir modeli token ile görüntüler.
 */

import { $, absoluteUrl, boot, copyText, createModal, esc, icon, qrSvg, shareTargets, toast, toggleTheme } from './core.js';
import { DetailView } from './detail.js';

const share = boot.share;
const root = $('#shareRoot');

function updateThemeIcon() {
  const button = $('#themeToggle');
  const dark = document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  button.innerHTML = icon(dark ? 'sun' : 'moon');
}

function openShareBox() {
  const url = absoluteUrl(window.location.pathname);
  const title = share.model.title;
  const dialog = createModal({
    title: 'Bağlantıyı paylaş',
    description: title,
    iconName: 'share-2',
    body: `
      <div class="share-box">
        <div style="min-width:0;width:100%">
          <div class="share-link">
            <input class="input" value="${esc(url)}" readonly aria-label="Bağlantı">
            <button type="button" class="btn btn-primary" data-copy>${icon('copy')}Kopyala</button>
          </div>
          <div class="share-targets">
            ${navigator.share ? `<button type="button" class="btn btn-sm" data-native>${icon('share-2', 'icon-sm')}Paylaş…</button>` : ''}
            ${shareTargets(url, title).map((item) => `<a class="btn btn-sm" href="${esc(item.href)}" target="_blank" rel="noopener">${icon(item.icon, 'icon-sm')}${esc(item.label)}</a>`).join('')}
          </div>
        </div>
        <div class="qr">${qrSvg(url)}</div>
      </div>`,
  });
  dialog.querySelector('[data-copy]').addEventListener('click', async () => {
    if (await copyText(url)) toast('Bağlantı kopyalandı', 'success');
  });
  dialog.querySelector('[data-native]')?.addEventListener('click', () => navigator.share({ title, url }).catch(() => {}));
}

function start() {
  const view = new DetailView({
    root,
    mode: 'share',
    role: null,
    onShare: openShareBox,
  });
  view.render(share.model);
  document.addEventListener('keydown', (event) => {
    if (event.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return;
    if (event.shiftKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
      event.preventDefault();
      view.stepPart(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
}

$('#themeToggle')?.addEventListener('click', () => {
  toggleTheme();
  updateThemeIcon();
});
updateThemeIcon();
if (share && root) {
  if (window.THREE) start();
  else window.addEventListener('load', start, { once: true });
}
