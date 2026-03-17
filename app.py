"""
3D Model Yöneticisi — Flask Backend
Dağınık 3D model dosyalarını tarayan, kataloglayan ve yöneten web uygulaması.
"""

import hashlib
import io
import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import BadRequest, HTTPException

app = Flask(__name__)

# Yapılandırma
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "3d models"
DB_PATH = BASE_DIR / "db.json"
DB_LOCK = threading.RLock()
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5000
GROUP_MODES = ('project', 'folder')

# Desteklenen dosya formatları
SUPPORTED_FORMATS = {'.stl', '.3mf', '.obj', '.gltf', '.glb', '.fbx', '.ply'}
THREEMF_PREVIEW_CANDIDATES = (
    'Auxiliaries/.thumbnails/thumbnail_3mf.png',
    'Auxiliaries/.thumbnails/thumbnail_middle.png',
    'Auxiliaries/.thumbnails/thumbnail_small.png',
    'Metadata/plate_1.png',
    'Metadata/top_1.png',
)

# Otomatik kategori eşleştirme kuralları
AUTO_TAGS = {
    '🧩 Fidget/Oyuncak': ['fidget', 'spinner', 'toy', 'spiral', 'twisty', 'passthrough', 'kıpır'],
    '🧸 Bebek/Oyuncak': ['barbie', 'polly', 'doll', 'dollhouse', 'dreamhouse', 'ranza', 'bunk bed'],
    '📦 Kutu/Depolama': ['box', 'kutu', 'storage', 'drawer', 'tray', 'case', 'bin'],
    '🔧 Aksesuar/Tutucu': ['holder', 'clip', 'rack', 'stand', 'hook', 'charger', 'cable', 'tutucu', 'telefon'],
    '🚗 Araç Modeli': ['car', 'jeep', 'vehicle', 'nissan', 'delorean', 'bus'],
    '⚙️ Mekanizma/Dişli': ['gear', 'mechanism', 'mechanical', 'ratchet'],
    '🎄 Dekorasyon': ['christmas', 'decoration', 'bauble', 'gingerbread', 'valentine', 'art', 'shadow'],
    '🎵 Müzik': ['flute', 'whistle', 'düdük', 'pan flute', 'music'],
    '🖨️ Yazıcı Parçası': ['ender', 'creality', 'printer', 'spool', 'filament', 'nozzle', 'bed'],
    '🎪 Park/Oyun Alanı': ['slide', 'playground', 'park', 'kaydirak'],
    '🔑 Anahtarlık': ['key', 'keychain', 'anahtar', 'anahtarlık', 'llavero'],
    '📸 Kamera/Lens': ['lens', 'hood', 'camera', 'canon', 'nikon'],
    '🧩 Puzzle/Bulmaca': ['puzzle', 'maze', 'labyrinth'],
    '✋ Şaka/Eğlence': ['prank', 'nah', 'middle finger', 'surprise', 'sürpriz'],
    '🪑 Mobilya': ['chair', 'desk', 'table', 'bed', 'furniture', 'mesa', 'silla', 'masa'],
    '🔋 Pil/Elektronik': ['battery', 'usb', 'sd', 'ssd', 'hdd', 'electronic', 'charging'],
    '✏️ Kırtasiye': ['kalem', 'pencil', 'pen', 'stationery'],
    '👓 Giyilebilir': ['glasses', 'gözlük', 'pinhole', 'wearable'],
    '🐻 Figür/Heykel': ['bear', 'cat', 'animal', 'figure', 'statue', 'woman', 'urso'],
    '⭐ Harf/Yazı': ['letter', 'alphabet', 'name', 'abc', 'text', 'sign', 'işaret'],
}


def default_db():
    """Uygulama veritabanı için varsayılan şema."""
    return {'models': {}, 'catalog': {}, 'catalogs': {}, 'last_scan': None}


def coerce_int(value, default=0):
    """Sayı alanlarını güvenli şekilde tam sayıya çevir."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_float(value, default=0.0):
    """Sayı alanlarını güvenli şekilde ondalık sayıya çevir."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_catalog_path(path_value):
    """Katalogda tutulan göreli yolları platform bağımsız hale getir."""
    if not isinstance(path_value, str):
        return ''
    return path_value.replace('\\', '/').strip().lstrip('/')


def relative_model_path(path_obj):
    """Model yolunu katalog için göreli POSIX biçimine çevir."""
    return normalize_catalog_path(path_obj.relative_to(MODELS_DIR).as_posix())


def normalize_catalog_record(model_id, record=None):
    """Tarama katalog kaydını API için güvenli ve tutarlı hale getir."""
    if not isinstance(record, dict):
        return None

    path = normalize_catalog_path(record.get('path'))
    files = []
    for item in record.get('files', []):
        normalized_item = normalize_catalog_path(item)
        if normalized_item:
            files.append(normalized_item)

    if not files and path:
        files = [path]

    size = coerce_int(record.get('size'), default=0)
    normalized = {
        'id': str(model_id),
        'name': str(record.get('name') or model_id),
        'display_name': str(record.get('display_name') or record.get('name') or model_id),
        'type': record.get('type') if record.get('type') in {'project', 'folder'} else 'file',
        'format': str(record.get('format', '')).lower(),
        'path': path,
        'size': size,
        'size_display': str(record.get('size_display') or format_size(size)),
        'modified': coerce_float(record.get('modified'), default=0.0),
        'files': files,
        'file_count': coerce_int(record.get('file_count'), default=len(files) or 1),
        'suggested_tags': [str(tag).strip() for tag in record.get('suggested_tags', []) if str(tag).strip()],
    }

    main_file = normalize_catalog_path(record.get('main_file'))
    if main_file:
        normalized['main_file'] = main_file

    return normalized


def normalize_catalog(catalog=None):
    """Tüm katalog kayıtlarını normalize et ve iç alanları temizle."""
    normalized = {}
    if not isinstance(catalog, dict):
        return normalized

    for model_id, record in catalog.items():
        normalized_record = normalize_catalog_record(str(model_id), record)
        if normalized_record is not None:
            normalized[str(model_id)] = normalized_record

    return normalized


def resolve_model_file_path(filepath):
    """API'den gelen göreli model yolunu güvenli şekilde çöz."""
    full_path = MODELS_DIR / filepath
    if not full_path.exists() or not full_path.is_file():
        abort(404)

    try:
        full_path.resolve().relative_to(MODELS_DIR.resolve())
    except ValueError:
        abort(403)

    if full_path.suffix.lower() not in SUPPORTED_FORMATS:
        abort(404)

    return full_path


def find_3mf_preview_entry(zip_file):
    """3MF paketindeki en uygun gömülü önizleme görselini bul."""
    names = set(zip_file.namelist())
    for candidate in THREEMF_PREVIEW_CANDIDATES:
        if candidate in names:
            return candidate

    preferred_prefixes = ('Auxiliaries/.thumbnails/', 'Metadata/', 'Auxiliaries/Model Pictures/')
    preferred_suffixes = ('.png', '.webp', '.jpg', '.jpeg')

    for name in zip_file.namelist():
        lowered = name.lower()
        if lowered.endswith(preferred_suffixes) and lowered.startswith(tuple(prefix.lower() for prefix in preferred_prefixes)):
            return name

    for name in zip_file.namelist():
        lowered = name.lower()
        if lowered.endswith(preferred_suffixes):
            return name

    return None


def read_3mf_preview(full_path):
    """3MF içindeki gömülü önizleme görselini oku."""
    try:
        with zipfile.ZipFile(full_path, 'r') as archive:
            preview_entry = find_3mf_preview_entry(archive)
            if not preview_entry:
                return None

            preview_bytes = archive.read(preview_entry)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None

    mimetype = mimetypes.guess_type(preview_entry)[0] or 'application/octet-stream'
    return preview_entry, preview_bytes, mimetype


def normalize_db(db=None):
    """Diskten gelen DB yapısını güncel şemaya hizala."""
    normalized = default_db()
    if not isinstance(db, dict):
        return normalized

    if isinstance(db.get('models'), dict):
        normalized['models'] = db['models']

    has_catalog = False
    if isinstance(db.get('catalog'), dict):
        normalized['catalog'] = normalize_catalog(db.get('catalog'))
        has_catalog = True

    if isinstance(db.get('catalogs'), dict):
        normalized['catalogs'] = {
            str(group_mode): normalize_catalog(catalog)
            for group_mode, catalog in db['catalogs'].items()
            if str(group_mode) in GROUP_MODES and isinstance(catalog, dict)
        }

    if not has_catalog and 'project' in normalized['catalogs']:
        normalized['catalog'] = normalized['catalogs']['project']
        has_catalog = True

    last_scan = db.get('last_scan')
    if has_catalog and isinstance(last_scan, (int, float)):
        normalized['last_scan'] = float(last_scan)

    return normalized


def default_model_record(tags=None):
    """Yeni model kaydı için varsayılan kullanıcı verisi oluştur."""
    return {
        'tags': list(tags or []),
        'favorite': False,
        'note': '',
        'printed': False,
    }


def normalize_model_record(record=None, suggested_tags=None):
    """Eksik alanları tamamla ve veri tiplerini tutarlı hale getir."""
    normalized = default_model_record(suggested_tags)
    if not isinstance(record, dict):
        return normalized

    if isinstance(record.get('tags'), list):
        normalized['tags'] = [str(tag).strip() for tag in record['tags'] if str(tag).strip()]
    normalized['favorite'] = bool(record.get('favorite', False))
    normalized['note'] = str(record.get('note', ''))
    normalized['printed'] = bool(record.get('printed', False))
    return normalized


def sanitize_tags(tags):
    """Etiket listesini normalize et ve tekrarları temizle."""
    if not isinstance(tags, list):
        abort(400, description='tags must be a list')

    cleaned = []
    seen = set()
    for raw_tag in tags:
        if not isinstance(raw_tag, str):
            continue
        tag = raw_tag.strip()[:64]
        if not tag or tag in seen:
            continue
        cleaned.append(tag)
        seen.add(tag)
    return cleaned


def generate_id(path_str):
    """Dosya yolundan tekrarlanabilir benzersiz ID üret."""
    return hashlib.md5(path_str.encode('utf-8')).hexdigest()[:12]


def parse_group_mode(group_mode=None, default='folder'):
    """Geçerli gruplama modunu doğrula."""
    normalized = str(group_mode or default).strip().lower()
    if normalized not in GROUP_MODES:
        abort(400, description='Invalid group mode')
    return normalized


def build_model_id(key, group_mode='project'):
    """Görünüm moduna göre kararlı model ID üret."""
    base_id = generate_id(key)
    return base_id if group_mode == 'project' else f'{group_mode}:{base_id}'


def infer_group_mode_from_model_id(model_id):
    """Model ID'sinden hangi görünüm moduna ait olduğunu çöz."""
    model_id = str(model_id)
    for group_mode in GROUP_MODES:
        if group_mode != 'project' and model_id.startswith(f'{group_mode}:'):
            return group_mode
    return 'project'


def model_id_matches_group_mode(model_id, group_mode):
    """DB kaydının ilgili görünüm moduna ait olup olmadığını belirle."""
    model_id = str(model_id)
    if group_mode == 'project':
        return ':' not in model_id
    return model_id.startswith(f'{group_mode}:')


def format_size(size_bytes):
    """Byte cinsinden boyutu okunabilir formata çevir."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def suggest_tags(name):
    """Dosya/klasör adından otomatik etiket öner."""
    name_lower = name.lower()
    suggested = []
    for tag, keywords in AUTO_TAGS.items():
        for kw in keywords:
            if kw in name_lower:
                suggested.append(tag)
                break
    return suggested


def choose_group_main_file(file_entries):
    """Önizleme için en uygun ana dosyayı seç."""
    preferred_files = [entry for entry in file_entries if entry['format'] == 'stl']
    candidates = preferred_files or list(file_entries)
    return max(candidates, key=lambda entry: (entry['size'], entry['rel_path'].lower()))


def scan_model_snapshot():
    """Dosya sistemini tek geçişte okuyup tarama özeti üret."""
    snapshot = {
        'root_files': [],
        'groups': {group_mode: {} for group_mode in GROUP_MODES},
    }

    if not MODELS_DIR.exists():
        return snapshot

    for root, dirs, files in os.walk(MODELS_DIR):
        dirs.sort()
        files.sort()
        root_path = Path(root)

        for filename in files:
            file_path = root_path / filename
            ext = file_path.suffix.lower()

            if ext not in SUPPORTED_FORMATS:
                continue

            try:
                stat = file_path.stat()
            except OSError:
                continue

            entry = {
                'path_obj': file_path,
                'root_path': root_path,
                'name': file_path.stem,
                'format': ext.lstrip('.'),
                'rel_path': relative_model_path(file_path),
                'size': stat.st_size,
                'modified': stat.st_mtime,
            }

            if root_path == MODELS_DIR:
                snapshot['root_files'].append(entry)
                continue

            rel_root = root_path.relative_to(MODELS_DIR)
            project_dir = MODELS_DIR / rel_root.parts[0]
            grouped_dirs = {
                'project': project_dir,
                'folder': root_path,
            }

            for group_mode, group_dir in grouped_dirs.items():
                group_key = relative_model_path(group_dir)
                groups = snapshot['groups'][group_mode]
                if group_key not in groups:
                    groups[group_key] = {
                        'name': group_dir.name,
                        'path': group_dir,
                        'files': [],
                    }
                groups[group_key]['files'].append(entry)

    return snapshot


def build_catalog_from_snapshot(snapshot, group_mode='project'):
    """Snapshot verisinden istenen görünümün katalogunu oluştur."""
    group_mode = parse_group_mode(group_mode)
    models = {}

    for entry in snapshot.get('root_files', []):
        rel_path = entry['rel_path']
        model_id = build_model_id(rel_path, group_mode=group_mode)
        name = entry['name']
        if name.endswith('.stl') or name.endswith('.3mf'):
            name = Path(name).stem

        models[model_id] = normalize_catalog_record(model_id, {
            'id': model_id,
            'name': name,
            'display_name': name,
            'type': 'file',
            'format': entry['format'],
            'path': rel_path,
            'size': entry['size'],
            'size_display': format_size(entry['size']),
            'modified': entry['modified'],
            'files': [rel_path],
            'file_count': 1,
            'suggested_tags': suggest_tags(name),
        })

    for grouped in snapshot.get('groups', {}).get(group_mode, {}).values():
        group_path = relative_model_path(grouped['path'])
        model_id = build_model_id(group_path, group_mode=group_mode)
        file_entries = grouped['files']
        total_size = sum(entry['size'] for entry in file_entries)
        latest_modified = max(entry['modified'] for entry in file_entries)
        file_list = [entry['rel_path'] for entry in file_entries]
        main_file = choose_group_main_file(file_entries)
        name = grouped['name']

        clean_name = name
        for sep in [' - ', ' -']:
            parts = clean_name.rsplit(sep, 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                clean_name = parts[0].strip()

        models[model_id] = normalize_catalog_record(model_id, {
            'id': model_id,
            'name': name,
            'display_name': clean_name,
            'type': 'folder' if group_mode == 'folder' else 'project',
            'format': main_file['format'],
            'path': group_path,
            'main_file': main_file['rel_path'],
            'size': total_size,
            'size_display': format_size(total_size),
            'modified': latest_modified,
            'files': file_list,
            'file_count': len(file_list),
            'suggested_tags': suggest_tags(name),
        })

    return models


def scan_models(group_mode='project'):
    """3D model klasörünü tara ve istenen görünüm için katalog üret."""
    snapshot = scan_model_snapshot()
    return build_catalog_from_snapshot(snapshot, group_mode=group_mode)


def _load_db_unlocked():
    """Veritabanını yükle, yoksa boş oluştur."""
    if not DB_PATH.exists():
        return default_db()

    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return normalize_db(json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        backup_path = None
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        candidate = DB_PATH.with_name(f'{DB_PATH.stem}.corrupt-{timestamp}{DB_PATH.suffix}')
        try:
            DB_PATH.replace(candidate)
            backup_path = candidate
        except OSError:
            pass
        app.logger.warning('DB yüklenemedi, yeni veritabanı ile devam ediliyor. backup=%s error=%s', backup_path, exc)
        return default_db()


def load_db():
    """Veritabanını kilit koruması altında yükle."""
    with DB_LOCK:
        return _load_db_unlocked()


def _save_db_unlocked(db):
    """Veritabanını kaydet."""
    normalized = normalize_db(db)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=DB_PATH.parent, delete=False) as tmp_file:
        json.dump(normalized, tmp_file, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp_file.name)

    tmp_path.replace(DB_PATH)


def save_db(db):
    """Veritabanını kilit koruması altında kaydet."""
    with DB_LOCK:
        _save_db_unlocked(db)


def sync_db_with_scan(db, scanned, group_mode='project'):
    """İlgili görünüm modundaki model kayıtlarını güncel tarama ile hizala."""
    group_mode = parse_group_mode(group_mode)
    current_models = db.get('models', {})
    synced_models = {
        mid: record
        for mid, record in current_models.items()
        if not model_id_matches_group_mode(mid, group_mode)
    }

    for mid, mdata in scanned.items():
        synced_models[mid] = normalize_model_record(
            current_models.get(mid),
            mdata.get('suggested_tags', []),
        )

    changed = synced_models != current_models
    db['models'] = synced_models
    return changed


def get_catalog_for_mode(db, group_mode='project'):
    """İstenen görünüm modunun katalogunu döndür."""
    group_mode = parse_group_mode(group_mode)
    if group_mode == 'project':
        return db.get('catalog', {})
    return db.get('catalogs', {}).get(group_mode)


def set_catalog_for_mode(db, scanned, group_mode='project'):
    """İstenen görünüm modunun katalogunu güncelle."""
    group_mode = parse_group_mode(group_mode)
    if group_mode == 'project':
        db['catalog'] = scanned
        return
    db.setdefault('catalogs', {})[group_mode] = scanned


def refresh_all_catalogs_unlocked(db):
    """Tüm görünüm modları için katalogları yeniden üret."""
    snapshot = scan_model_snapshot()
    for group_mode in GROUP_MODES:
        scanned = normalize_catalog(build_catalog_from_snapshot(snapshot, group_mode=group_mode))
        set_catalog_for_mode(db, scanned, group_mode=group_mode)
        sync_db_with_scan(db, scanned, group_mode=group_mode)
    db['last_scan'] = time.time()


def _get_synced_state_unlocked(refresh=False, group_mode='folder'):
    """Tarama sonuçları ile kullanıcı verilerini senkron halde döndür."""
    group_mode = parse_group_mode(group_mode)
    db = _load_db_unlocked()
    should_refresh_all = refresh or db.get('last_scan') is None
    if should_refresh_all:
        refresh_all_catalogs_unlocked(db)
        _save_db_unlocked(db)
        return db, get_catalog_for_mode(db, group_mode=group_mode)

    scanned = get_catalog_for_mode(db, group_mode=group_mode)
    if scanned is None:
        scanned = normalize_catalog(scan_models(group_mode=group_mode))
        set_catalog_for_mode(db, scanned, group_mode=group_mode)
        db['last_scan'] = time.time()
        sync_db_with_scan(db, scanned, group_mode=group_mode)
        _save_db_unlocked(db)
        return db, scanned

    changed = sync_db_with_scan(db, scanned, group_mode=group_mode)
    if changed:
        _save_db_unlocked(db)

    return db, scanned


def get_synced_state(refresh=False, group_mode='folder'):
    """Tarama sonuçları ile kullanıcı verilerini kilit koruması altında döndür."""
    with DB_LOCK:
        return _get_synced_state_unlocked(refresh=refresh, group_mode=group_mode)


def _get_existing_model_or_404_unlocked(model_id):
    """Model gerçekten mevcutsa DB kaydını döndür, değilse 404 ver."""
    group_mode = infer_group_mode_from_model_id(model_id)
    db, scanned = _get_synced_state_unlocked(group_mode=group_mode)
    if model_id not in scanned:
        abort(404, description='Model not found')

    primary_path = scanned[model_id].get('main_file') or scanned[model_id].get('path')
    if primary_path and not (MODELS_DIR / primary_path).exists():
        db, scanned = _get_synced_state_unlocked(refresh=True, group_mode=group_mode)
        if model_id not in scanned:
            abort(404, description='Model not found')

    return db, scanned, db['models'][model_id]


def get_existing_model_or_404(model_id):
    """Modeli kilit koruması altında doğrula ve DB kaydını döndür."""
    with DB_LOCK:
        return _get_existing_model_or_404_unlocked(model_id)


def mutate_model_record(model_id, mutator):
    """Bir model kaydını atomik olarak güncelle."""
    with DB_LOCK:
        db, _, record = _get_existing_model_or_404_unlocked(model_id)
        response_payload = mutator(record)
        _save_db_unlocked(db)
        return response_payload


def ensure_scanned():
    """Eğer henüz taranmamışsa taramayı çalıştır ve DB'ye kaydet."""
    with DB_LOCK:
        db = _load_db_unlocked()
        if db.get('last_scan') is None:
            db, _ = _get_synced_state_unlocked(refresh=True)
        return db


def parse_json_object():
    """JSON body'yi doğrula ve nesne olarak döndür."""
    if not request.is_json:
        abort(400, description='Expected JSON body')

    try:
        data = request.get_json(silent=False)
    except BadRequest:
        abort(400, description='Invalid JSON body')

    if not isinstance(data, dict):
        abort(400, description='JSON body must be an object')

    return data


def safe_console_text(value, encoding=None):
    """Konsolun desteklemediği karakterleri güvenli şekilde dönüştür."""
    text = str(value)
    target_encoding = encoding or getattr(sys.stdout, 'encoding', None) or 'utf-8'
    return text.encode(target_encoding, errors='replace').decode(target_encoding, errors='replace')


def print_startup_banner(stream=None):
    """Başlangıç bilgilerini terminal encoding'ine uygun bas."""
    run_settings = get_run_settings()
    output = stream or sys.stdout
    encoding = getattr(output, 'encoding', None)
    for line in (
        '',
        '3D Model Manager starting...',
        f'Model directory: {MODELS_DIR}',
        f'Open {build_local_url(run_settings["host"], run_settings["port"])}',
        '',
    ):
        print(safe_console_text(line, encoding=encoding), file=output)


def parse_env_bool(value, default=False):
    """Çevre değişkenlerinden gelen bool değerlerini yorumla."""
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def build_local_url(host, port):
    """Terminal için okunabilir bir yerel URL üret."""
    display_host = 'localhost' if host in {'0.0.0.0', '::', DEFAULT_HOST} else host
    return f'http://{display_host}:{port}'


def get_run_settings():
    """Flask çalışma ayarlarını çevre değişkenlerinden oku."""
    host = os.getenv('MODEL_MANAGER_HOST', DEFAULT_HOST).strip() or DEFAULT_HOST
    port = coerce_int(os.getenv('MODEL_MANAGER_PORT', DEFAULT_PORT), default=DEFAULT_PORT)
    if not 1 <= port <= 65535:
        port = DEFAULT_PORT

    return {
        'host': host,
        'port': port,
        'debug': parse_env_bool(os.getenv('MODEL_MANAGER_DEBUG'), default=False),
    }


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    """API isteklerinde tutarlı JSON hata cevabı dön."""
    response = exc.get_response()
    if request.path.startswith('/api/'):
        response.data = json.dumps({'error': exc.description or exc.name}, ensure_ascii=False)
        response.content_type = 'application/json; charset=utf-8'
    return response


# ─── Routes ──────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Ana sayfa."""
    ensure_scanned()
    return render_template('index.html')


@app.route('/api/models')
def api_models():
    """Model listesini döndür. Query parametreleri: q, tag, format, sort, fav."""
    group_mode = parse_group_mode(request.args.get('group'))
    db, scanned = get_synced_state(group_mode=group_mode)

    q = request.args.get('q', '').lower().strip()
    tag_filter = request.args.get('tag', '').strip()
    fmt_filter = request.args.get('format', '').strip().lower()
    sort_by = request.args.get('sort', 'name')  # name, size, date
    fav_only = request.args.get('fav', '').strip() == '1'

    results = []
    for mid, mdata in scanned.items():
        # DB'deki kullanıcı verilerini birleştir
        user_data = db['models'][mid]

        item = {**mdata, **user_data, 'id': mid}

        # Filtreler
        if q and q not in item['name'].lower() and q not in item.get('display_name', '').lower():
            # Etiketlerde de ara
            if not any(q in t.lower() for t in item.get('tags', [])):
                continue

        if tag_filter and tag_filter not in item.get('tags', []):
            continue

        if fmt_filter and item.get('format') != fmt_filter:
            continue

        if fav_only and not item.get('favorite'):
            continue

        results.append(item)

    # Sıralama
    if sort_by == 'size':
        results.sort(key=lambda x: x.get('size', 0), reverse=True)
    elif sort_by == 'date':
        results.sort(key=lambda x: x.get('modified', 0), reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x.get('display_name', x.get('name', '')).lower())

    return jsonify({
        'models': results,
        'total': len(results),
    })


@app.route('/api/models/<model_id>/tags', methods=['POST'])
def api_update_tags(model_id):
    """Modelin etiketlerini güncelle."""
    data = parse_json_object()
    tags = sanitize_tags(data.get('tags', []))

    def apply_tags(record):
        record['tags'] = tags
        return {'success': True, 'tags': tags}

    return jsonify(mutate_model_record(model_id, apply_tags))


@app.route('/api/models/<model_id>/favorite', methods=['POST'])
def api_toggle_favorite(model_id):
    """Favori durumunu toggle et."""
    def toggle(record):
        record['favorite'] = not record['favorite']
        return {'success': True, 'favorite': record['favorite']}

    return jsonify(mutate_model_record(model_id, toggle))


@app.route('/api/models/<model_id>/note', methods=['POST'])
def api_update_note(model_id):
    """Modelin notunu güncelle."""
    data = parse_json_object()
    note = str(data.get('note', ''))

    def apply_note(record):
        record['note'] = note
        return {'success': True, 'note': note}

    return jsonify(mutate_model_record(model_id, apply_note))


@app.route('/api/models/<model_id>/printed', methods=['POST'])
def api_toggle_printed(model_id):
    """Yazdırıldı durumunu toggle et."""
    def toggle(record):
        record['printed'] = not record.get('printed', False)
        return {'success': True, 'printed': record['printed']}

    return jsonify(mutate_model_record(model_id, toggle))


@app.route('/api/tags')
def api_tags():
    """Tüm kullanılan etiketleri ve sayılarını döndür."""
    group_mode = parse_group_mode(request.args.get('group'))
    db, scanned = get_synced_state(group_mode=group_mode)
    tag_counts = {}
    for mid in scanned:
        for tag in db['models'][mid].get('tags', []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    # Sıralı döndür
    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    return jsonify({'tags': [{'name': t, 'count': c} for t, c in sorted_tags]})


@app.route('/api/scan', methods=['POST'])
def api_rescan():
    """Klasörü yeniden tara."""
    group_mode = parse_group_mode(request.args.get('group'))
    _, scanned = get_synced_state(refresh=True, group_mode=group_mode)
    return jsonify({'success': True, 'total': len(scanned)})


@app.route('/api/stats')
def api_stats():
    """İstatistikleri döndür."""
    group_mode = parse_group_mode(request.args.get('group'))
    db, scanned = get_synced_state(group_mode=group_mode)

    total = len(scanned)
    favorites = sum(1 for mid in scanned if db['models'][mid].get('favorite'))
    printed = sum(1 for mid in scanned if db['models'][mid].get('printed'))
    formats = {}
    total_size = 0
    for m in scanned.values():
        fmt = m.get('format', 'unknown')
        formats[fmt] = formats.get(fmt, 0) + 1
        total_size += m.get('size', 0)

    return jsonify({
        'total': total,
        'favorites': favorites,
        'printed': printed,
        'formats': formats,
        'total_size': format_size(total_size),
    })


@app.route('/api/file/<path:filepath>')
def api_serve_file(filepath):
    """3D model dosyasını serve et."""
    full_path = resolve_model_file_path(filepath)
    as_attachment = request.args.get('download', '').strip() == '1'
    return send_file(
        str(full_path),
        as_attachment=as_attachment,
        download_name=full_path.name if as_attachment else None,
    )


@app.route('/api/preview/<path:filepath>')
def api_preview_file(filepath):
    """Destekleniyorsa model dosyası için gömülü önizleme döndür."""
    full_path = resolve_model_file_path(filepath)
    if full_path.suffix.lower() != '.3mf':
        abort(404)

    preview = read_3mf_preview(full_path)
    if not preview:
        abort(404)

    preview_name, preview_bytes, mimetype = preview
    return send_file(
        io.BytesIO(preview_bytes),
        mimetype=mimetype,
        download_name=Path(preview_name).name,
        conditional=False,
    )


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_settings = get_run_settings()
    print_startup_banner()
    app.run(**run_settings)
