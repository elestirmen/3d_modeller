/**
 * 3D Model Yöneticisi — Frontend JavaScript
 * Three.js ile 3D STL önizleme + thumbnail üretimi
 */

// ─── State ─────────────────────────────────────────────────
const state = {
    models: [],
    currentFilter: 'all',
    currentTag: '',
    currentFormat: '',
    currentSort: 'name',
    currentGroupMode: localStorage.getItem('groupMode') === 'project' ? 'project' : 'folder',
    currentMakerFilters: {
        has_readme: false,
        has_license: false,
        has_cad: false,
        has_gcode: false,
        multipart: false,
    },
    searchQuery: '',
    viewMode: 'grid',
    selectedModel: null,
    selectedFilePath: '',
    // Three.js (modal viewer)
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    currentObject: null,
    animationId: null,
    // Thumbnails
    thumbCache: {},        // modelId -> dataURL
    thumbQueue: [],        // bekleme kuyruğu
    thumbBusy: false,
    thumbScheduled: false,
};

const IMAGE_FILE_FORMATS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif']);
const TEXT_FILE_FORMATS = new Set(['txt', 'md']);

// ─── DOM Refs ──────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    searchInput: $('#searchInput'),
    modelGrid: $('#modelGrid'),
    loadingOverlay: $('#loadingOverlay'),
    resultCount: $('#resultCount'),
    sortSelect: $('#sortSelect'),
    groupSelect: $('#groupSelect'),
    sidebar: $('#sidebar'),
    sidebarClose: $('#sidebarClose'),
    sidebarBackdrop: $('#sidebarBackdrop'),
    tagList: $('#tagList'),
    formatChips: $('#formatChips'),
    makerChips: $('#makerChips'),
    previewModal: $('#previewModal'),
    modalTitle: $('#modalTitle'),
    modalPrinted: $('#modalPrinted'),
    modalFavorite: $('#modalFavorite'),
    modalClose: $('#modalClose'),
    viewerContainer: $('#viewerContainer'),
    viewer3D: $('#viewer3D'),
    viewerLoading: $('#viewerLoading'),
    viewerControls: $('#viewerControls'),
    detailFormat: $('#detailFormat'),
    detailFormats: $('#detailFormats'),
    detailSize: $('#detailSize'),
    detailFileCount: $('#detailFileCount'),
    detailType: $('#detailType'),
    detailPrinted: $('#detailPrinted'),
    detailAssets: $('#detailAssets'),
    currentTags: $('#currentTags'),
    tagInput: $('#tagInput'),
    tagSuggestions: $('#tagSuggestions'),
    addTagBtn: $('#addTagBtn'),
    suggestedTags: $('#suggestedTags'),
    noteInput: $('#noteInput'),
    saveNoteBtn: $('#saveNoteBtn'),
    fileList: $('#fileList'),
    makerInfoSection: $('#makerInfoSection'),
    makerBadges: $('#makerBadges'),
    printProfile: $('#printProfile'),
    readmeExcerpt: $('#readmeExcerpt'),
    resourceLinks: $('#resourceLinks'),
    previewGallerySection: $('#previewGallerySection'),
    previewGallery: $('#previewGallery'),
    toastContainer: $('#toastContainer'),
    btnFilters: $('#btnFilters'),
    btnRescan: $('#btnRescan'),
    btnRescanLabel: $('#btnRescanLabel'),
    btnFullRescan: $('#btnFullRescan'),
    btnFullRescanLabel: $('#btnFullRescanLabel'),
    viewGrid: $('#viewGrid'),
    viewList: $('#viewList'),
    statTotal: $('#statTotal'),
    statFavorites: $('#statFavorites'),
    statSize: $('#statSize'),
    filterAll: $('#filterAll'),
    filterFav: $('#filterFav'),
};

// ─── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Thumbnail cache'i temizle (yeni render kalitesi)
    try {
        const ver = localStorage.getItem('thumbVersion');
        if (ver !== 'v7') {
            localStorage.removeItem('thumbCache');
            localStorage.setItem('thumbVersion', 'v7');
        } else {
            const saved = localStorage.getItem('thumbCache');
            if (saved) state.thumbCache = JSON.parse(saved);
        }
    } catch (e) { /* pass */ }

    if (dom.groupSelect) {
        dom.groupSelect.value = state.currentGroupMode;
    }

    loadModels();
    loadStats();
    loadTags();
    bindEvents();
});

// ─── API Helpers ───────────────────────────────────────────
async function api(url, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const resp = await fetch(url, {
        headers,
        ...options,
    });
    const contentType = resp.headers.get('content-type') || '';
    const payload = contentType.includes('application/json')
        ? await resp.json()
        : await resp.text();

    if (!resp.ok) {
        const message = typeof payload === 'object' && payload
            ? payload.error || payload.message || `HTTP ${resp.status}`
            : `HTTP ${resp.status}`;
        throw new Error(message);
    }

    return payload;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));
}

function isMobileViewport() {
    return window.innerWidth <= 768;
}

function setSidebarOpen(isOpen) {
    dom.sidebar.classList.toggle('mobile-open', isOpen);
    dom.sidebarBackdrop.classList.toggle('visible', isOpen);
}

function renderResultCount(total) {
    dom.resultCount.replaceChildren();
    const strong = document.createElement('strong');
    strong.textContent = total;
    dom.resultCount.append(strong, ' model bulundu');
}

function getFileName(filePath) {
    return String(filePath).split('\\').pop().split('/').pop();
}

function getFileFormat(filePath) {
    const fileName = getFileName(filePath);
    const lastDot = fileName.lastIndexOf('.');
    if (lastDot === -1) return '';
    return fileName.slice(lastDot + 1).toLowerCase();
}

function buildFileUrl(filePath, options = {}) {
    const params = new URLSearchParams();
    if (options.download) params.set('download', '1');
    const suffix = params.toString() ? `?${params}` : '';
    return `/api/file/${encodeURIComponent(filePath)}${suffix}`;
}

function buildPreviewUrl(filePath) {
    return `/api/preview/${encodeURIComponent(filePath)}`;
}

function getAllDisplayFiles(model) {
    return model?.all_files || model?.files || [];
}

function formatAvailableFormats(formats = []) {
    const normalized = formats.filter(Boolean).map((format) => String(format).toUpperCase());
    return normalized.length ? normalized.join(', ') : '—';
}

function getMakerFlagLabel(flag) {
    const labels = {
        has_readme: 'README',
        has_license: 'Lisans',
        has_cad: 'CAD',
        has_gcode: 'G-code',
        multipart: 'Çok Parça',
    };
    return labels[flag] || flag;
}

function getMakerBadges(model) {
    const badges = [];
    if (model?.has_readme) badges.push('README');
    if (model?.has_license) badges.push('Lisans');
    if (model?.has_cad) badges.push('CAD');
    if (model?.has_gcode) badges.push('G-code');
    if (model?.preview_available) badges.push('Önizleme');
    return badges;
}

function getPrintProfileLabel(key) {
    const labels = {
        resolution: 'Katman',
        supports: 'Destek',
        infill: 'Doluluk',
        material: 'Malzeme',
        nozzle: 'Nozul',
    };
    return labels[key] || key;
}

function getCardThumbnailState(model) {
    if (state.thumbCache[model.id]) {
        return { kind: 'cached', source: state.thumbCache[model.id] };
    }
    if (model.preview_images?.length) {
        return { kind: 'image', source: buildFileUrl(model.preview_images[0]) };
    }
    if (model.main_file_has_embedded_preview && model.main_file) {
        return { kind: 'image', source: buildPreviewUrl(model.main_file) };
    }

    const thumbFormat = String(model.main_file_format || model.format || '').toLowerCase();
    if (thumbFormat === 'stl') {
        return { kind: 'generated', format: thumbFormat };
    }
    return { kind: 'icon', format: thumbFormat };
}

function renderFileList(files = []) {
    const modelFiles = new Set(state.selectedModel?.files || []);
    const items = files.map((filePath) => {
        const isActive = filePath === state.selectedFilePath;
        const fileFormat = getFileFormat(filePath).toUpperCase() || 'DOSYA';
        const fileName = getFileName(filePath);
        const fileRole = modelFiles.has(filePath) ? 'MODEL' : 'EK';
        return `
            <li class="file-item ${isActive ? 'active' : ''}">
                <button
                    type="button"
                    class="file-select"
                    data-action="select-file"
                    data-file-path="${escapeHtml(filePath)}"
                    title="${escapeHtml(filePath)}"
                >
                    <span class="file-name">${escapeHtml(fileName)}</span>
                    <span class="file-format"><span class="file-role">${fileRole}</span>${escapeHtml(fileFormat)}</span>
                </button>
                <a
                    class="file-download"
                    href="${buildFileUrl(filePath, { download: true })}"
                    data-action="download-file"
                    data-file-path="${escapeHtml(filePath)}"
                >
                    İndir
                </a>
            </li>
        `;
    }).join('');

    dom.fileList.innerHTML = items;
}

function renderPrintedState(model) {
    const printed = Boolean(model?.printed);
    dom.modalPrinted.classList.toggle('active', printed);
    dom.detailPrinted.textContent = printed ? 'Yazdırıldı' : 'Bekliyor';
}

function setViewerControlsVisible(visible) {
    dom.viewerControls.hidden = !visible;
}

function withGroupMode(path) {
    const separator = path.includes('?') ? '&' : '?';
    return `${path}${separator}group=${encodeURIComponent(state.currentGroupMode)}`;
}

function setScanButtonsBusy(isBusy, activeMode = 'incremental') {
    const buttons = [
        [dom.btnRescan, dom.btnRescanLabel, 'Yenile', 'incremental'],
        [dom.btnFullRescan, dom.btnFullRescanLabel, 'Tam Tara', 'full'],
    ];

    buttons.forEach(([button, label, idleText, buttonMode]) => {
        if (!button) return;
        button.disabled = isBusy;
        button.classList.toggle('spinning', isBusy && activeMode === buttonMode);
        if (isBusy) {
            button.setAttribute('aria-busy', activeMode === buttonMode ? 'true' : 'false');
        } else {
            button.removeAttribute('aria-busy');
        }
        if (label) {
            label.textContent = isBusy && activeMode === buttonMode ? 'Taranıyor...' : idleText;
        }
    });
}

async function runScan(scanMode = 'incremental') {
    const normalizedMode = scanMode === 'full' ? 'full' : 'incremental';
    const activeButton = normalizedMode === 'full' ? dom.btnFullRescan : dom.btnRescan;
    if (!activeButton || activeButton.disabled) return;

    setScanButtonsBusy(true, normalizedMode);
    try {
        const result = await api(withGroupMode(`/api/scan?mode=${normalizedMode}`), { method: 'POST' });

        if (result.mode === 'full') {
            state.thumbCache = {};
            localStorage.removeItem('thumbCache');
        } else {
            for (const modelId of result.updated_ids || []) {
                delete state.thumbCache[modelId];
            }
            saveThumbCache();
        }

        await Promise.all([
            loadModels(),
            loadStats(),
            loadTags(),
        ]);

        if (result.mode === 'full') {
            toast(`Tam tarama tamamlandı. ${result.total} model var.`, 'success');
            return;
        }

        if (result.updated > 0) {
            toast(`Yeni/değişen kayıtlar işlendi. ${result.updated} model güncellendi.`, 'success');
            return;
        }

        toast('Yeni model bulunmadı.', 'info');
    } catch (e) {
        toast('Tarama sırasında hata oluştu', 'error');
    } finally {
        setScanButtonsBusy(false);
    }
}

function getModelTypeLabel(type) {
    if (type === 'folder') return '📂 Klasör';
    if (type === 'project') return '📁 Proje';
    return '📄 Dosya';
}

function getModelDetailType(type) {
    if (type === 'folder') return 'Klasör Grubu';
    if (type === 'project') return 'Proje (Klasör)';
    return 'Tekil Dosya';
}

function renderViewerMessage(icon, message) {
    setViewerControlsVisible(false);
    dom.viewerLoading.classList.add('visible');
    dom.viewerLoading.innerHTML = `
        <div style="text-align: center;">
            <div style="font-size: 4rem; margin-bottom: 16px;">${icon}</div>
            <p style="color: var(--text-secondary); font-size: 0.9rem;">
                ${message}
            </p>
        </div>
    `;
}

function showSelectedFile(filePath) {
    if (!state.selectedModel || !filePath) return;

    state.selectedFilePath = filePath;
    renderFileList(getAllDisplayFiles(state.selectedModel));

    const fileFormat = getFileFormat(filePath) || state.selectedModel.format;
    dom.detailFormat.textContent = fileFormat.toUpperCase();

    if (fileFormat === 'stl' || fileFormat === '3mf') {
        showViewerLoading(`${fileFormat.toUpperCase()} model yükleniyor...`);
        setViewerControlsVisible(true);
        if (!state.renderer) initViewer();
        if (fileFormat === 'stl') {
            loadSTL(buildFileUrl(filePath), filePath);
        } else {
            load3MF(buildFileUrl(filePath), filePath);
        }
        return;
    }

    if (IMAGE_FILE_FORMATS.has(fileFormat)) {
        renderViewerImagePreview(
            buildFileUrl(filePath),
            `${getFileName(filePath)} görseli gösteriliyor.`,
            'Görsel yüklenemedi.',
        );
        return;
    }

    disposeViewer();
    renderViewerMessage(
        getFormatIcon(fileFormat),
        `${fileFormat.toUpperCase()} dosyası seçildi. Etkileşimli 3D önizleme şu an yalnızca STL ve 3MF için mevcut.`,
    );
}

// ─── Load Data ─────────────────────────────────────────────
async function loadModels() {
    showLoading(true);
    try {
        const params = new URLSearchParams();
        if (state.searchQuery) params.set('q', state.searchQuery);
        if (state.currentTag) params.set('tag', state.currentTag);
        if (state.currentFormat) params.set('format', state.currentFormat);
        if (state.currentSort) params.set('sort', state.currentSort);
        if (state.currentFilter === 'fav') params.set('fav', '1');
        Object.entries(state.currentMakerFilters).forEach(([flag, enabled]) => {
            if (enabled) params.set(flag, '1');
        });
        params.set('group', state.currentGroupMode);

        const data = await api(`/api/models?${params}`);
        state.models = data.models;
        renderGrid();
        renderResultCount(data.total);
    } catch (err) {
        console.error('Model yüklenemedi:', err);
        toast('Modeller yüklenirken hata oluştu', 'error');
    } finally {
        showLoading(false);
    }
}

async function loadStats() {
    try {
        const data = await api(withGroupMode('/api/stats'));
        dom.statTotal.querySelector('.stat-value').textContent = data.total;
        dom.statFavorites.querySelector('.stat-value').textContent = data.favorites;
        dom.statSize.querySelector('.stat-value').textContent = data.total_size;
    } catch (e) { /* pass */ }
}

async function loadTags() {
    try {
        const data = await api(withGroupMode('/api/tags'));
        renderTags(data.tags);
    } catch (e) { /* pass */ }
}

// ─── Render ────────────────────────────────────────────────
function renderGrid() {
    if (state.models.length === 0) {
        dom.modelGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📂</div>
                <h3>Model bulunamadı</h3>
                <p>Arama kriterlerini değiştirmeyi deneyin</p>
            </div>
        `;
        return;
    }

    dom.modelGrid.innerHTML = state.models.map((m) => {
        const tags = (m.tags || []).slice(0, 3);
        const isFav = m.favorite ? 'active' : '';
        const isPrinted = m.printed ? '<span class="printed-badge">✅ Yazdırıldı</span>' : '';
        const fileCount = m.file_count > 1 ? `<span class="file-count-badge">${m.file_count} dosya</span>` : '';
        const displayName = escapeHtml(m.display_name || m.name);
        const rawName = escapeHtml(m.name || '');
        const metaType = getModelTypeLabel(m.type);

        // Thumbnail durumunu kontrol et
        const cached = state.thumbCache[m.id];
        let thumbContent;
        if (cached) {
            thumbContent = `<img src="${cached}" alt="${displayName}" style="width:100%;height:100%;object-fit:contain;">`;
        } else if (m.format === 'stl') {
            thumbContent = `<div class="thumb-loading" data-model-id="${m.id}"><div class="mini-spinner"></div><span>Yükleniyor</span></div>`;
        } else {
            thumbContent = `<span class="thumb-icon">${getFormatIcon(m.format)}</span>`;
        }

        return `
            <div class="model-card" data-id="${m.id}">
                <div class="card-thumbnail" data-thumb-id="${m.id}" data-format="${escapeHtml(m.format)}">
                    <span class="format-badge">${escapeHtml(m.format)}</span>
                    ${fileCount}
                    ${thumbContent}
                    ${isPrinted}
                    <div class="card-favorite ${isFav}" data-action="favorite" role="button" tabindex="0" aria-label="Favori">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                        </svg>
                    </div>
                </div>
                <div class="card-body">
                    <div class="card-name" title="${rawName}">${displayName}</div>
                    <div class="card-meta">
                        <span>${escapeHtml(m.size_display)}</span>
                        <span>${metaType}</span>
                    </div>
                    <div class="card-tags">
                        ${tags.map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join('')}
                        ${m.tags && m.tags.length > 3 ? `<span class="card-tag">+${m.tags.length - 3}</span>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Thumbnail üretimini başlat (IntersectionObserver ile lazy)
    setupThumbnailObserver();
}

function renderTags(tags) {
    dom.tagList.innerHTML = tags.map(t => `
        <div class="tag-item ${state.currentTag === t.name ? 'active' : ''}" data-tag="${escapeHtml(t.name)}">
            <span class="tag-name">${escapeHtml(t.name)}</span>
            <span class="tag-count">${t.count}</span>
        </div>
    `).join('');
}

function getFormatIcon(format) {
    const icons = {
        stl: '🔷',
        '3mf': '📦',
        obj: '🟢',
        gltf: '🟡',
        glb: '🟡',
        fbx: '🟠',
        ply: '🟣',
    };
    return icons[format] || '📄';
}

// ─── Thumbnail Generation ──────────────────────────────────

// Offscreen thumbnail renderer
const thumbRenderer = {
    renderer: null,
    scene: null,
    camera: null,
    loader: null,

    init() {
        if (this.renderer) return;

        const W = 480, H = 360;
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(W, H);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x000000, 0);  // Saydam — CSS gradient arka plan görünecek
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.5;
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

        this.scene = new THREE.Scene();
        // Arka plan yok — saydam render

        // Camera
        this.camera = new THREE.PerspectiveCamera(35, W / H, 0.1, 2000);

        // Aydınlatma — stüdyo tarzı, belirgin gölge/kenar
        const ambient = new THREE.AmbientLight(0xc0c8e0, 0.6);
        this.scene.add(ambient);

        const keyLight = new THREE.DirectionalLight(0xffffff, 2.5);
        keyLight.position.set(60, 120, 80);
        keyLight.castShadow = true;
        this.scene.add(keyLight);

        const fillLight = new THREE.DirectionalLight(0x8899ff, 0.8);
        fillLight.position.set(-60, 50, -30);
        this.scene.add(fillLight);

        const rimLight = new THREE.DirectionalLight(0xbb77ff, 0.7);
        rimLight.position.set(-20, -30, -70);
        this.scene.add(rimLight);

        const topLight = new THREE.DirectionalLight(0xffffff, 0.5);
        topLight.position.set(0, 150, 0);
        this.scene.add(topLight);

        const hemi = new THREE.HemisphereLight(0xddddef, 0x8888aa, 0.5);
        this.scene.add(hemi);

        this.loader = new THREE.STLLoader();
    },

    async renderThumbnail(url) {
        return new Promise((resolve, reject) => {
            this.init();

            this.loader.load(
                url,
                (geometry) => {
                    // Clear previous meshes AND edge lines
                    const toRemove = this.scene.children.filter(c => c.isMesh || c.isLineSegments);
                    toRemove.forEach(m => {
                        this.scene.remove(m);
                        m.geometry.dispose();
                        if (m.material) m.material.dispose();
                    });

                    geometry.computeVertexNormals();

                    const material = new THREE.MeshPhysicalMaterial({
                        color: 0x4a50c8,
                        metalness: 0.15,
                        roughness: 0.3,
                        clearcoat: 0.6,
                        clearcoatRoughness: 0.15,
                        reflectivity: 0.6,
                    });

                    const mesh = new THREE.Mesh(geometry, material);

                    // Center and scale
                    geometry.computeBoundingBox();
                    const box = geometry.boundingBox;
                    const center = new THREE.Vector3();
                    box.getCenter(center);
                    geometry.translate(-center.x, -center.y, -center.z);

                    const size = new THREE.Vector3();
                    box.getSize(size);
                    const maxDim = Math.max(size.x, size.y, size.z);
                    const scale = 70 / maxDim;
                    mesh.scale.set(scale, scale, scale);

                    // Position on ground
                    geometry.computeBoundingBox();
                    mesh.position.y = -geometry.boundingBox.min.y * scale;

                    this.scene.add(mesh);

                    // Edge wireframe overlay — kenarları belirginleştirir
                    const edgesGeo = new THREE.EdgesGeometry(geometry, 30);
                    const edgeMat = new THREE.LineBasicMaterial({
                        color: 0x2a2e80,
                        transparent: true,
                        opacity: 0.25,
                        linewidth: 1,
                    });
                    const edges = new THREE.LineSegments(edgesGeo, edgeMat);
                    edges.scale.copy(mesh.scale);
                    edges.position.copy(mesh.position);
                    this.scene.add(edges);

                    // Camera — closer angle for better visibility
                    const dist = maxDim * scale * 1.7;
                    this.camera.position.set(dist * 0.6, dist * 0.45, dist * 0.75);
                    this.camera.lookAt(0, (size.y * scale) / 5, 0);

                    // Render
                    this.renderer.render(this.scene, this.camera);
                    const dataURL = this.renderer.domElement.toDataURL('image/webp', 0.85);

                    // Clean up mesh + edges
                    this.scene.remove(mesh);
                    this.scene.remove(edges);
                    geometry.dispose();
                    material.dispose();
                    edgesGeo.dispose();
                    edgeMat.dispose();

                    resolve(dataURL);
                },
                undefined,
                (error) => {
                    reject(error);
                }
            );
        });
    }
};

function setupThumbnailObserver() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const el = entry.target;
                const modelId = el.dataset.thumbId;
                const format = el.dataset.format;

                if (format === 'stl' && !state.thumbCache[modelId]) {
                    queueThumbnail(modelId);
                }
                observer.unobserve(el);
            }
        });
    }, {
        rootMargin: '200px',
        threshold: 0
    });

    document.querySelectorAll('.card-thumbnail[data-format="stl"]').forEach(el => {
        if (!state.thumbCache[el.dataset.thumbId]) {
            observer.observe(el);
        }
    });
}

function queueThumbnail(modelId) {
    if (state.thumbQueue.includes(modelId)) return;
    state.thumbQueue.push(modelId);
    scheduleThumbQueue();
}

function scheduleThumbQueue() {
    if (state.thumbScheduled) return;
    state.thumbScheduled = true;

    const run = () => {
        state.thumbScheduled = false;
        processThumbQueue();
    };

    if ('requestIdleCallback' in window) {
        window.requestIdleCallback(run, { timeout: 150 });
        return;
    }

    setTimeout(run, 32);
}

function waitForIdle(timeout = 100) {
    return new Promise((resolve) => {
        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(() => resolve(), { timeout });
            return;
        }

        setTimeout(resolve, Math.min(timeout, 32));
    });
}

async function processThumbQueue() {
    if (state.thumbBusy || state.thumbQueue.length === 0) return;
    state.thumbBusy = true;

    while (state.thumbQueue.length > 0) {
        const modelId = state.thumbQueue.shift();
        if (state.thumbCache[modelId]) continue;

        const model = state.models.find(m => m.id === modelId);
        if (!model) continue;

        const filePath = model.main_file || model.path;
        const url = `/api/file/${encodeURIComponent(filePath)}`;

        try {
            const dataURL = await thumbRenderer.renderThumbnail(url);
            state.thumbCache[modelId] = dataURL;

            // DOM'daki thumbnail'ı güncelle
            const thumbEl = document.querySelector(`.card-thumbnail[data-thumb-id="${modelId}"]`);
            if (thumbEl) {
                const loading = thumbEl.querySelector('.thumb-loading');
                if (loading) {
                    const img = document.createElement('img');
                    img.src = dataURL;
                    img.alt = model.display_name || model.name;
                    img.style.cssText = 'width:100%;height:100%;object-fit:contain;';
                    img.style.animation = 'fadeIn 0.3s ease';
                    loading.replaceWith(img);
                }
            }

            // Her 10 thumbnail'da bir localStorage'a kaydet
            if (Object.keys(state.thumbCache).length % 10 === 0) {
                saveThumbCache();
            }
        } catch (e) {
            console.warn(`Thumbnail üretilemedi: ${modelId}`, e);
            // Hata durumunda fallback icon göster
            const thumbEl = document.querySelector(`.card-thumbnail[data-thumb-id="${modelId}"]`);
            if (thumbEl) {
                const loading = thumbEl.querySelector('.thumb-loading');
                if (loading) {
                    loading.innerHTML = '<span class="thumb-icon">🔷</span>';
                }
            }
        }

        // Bir sonraki thumbnail için kısa bekleme (UI'ı bloklamayalım)
        await waitForIdle(120);
    }

    state.thumbBusy = false;
    saveThumbCache();
}

function saveThumbCache() {
    try {
        // localStorage sınırını aşmamak için en fazla 200 thumbnail sakla
        const keys = Object.keys(state.thumbCache);
        if (keys.length > 200) {
            const toRemove = keys.slice(0, keys.length - 200);
            toRemove.forEach(k => delete state.thumbCache[k]);
        }
        localStorage.setItem('thumbCache', JSON.stringify(state.thumbCache));
    } catch (e) {
        // localStorage dolmuş olabilir, cache'i temizle
        console.warn('Thumbnail cache kaydedilemedi, temizleniyor...');
        localStorage.removeItem('thumbCache');
    }
}

// ─── Events ────────────────────────────────────────────────
function bindEvents() {
    // Arama
    let debounceTimer;
    dom.searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            state.searchQuery = dom.searchInput.value;
            loadModels();
        }, 300);
    });

    // Ctrl+K ile arama
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            dom.searchInput.focus();
        }
        if (e.key === 'Escape' && dom.previewModal.classList.contains('visible')) {
            closePreview();
            return;
        }
        if (e.key === 'Escape' && dom.sidebar.classList.contains('mobile-open')) {
            setSidebarOpen(false);
        }
    });

    // Sıralama
    dom.sortSelect.addEventListener('change', () => {
        state.currentSort = dom.sortSelect.value;
        loadModels();
        if (isMobileViewport()) setSidebarOpen(false);
    });

    dom.groupSelect?.addEventListener('change', async () => {
        state.currentGroupMode = dom.groupSelect.value === 'folder' ? 'folder' : 'project';
        localStorage.setItem('groupMode', state.currentGroupMode);
        closePreview();
        await loadModels();
        loadStats();
        loadTags();
        if (isMobileViewport()) setSidebarOpen(false);
    });

    // Format filtreleri
    dom.formatChips.addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        dom.formatChips.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.currentFormat = chip.dataset.format || '';
        loadModels();
        if (isMobileViewport()) setSidebarOpen(false);
    });

    // Tümü / Favoriler filtresi
    dom.filterAll.addEventListener('click', () => {
        state.currentFilter = 'all';
        dom.filterAll.classList.add('active');
        dom.filterFav.classList.remove('active');
        loadModels();
        if (isMobileViewport()) setSidebarOpen(false);
    });
    dom.filterFav.addEventListener('click', () => {
        state.currentFilter = 'fav';
        dom.filterFav.classList.add('active');
        dom.filterAll.classList.remove('active');
        loadModels();
        if (isMobileViewport()) setSidebarOpen(false);
    });

    dom.tagList.addEventListener('click', (e) => {
        const item = e.target.closest('.tag-item');
        if (!item) return;
        filterByTag(item.dataset.tag || '');
        if (isMobileViewport()) setSidebarOpen(false);
    });

    dom.modelGrid.addEventListener('click', (e) => {
        const favoriteButton = e.target.closest('[data-action="favorite"]');
        if (favoriteButton) {
            const card = favoriteButton.closest('.model-card');
            if (card) toggleFavorite(card.dataset.id);
            return;
        }

        const card = e.target.closest('.model-card');
        if (card) openPreview(card.dataset.id);
    });

    dom.fileList.addEventListener('click', (e) => {
        const selectButton = e.target.closest('[data-action="select-file"]');
        if (selectButton) {
            showSelectedFile(selectButton.dataset.filePath || '');
        }
    });

    dom.currentTags.addEventListener('click', (e) => {
        const removeButton = e.target.closest('.remove-tag');
        if (removeButton) {
            removeTag(removeButton.dataset.tag || '');
        }
    });

    dom.suggestedTags.addEventListener('click', (e) => {
        const suggestButton = e.target.closest('.suggest-tag');
        if (suggestButton) {
            addSuggestedTag(suggestButton.dataset.tag || '');
        }
    });

    // Görünüm
    dom.viewGrid.addEventListener('click', () => {
        state.viewMode = 'grid';
        dom.viewGrid.classList.add('active');
        dom.viewList.classList.remove('active');
        dom.modelGrid.classList.remove('list-view');
    });
    dom.viewList.addEventListener('click', () => {
        state.viewMode = 'list';
        dom.viewList.classList.add('active');
        dom.viewGrid.classList.remove('active');
        dom.modelGrid.classList.add('list-view');
    });

    // Yeniden tara
    dom.btnRescan.addEventListener('click', () => {
        runScan('incremental');
    });

    dom.btnFullRescan?.addEventListener('click', () => {
        runScan('full');
    });

    // Modal kapat
    dom.modalClose.addEventListener('click', closePreview);
    dom.previewModal.addEventListener('click', (e) => {
        if (e.target === dom.previewModal) closePreview();
    });

    dom.btnFilters?.addEventListener('click', () => setSidebarOpen(true));
    dom.sidebarClose?.addEventListener('click', () => setSidebarOpen(false));
    dom.sidebarBackdrop?.addEventListener('click', () => setSidebarOpen(false));
    window.addEventListener('resize', () => {
        if (!isMobileViewport()) setSidebarOpen(false);
    });

    // Modal yazdırıldı
    dom.modalPrinted.addEventListener('click', () => {
        if (state.selectedModel) togglePrinted(state.selectedModel.id);
    });

    // Modal favori
    dom.modalFavorite.addEventListener('click', () => {
        if (state.selectedModel) toggleFavorite(state.selectedModel.id);
    });

    // Etiket ekle
    dom.addTagBtn.addEventListener('click', addTag);
    dom.tagInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') addTag();
    });

    // Not kaydet
    dom.saveNoteBtn.addEventListener('click', saveNote);
}

// ─── Actions ───────────────────────────────────────────────
function updateModelState(modelId, changes) {
    const model = state.models.find((item) => item.id === modelId);
    if (model) Object.assign(model, changes);
    if (state.selectedModel?.id === modelId) {
        Object.assign(state.selectedModel, changes);
    }
}

function filterByTag(tagName) {
    if (state.currentTag === tagName) {
        state.currentTag = '';
    } else {
        state.currentTag = tagName;
    }
    loadModels();
    loadTags();
}

async function toggleFavorite(modelId) {
    try {
        const data = await api(`/api/models/${modelId}/favorite`, { method: 'POST' });
        updateModelState(modelId, { favorite: data.favorite });
        dom.modalFavorite.classList.toggle('active', Boolean(state.selectedModel?.favorite));
        await loadModels();

        loadStats();
        toast(data.favorite ? '⭐ Favorilere eklendi' : 'Favorilerden çıkarıldı', 'info');
    } catch (e) {
        toast('Favori güncellenemedi', 'error');
    }
}

async function togglePrinted(modelId) {
    try {
        const data = await api(`/api/models/${modelId}/printed`, { method: 'POST' });
        updateModelState(modelId, { printed: data.printed });
        renderPrintedState(state.selectedModel || state.models.find((item) => item.id === modelId));
        renderGrid();
        loadStats();
        toast(data.printed ? 'Yazdırıldı olarak işaretlendi' : 'Yazdırıldı işareti kaldırıldı', 'info');
    } catch (e) {
        toast('Yazdırıldı durumu güncellenemedi', 'error');
    }
}

async function addTag() {
    const tag = dom.tagInput.value.trim();
    if (!tag || !state.selectedModel) return;

    const tags = [...(state.selectedModel.tags || [])];
    if (tags.includes(tag)) {
        toast('Bu etiket zaten ekli', 'info');
        return;
    }
    tags.push(tag);

    try {
        await api(`/api/models/${state.selectedModel.id}/tags`, {
            method: 'POST',
            body: JSON.stringify({ tags }),
        });
        updateModelState(state.selectedModel.id, { tags });
        renderModalTags();
        renderSuggestedTags();
        dom.tagInput.value = '';
        await loadModels();
        loadTags();
        toast(`"${tag}" etiketi eklendi`, 'success');
    } catch (e) {
        toast('Etiket eklenemedi', 'error');
    }
}

async function removeTag(tag) {
    if (!state.selectedModel) return;
    const tags = (state.selectedModel.tags || []).filter(t => t !== tag);
    try {
        await api(`/api/models/${state.selectedModel.id}/tags`, {
            method: 'POST',
            body: JSON.stringify({ tags }),
        });
        updateModelState(state.selectedModel.id, { tags });
        renderModalTags();
        renderSuggestedTags();
        await loadModels();
        loadTags();
        toast(`"${tag}" etiketi kaldırıldı`, 'info');
    } catch (e) {
        toast('Etiket kaldırılamadı', 'error');
    }
}

async function saveNote() {
    if (!state.selectedModel) return;
    const note = dom.noteInput.value;
    try {
        await api(`/api/models/${state.selectedModel.id}/note`, {
            method: 'POST',
            body: JSON.stringify({ note }),
        });
        updateModelState(state.selectedModel.id, { note });
        toast('Not kaydedildi', 'success');
    } catch (e) {
        toast('Not kaydedilemedi', 'error');
    }
}

// ─── 3D Preview Modal ──────────────────────────────────────
function openPreview(modelId) {
    const model = state.models.find(m => m.id === modelId);
    if (!model) return;

    state.selectedModel = model;
    dom.previewModal.classList.add('visible');
    document.body.style.overflow = 'hidden';
    setSidebarOpen(false);

    // Modal bilgilerini doldur
    dom.modalTitle.textContent = model.display_name || model.name;
    renderPrintedState(model);
    dom.modalFavorite.classList.toggle('active', model.favorite);
    dom.detailFormat.textContent = model.format.toUpperCase();
    dom.detailSize.textContent = model.size_display;
    dom.detailFileCount.textContent = model.file_count;
    dom.detailType.textContent = getModelDetailType(model.type);
    dom.noteInput.value = model.note || '';

    renderModalTags();
    renderSuggestedTags();
    loadTagSuggestions();

    const filePath = model.main_file || model.path;
    showSelectedFile(filePath);
}

function closePreview() {
    dom.previewModal.classList.remove('visible');
    document.body.style.overflow = '';
    state.selectedModel = null;
    state.selectedFilePath = '';
    setViewerControlsVisible(true);
    disposeViewer();
    renderGrid();
}

function renderModalTags() {
    const tags = state.selectedModel?.tags || [];
    dom.currentTags.innerHTML = tags.map(t => `
        <span class="editable-tag">
            ${escapeHtml(t)}
            <span class="remove-tag" data-tag="${escapeHtml(t)}">×</span>
        </span>
    `).join('');
}

function renderSuggestedTags() {
    const model = state.selectedModel;
    if (!model) return;
    const existing = new Set(model.tags || []);
    const suggested = (model.suggested_tags || []).filter(t => !existing.has(t));

    if (suggested.length === 0) {
        dom.suggestedTags.innerHTML = '';
        return;
    }
    dom.suggestedTags.innerHTML = '<span style="font-size:0.72rem;color:var(--text-muted)">Önerilen:</span> ' +
        suggested.map(t => `<span class="suggest-tag" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join('');
}

async function addSuggestedTag(tag) {
    if (!state.selectedModel) return;
    const tags = [...(state.selectedModel.tags || []), tag];
    try {
        await api(`/api/models/${state.selectedModel.id}/tags`, {
            method: 'POST',
            body: JSON.stringify({ tags }),
        });
        updateModelState(state.selectedModel.id, { tags });
        renderModalTags();
        renderSuggestedTags();
        await loadModels();
        loadTags();
        toast(`"${tag}" etiketi eklendi`, 'success');
    } catch (e) {
        toast('Etiket eklenemedi', 'error');
    }
}

async function loadTagSuggestions() {
    try {
        const data = await api(withGroupMode('/api/tags'));
        dom.tagSuggestions.replaceChildren();
        data.tags.forEach((tag) => {
            const option = document.createElement('option');
            option.value = tag.name;
            dom.tagSuggestions.appendChild(option);
        });
    } catch (e) { /* pass */ }
}

// ─── Three.js Modal Viewer ─────────────────────────────────
function initViewer() {
    disposeViewer();

    const container = dom.viewerContainer;
    const canvas = dom.viewer3D;

    state.scene = new THREE.Scene();
    state.scene.background = new THREE.Color(0xeceef6);

    const aspect = container.clientWidth / container.clientHeight;
    state.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 2000);
    state.camera.position.set(0, 80, 150);

    state.renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
    });
    state.renderer.setSize(container.clientWidth, container.clientHeight);
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    state.renderer.shadowMap.enabled = true;
    state.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    state.renderer.outputEncoding = THREE.sRGBEncoding;
    state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    state.renderer.toneMappingExposure = 1.3;

    // Lights
    const ambientLight = new THREE.AmbientLight(0x808090, 0.7);
    state.scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
    dirLight.position.set(50, 100, 80);
    dirLight.castShadow = true;
    state.scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0x5b5ff7, 0.3);
    fillLight.position.set(-50, 30, -50);
    state.scene.add(fillLight);

    const rimLight = new THREE.DirectionalLight(0xa855f7, 0.2);
    rimLight.position.set(0, -30, -60);
    state.scene.add(rimLight);

    const hemiLight = new THREE.HemisphereLight(0x8888cc, 0xf0f0ff, 0.4);
    state.scene.add(hemiLight);

    // Grid
    const gridHelper = new THREE.GridHelper(200, 40, 0xd0d4e4, 0xe0e4f0);
    state.scene.add(gridHelper);

    // Controls
    state.controls = new THREE.OrbitControls(state.camera, state.renderer.domElement);
    state.controls.enableDamping = true;
    state.controls.dampingFactor = 0.08;
    state.controls.enablePan = true;
    state.controls.autoRotate = true;
    state.controls.autoRotateSpeed = 1.0;

    const onResize = () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        state.camera.aspect = w / h;
        state.camera.updateProjectionMatrix();
        state.renderer.setSize(w, h);
    };
    window.addEventListener('resize', onResize);
    state._onResize = onResize;

    function animate() {
        state.animationId = requestAnimationFrame(animate);
        state.controls.update();
        state.renderer.render(state.scene, state.camera);
    }
    animate();
}

function showViewerLoading(message = '3D model yükleniyor...') {
    dom.viewerLoading.classList.add('visible');
    dom.viewerLoading.innerHTML = `<div class="spinner"></div><p>${message}</p>`;
}

function disposeMaterial(material) {
    const materials = Array.isArray(material) ? material : [material];
    materials.filter(Boolean).forEach((entry) => {
        Object.values(entry).forEach((value) => {
            if (value && value.isTexture) {
                value.dispose();
            }
        });
        entry.dispose?.();
    });
}

function disposeObject3D(object) {
    if (!object) return;
    object.traverse((child) => {
        child.geometry?.dispose?.();
        if (child.material) {
            disposeMaterial(child.material);
        }
    });
}

function clearCurrentObject() {
    if (!state.currentObject) return;
    state.scene?.remove(state.currentObject);
    disposeObject3D(state.currentObject);
    state.currentObject = null;
}

function prepareViewerObject(object) {
    object.traverse((child) => {
        if (!child.isMesh) return;
        child.castShadow = true;
        child.receiveShadow = true;
        if (child.geometry && !child.geometry.attributes.normal && child.geometry.computeVertexNormals) {
            child.geometry.computeVertexNormals();
        }
    });
}

function fitViewerObject(object) {
    const wrapper = new THREE.Group();
    wrapper.add(object);

    const bounds = new THREE.Box3().setFromObject(object);
    if (bounds.isEmpty()) {
        return wrapper;
    }

    const center = bounds.getCenter(new THREE.Vector3());
    object.position.sub(center);

    const size = bounds.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    const scale = 80 / maxDim;
    wrapper.scale.setScalar(scale);

    const groundedBounds = new THREE.Box3().setFromObject(wrapper);
    wrapper.position.y = -groundedBounds.min.y;

    return wrapper;
}

function focusViewerObject(object) {
    const bounds = new THREE.Box3().setFromObject(object);
    if (bounds.isEmpty()) return;

    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 80);
    const distance = maxDim * 1.6;

    state.camera.position.set(
        center.x + distance * 0.6,
        center.y + distance * 0.5,
        center.z + distance * 0.8,
    );
    state.controls.target.copy(center);
    state.controls.update();
}

function setViewerObject(object) {
    clearCurrentObject();
    prepareViewerObject(object);

    const framedObject = fitViewerObject(object);
    state.currentObject = framedObject;
    state.scene.add(framedObject);
    focusViewerObject(framedObject);

    dom.viewerLoading.classList.remove('visible');
}

function renderViewerLoadError(message = 'Model yüklenemedi') {
    dom.viewerLoading.classList.add('visible');
    dom.viewerLoading.innerHTML = `
        <div style="text-align: center; color: var(--text-secondary);">
            <div style="font-size: 3rem; margin-bottom: 12px;">⚠️</div>
            <p>${message}</p>
        </div>
    `;
}

function renderViewerImagePreview(imageUrl, message, fallbackMessage) {
    disposeViewer();
    setViewerControlsVisible(false);
    showViewerLoading(message);

    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;max-width:100%;padding:12px;';

    const image = document.createElement('img');
    image.alt = message;
    image.style.cssText = 'max-width:min(100%, 560px);max-height:320px;object-fit:contain;border-radius:16px;box-shadow:0 18px 50px rgba(15,23,42,0.18);background:rgba(255,255,255,0.92);';

    const caption = document.createElement('p');
    caption.textContent = message;
    caption.style.cssText = 'margin:0;color:var(--text-secondary);font-size:0.9rem;text-align:center;';

    wrapper.append(image, caption);

    image.addEventListener('load', () => {
        dom.viewerLoading.replaceChildren(wrapper);
        dom.viewerLoading.classList.add('visible');
    });
    image.addEventListener('error', () => {
        renderViewerLoadError(fallbackMessage);
    });

    image.src = imageUrl;
}

function show3MFPreviewFallback(filePath) {
    if (!filePath || state.selectedFilePath !== filePath) return;
    renderViewerImagePreview(
        buildPreviewUrl(filePath),
        '3D mesh açılamadı. Paketteki gömülü 3MF önizlemesi gösteriliyor.',
        '3MF modeli açılamadı ve pakette önizleme görseli bulunamadı.',
    );
}

function loadSTL(url, filePath) {
    showViewerLoading('STL model yükleniyor...');

    const loader = new THREE.STLLoader();
    loader.load(
        url,
        (geometry) => {
            if (state.selectedFilePath !== filePath) return;
            const material = new THREE.MeshPhysicalMaterial({
                color: 0x7c80ff,
                metalness: 0.1,
                roughness: 0.45,
                clearcoat: 0.3,
                clearcoatRoughness: 0.4,
            });

            const mesh = new THREE.Mesh(geometry, material);
            setViewerObject(mesh);
        },
        undefined,
        (error) => {
            if (state.selectedFilePath !== filePath) return;
            console.error('STL yüklenemedi:', error);
            renderViewerLoadError('STL modeli yüklenemedi');
        }
    );
}

function load3MF(url, filePath) {
    showViewerLoading('3MF model yükleniyor...');

    const loader = new THREE.ThreeMFLoader();
    loader.load(
        url,
        (object) => {
            if (state.selectedFilePath !== filePath) return;
            if (!object) {
                show3MFPreviewFallback(filePath);
                return;
            }

            setViewerObject(object);
        },
        undefined,
        (error) => {
            if (state.selectedFilePath !== filePath) return;
            console.error('3MF yüklenemedi:', error);
            show3MFPreviewFallback(filePath);
        }
    );
}

function disposeViewer() {
    if (state.animationId) cancelAnimationFrame(state.animationId);
    clearCurrentObject();
    if (state.renderer) {
        state.renderer.dispose();
        state.renderer = null;
    }
    if (state.controls) {
        state.controls.dispose();
        state.controls = null;
    }
    if (state._onResize) {
        window.removeEventListener('resize', state._onResize);
        state._onResize = null;
    }
    state.scene = null;
    state.camera = null;
}

// ─── Helpers ───────────────────────────────────────────────
function renderPrintedState(model) {
    const printed = Boolean(model?.printed);
    dom.modalPrinted.classList.toggle('active', printed);
    dom.detailPrinted.textContent = printed ? 'Yazdırıldı' : 'Bekliyor';
}

function showSelectedFile(filePath) {
    if (!state.selectedModel || !filePath) return;

    state.selectedFilePath = filePath;
    renderFileList(getAllDisplayFiles(state.selectedModel));

    const fileFormat = getFileFormat(filePath) || state.selectedModel.format;
    dom.detailFormat.textContent = fileFormat.toUpperCase();

    if (fileFormat === 'stl' || fileFormat === '3mf') {
        showViewerLoading(`${fileFormat.toUpperCase()} model yükleniyor...`);
        setViewerControlsVisible(true);
        if (!state.renderer) initViewer();
        if (fileFormat === 'stl') {
            loadSTL(buildFileUrl(filePath), filePath);
        } else {
            load3MF(buildFileUrl(filePath), filePath);
        }
        return;
    }

    if (IMAGE_FILE_FORMATS.has(fileFormat)) {
        renderViewerImagePreview(
            buildFileUrl(filePath),
            `${getFileName(filePath)} görseli gösteriliyor.`,
            'Görsel yüklenemedi.',
        );
        return;
    }

    disposeViewer();
    const message = TEXT_FILE_FORMATS.has(fileFormat)
        ? `${fileFormat.toUpperCase()} dokümanı seçildi. Dosya listesinden indirerek açabilirsiniz.`
        : `${fileFormat.toUpperCase()} dosyası seçildi. Etkileşimli 3D önizleme şu an yalnızca STL ve 3MF için mevcut.`;
    renderViewerMessage(getFormatIcon(fileFormat), message);
}

function renderGrid() {
    if (state.models.length === 0) {
        dom.modelGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📂</div>
                <h3>Model bulunamadı</h3>
                <p>Arama kriterlerini değiştirmeyi deneyin</p>
            </div>
        `;
        return;
    }

    dom.modelGrid.innerHTML = state.models.map((m) => {
        const tags = (m.tags || []).slice(0, 3);
        const isFav = m.favorite ? 'active' : '';
        const isPrinted = m.printed ? '<span class="printed-badge">✅ Yazdırıldı</span>' : '';
        const fileCount = m.file_count > 1 ? `<span class="file-count-badge">${m.file_count} dosya</span>` : '';
        const displayName = escapeHtml(m.display_name || m.name);
        const rawName = escapeHtml(m.name || '');
        const metaType = getModelTypeLabel(m.type);
        const thumbState = getCardThumbnailState(m);
        const thumbFormat = escapeHtml(m.main_file_format || m.format || '');
        let thumbContent = `<span class="thumb-icon">${getFormatIcon(m.main_file_format || m.format)}</span>`;
        if (thumbState.kind === 'cached' || thumbState.kind === 'image') {
            thumbContent = `<img src="${thumbState.source}" alt="${displayName}" style="width:100%;height:100%;object-fit:contain;">`;
        } else if (thumbState.kind === 'generated') {
            thumbContent = `<div class="thumb-loading" data-model-id="${m.id}"><div class="mini-spinner"></div><span>Yükleniyor</span></div>`;
        }
        const makerBadges = getMakerBadges(m).slice(0, 3);
        const assetLabel = m.asset_count ? `<span class="card-support-tag">+${m.asset_count} ek</span>` : '';

        return `
            <div class="model-card" data-id="${m.id}">
                <div class="card-thumbnail" data-thumb-id="${m.id}" data-format="${thumbFormat}" data-thumb-kind="${thumbState.kind}">
                    <span class="format-badge">${escapeHtml((m.main_file_format || m.format || '').toUpperCase())}</span>
                    ${fileCount}
                    ${thumbContent}
                    ${isPrinted}
                    <div class="card-favorite ${isFav}" data-action="favorite" role="button" tabindex="0" aria-label="Favori">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                        </svg>
                    </div>
                </div>
                <div class="card-body">
                    <div class="card-name" title="${rawName}">${displayName}</div>
                    <div class="card-meta">
                        <span>${escapeHtml(m.size_display)}</span>
                        <span>${metaType}</span>
                    </div>
                    <div class="card-supports">
                        ${makerBadges.map((badge) => `<span class="card-support-tag">${escapeHtml(badge)}</span>`).join('')}
                        ${assetLabel}
                    </div>
                    <div class="card-tags">
                        ${tags.map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join('')}
                        ${m.tags && m.tags.length > 3 ? `<span class="card-tag">+${m.tags.length - 3}</span>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    setupThumbnailObserver();
}

function setupThumbnailObserver() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            const modelId = el.dataset.thumbId;
            if (el.dataset.thumbKind === 'generated' && !state.thumbCache[modelId]) {
                queueThumbnail(modelId);
            }
            observer.unobserve(el);
        });
    }, {
        rootMargin: '200px',
        threshold: 0,
    });

    document.querySelectorAll('.card-thumbnail[data-thumb-kind="generated"]').forEach((el) => {
        if (!state.thumbCache[el.dataset.thumbId]) {
            observer.observe(el);
        }
    });
}

function renderMakerDetails(model) {
    const badges = getMakerBadges(model);
    dom.makerBadges.innerHTML = badges.length
        ? badges.map((badge) => `<span class="detail-badge">${escapeHtml(badge)}</span>`).join('')
        : '<span class="empty-note">Ek maker metadata bulunamadı.</span>';

    const profileEntries = Object.entries(model.print_profile || {});
    dom.printProfile.innerHTML = profileEntries.map(([key, value]) => `
        <div class="profile-item">
            <span>${escapeHtml(getPrintProfileLabel(key))}</span>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `).join('');

    dom.readmeExcerpt.textContent = model.readme_excerpt || '';
    dom.readmeExcerpt.hidden = !model.readme_excerpt;

    const links = [];
    if (model.readme_path) {
        links.push(`<a class="resource-link" href="${buildFileUrl(model.readme_path)}" target="_blank" rel="noreferrer">README</a>`);
    }
    if (model.license_path) {
        links.push(`<a class="resource-link" href="${buildFileUrl(model.license_path)}" target="_blank" rel="noreferrer">Lisans</a>`);
    }
    if (model.source_url) {
        links.push(`<a class="resource-link" href="${escapeHtml(model.source_url)}" target="_blank" rel="noreferrer">Kaynak</a>`);
    }
    dom.resourceLinks.innerHTML = links.join('');

    const hasContent = badges.length || profileEntries.length || model.readme_excerpt || links.length;
    dom.makerInfoSection.hidden = !hasContent;
}

function renderPreviewGallery(model) {
    const images = (model.preview_images || []).slice(0, 8);
    if (!images.length) {
        dom.previewGallery.innerHTML = '';
        dom.previewGallerySection.hidden = true;
        return;
    }

    dom.previewGallery.innerHTML = images.map((filePath) => `
        <button type="button" class="preview-thumb" data-file-path="${escapeHtml(filePath)}">
            <img src="${buildFileUrl(filePath)}" alt="${escapeHtml(getFileName(filePath))}">
        </button>
    `).join('');
    dom.previewGallerySection.hidden = false;
}

function openPreview(modelId) {
    const model = state.models.find((item) => item.id === modelId);
    if (!model) return;

    state.selectedModel = model;
    dom.previewModal.classList.add('visible');
    document.body.style.overflow = 'hidden';
    setSidebarOpen(false);

    dom.modalTitle.textContent = model.display_name || model.name;
    renderPrintedState(model);
    dom.modalFavorite.classList.toggle('active', model.favorite);
    dom.detailFormat.textContent = String(model.main_file_format || model.format || '').toUpperCase();
    dom.detailFormats.textContent = formatAvailableFormats(model.available_formats || [model.format]);
    dom.detailSize.textContent = model.size_display;
    dom.detailFileCount.textContent = model.file_count;
    dom.detailType.textContent = getModelDetailType(model.type);
    dom.detailAssets.textContent = `${model.asset_count || 0} dosya`;
    dom.noteInput.value = model.note || '';

    renderModalTags();
    renderSuggestedTags();
    renderMakerDetails(model);
    renderPreviewGallery(model);
    loadTagSuggestions();

    const filePath = model.main_file || model.path;
    showSelectedFile(filePath);
}

document.addEventListener('DOMContentLoaded', () => {
    dom.makerChips?.addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;
        const flag = chip.dataset.flag;
        if (!flag) return;
        state.currentMakerFilters[flag] = !state.currentMakerFilters[flag];
        chip.classList.toggle('active', state.currentMakerFilters[flag]);
        loadModels();
        if (isMobileViewport()) setSidebarOpen(false);
    });

    dom.previewGallery?.addEventListener('click', (e) => {
        const button = e.target.closest('[data-file-path]');
        if (!button) return;
        showSelectedFile(button.dataset.filePath || '');
    });
});

function showLoading(visible) {
    dom.loadingOverlay.classList.toggle('visible', visible);
}

function toast(message, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    dom.toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3200);
}

// CSS animation for thumbnail fade-in
const styleSheet = document.createElement('style');
styleSheet.textContent = `@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }`;
document.head.appendChild(styleSheet);
