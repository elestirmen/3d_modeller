"""
3D Model Yöneticisi — Flask Backend
Dağınık 3D model dosyalarını tarayan, kataloglayan ve yöneten web uygulaması.
"""

import os
import json
import hashlib
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, abort
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

# Yapılandırma
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "3d models"
DB_PATH = BASE_DIR / "db.json"

# Desteklenen dosya formatları
SUPPORTED_FORMATS = {'.stl', '.3mf', '.obj', '.gltf', '.glb', '.fbx', '.ply'}

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


def scan_models():
    """3D model klasörünü tara ve tüm modelleri katalogla."""
    models = {}

    if not MODELS_DIR.exists():
        return models

    # Önce klasörleri "proje" olarak grupla
    projects = {}  # klasör yolu -> dosya listesi
    root_files = []  # kök dizindeki tekil dosyalar

    for root, dirs, files in os.walk(MODELS_DIR):
        root_path = Path(root)
        rel_root = root_path.relative_to(MODELS_DIR)

        for f in files:
            file_path = root_path / f
            ext = file_path.suffix.lower()

            if ext not in SUPPORTED_FORMATS:
                continue

            if root_path == MODELS_DIR:
                root_files.append(file_path)
            else:
                # En üst alt klasörü bul (proje klasörü)
                parts = rel_root.parts
                project_dir = MODELS_DIR / parts[0]
                project_key = str(project_dir)

                if project_key not in projects:
                    projects[project_key] = {
                        'name': parts[0],
                        'path': str(project_dir),
                        'files': []
                    }
                projects[project_key]['files'].append(file_path)

    # Kök dizindeki tekil dosyaları model olarak ekle
    for fp in root_files:
        rel_path = str(fp.relative_to(MODELS_DIR))
        model_id = generate_id(rel_path)
        stat = fp.stat()
        name = fp.stem
        # Çift uzantılı dosyaları temizle (örn: "file.stl.stl")
        if name.endswith('.stl') or name.endswith('.3mf'):
            name = Path(name).stem

        models[model_id] = {
            'id': model_id,
            'name': name,
            'display_name': name,
            'type': 'file',
            'format': fp.suffix.lower().lstrip('.'),
            'path': rel_path,
            'abs_path': str(fp),
            'size': stat.st_size,
            'size_display': format_size(stat.st_size),
            'modified': stat.st_mtime,
            'files': [rel_path],
            'file_count': 1,
            'suggested_tags': suggest_tags(name),
        }

    # Proje klasörlerini model olarak ekle
    for pk, proj in projects.items():
        model_id = generate_id(proj['name'])
        total_size = sum(f.stat().st_size for f in proj['files'])
        latest_modified = max(f.stat().st_mtime for f in proj['files'])

        file_list = [str(f.relative_to(MODELS_DIR)) for f in proj['files']]
        # Ana dosyayı bul (en büyük STL veya ilk dosya)
        main_file = max(proj['files'], key=lambda f: f.stat().st_size)
        main_format = main_file.suffix.lower().lstrip('.')

        name = proj['name']
        # Thingiverse tarzı numaraları temizle
        clean_name = name
        for sep in [' - ', ' -']:
            parts = clean_name.rsplit(sep, 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                clean_name = parts[0].strip()

        models[model_id] = {
            'id': model_id,
            'name': name,
            'display_name': clean_name,
            'type': 'project',
            'format': main_format,
            'path': str(Path(proj['path']).relative_to(MODELS_DIR)),
            'abs_path': str(main_file),
            'main_file': str(main_file.relative_to(MODELS_DIR)),
            'size': total_size,
            'size_display': format_size(total_size),
            'modified': latest_modified,
            'files': file_list,
            'file_count': len(file_list),
            'suggested_tags': suggest_tags(name),
        }

    return models


def load_db():
    """Veritabanını yükle, yoksa boş oluştur."""
    if DB_PATH.exists():
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'models': {}, 'custom_tags': [], 'last_scan': None}


def save_db(db):
    """Veritabanını kaydet."""
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def sync_db_with_scan(db, scanned):
    """DB'deki model kayıtlarını güncel tarama ile hizala."""
    current_models = db.get('models', {})
    synced_models = {}

    for mid, mdata in scanned.items():
        synced_models[mid] = normalize_model_record(
            current_models.get(mid),
            mdata.get('suggested_tags', []),
        )

    changed = synced_models != current_models
    db['models'] = synced_models
    return changed


def get_synced_state(persist=False):
    """Tarama sonuçları ile kullanıcı verilerini senkron halde döndür."""
    db = load_db()
    scanned = scan_models()
    changed = sync_db_with_scan(db, scanned)

    if persist and (changed or db.get('last_scan') is None):
        db['last_scan'] = time.time()
        save_db(db)

    return db, scanned


def get_existing_model_or_404(model_id):
    """Model gerçekten mevcutsa DB kaydını döndür, değilse 404 ver."""
    db, scanned = get_synced_state()
    if model_id not in scanned:
        abort(404, description='Model not found')
    return db, scanned, db['models'][model_id]


def ensure_scanned():
    """Eğer henüz taranmamışsa taramayı çalıştır ve DB'ye kaydet."""
    db = load_db()
    if db.get('last_scan') is None:
        db, _ = get_synced_state(persist=True)
    return db


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
    db, scanned = get_synced_state()

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
    db, _, record = get_existing_model_or_404(model_id)
    data = request.get_json(silent=True) or {}
    tags = sanitize_tags(data.get('tags', []))

    record['tags'] = tags
    save_db(db)
    return jsonify({'success': True, 'tags': tags})


@app.route('/api/models/<model_id>/favorite', methods=['POST'])
def api_toggle_favorite(model_id):
    """Favori durumunu toggle et."""
    db, _, record = get_existing_model_or_404(model_id)
    record['favorite'] = not record['favorite']
    save_db(db)
    return jsonify({'success': True, 'favorite': record['favorite']})


@app.route('/api/models/<model_id>/note', methods=['POST'])
def api_update_note(model_id):
    """Modelin notunu güncelle."""
    db, _, record = get_existing_model_or_404(model_id)
    data = request.get_json(silent=True) or {}
    note = str(data.get('note', ''))

    record['note'] = note
    save_db(db)
    return jsonify({'success': True, 'note': note})


@app.route('/api/models/<model_id>/printed', methods=['POST'])
def api_toggle_printed(model_id):
    """Yazdırıldı durumunu toggle et."""
    db, _, record = get_existing_model_or_404(model_id)
    record['printed'] = not record.get('printed', False)
    save_db(db)
    return jsonify({'success': True, 'printed': record['printed']})


@app.route('/api/tags')
def api_tags():
    """Tüm kullanılan etiketleri ve sayılarını döndür."""
    db, scanned = get_synced_state()
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
    _, scanned = get_synced_state(persist=True)
    return jsonify({'success': True, 'total': len(scanned)})


@app.route('/api/stats')
def api_stats():
    """İstatistikleri döndür."""
    db, scanned = get_synced_state()

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
    full_path = MODELS_DIR / filepath
    if not full_path.exists() or not full_path.is_file():
        abort(404)
    # Güvenlik kontrolü
    try:
        full_path.resolve().relative_to(MODELS_DIR.resolve())
    except ValueError:
        abort(403)
    if full_path.suffix.lower() not in SUPPORTED_FORMATS:
        abort(404)
    return send_file(str(full_path))


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n🧊 3D Model Yöneticisi başlatılıyor...")
    print(f"📂 Model klasörü: {MODELS_DIR}")
    print(f"🌐 http://localhost:5000\n")
    app.run(debug=True, port=5000)
