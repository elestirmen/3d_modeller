"""
3D Model Arşivi — Flask uygulaması.

Kütüphane klasörünü tarar, modelleri kategorilere ayırır ve sunucu tarafında
önizleme üretir. Ziyaretçiler arşivi gezer; yönetici girişiyle yükleme,
düzenleme, gizleme ve paylaşım bağlantısı oluşturma yapılır.
"""

import argparse
import getpass
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zipfile
from collections import deque
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import catalog
import categories

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5000
DB_VERSION = 2
# Tarama/sınıflandırma mantığı değiştiğinde artırılır; açılışta katalog yeniden üretilir.
CATALOG_VERSION = 4
RENDER_VERSION = 1
MESH_VERSION = 1
COMPACT_FORMATS = {'3mf', 'obj', 'ply'}
CHUNK_SIZE = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_FILE = 4 * 1024 ** 3
MAX_UPLOAD_TOTAL = 8 * 1024 ** 3
MAX_UPLOAD_FILES = 500
MAX_EXTRACT_BYTES = 8 * 1024 ** 3
UPLOAD_TTL = 24 * 3600
MISSING_TTL = 30 * 24 * 3600
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_FAILURES = 6
LOGIN_MAX_GLOBAL_FAILURES = 40
WATCH_INTERVAL = 45
SHARE_EXPIRY_DAYS = {1, 7, 30, 90, 365}
MIN_PASSWORD_LENGTH = 8
TEXT_FORMATS = {'txt', 'md'}
PREVIEW_FORMATS = catalog.VIEWABLE_FORMATS | {'png', 'jpg', 'jpeg', 'webp', 'gif'}
COMPRESSIBLE_FORMATS = {'stl', 'obj', 'ply', 'gltf', 'fbx', 'txt', 'md', 'gcode', 'step', 'stp', 'scad', 'x_t', 'dxf', 'iges', 'igs'}
WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
DEFAULT_SETTINGS = {
    'site_title': '3D Model Arşivi',
    'site_tagline': 'Kişisel 3D baskı model koleksiyonu',
    'public_browsing': True,
    'public_downloads': True,
    'hide_nsfw': True,
}
# Eski sürümün otomatik ürettiği etiketler; kullanıcı etiketi sayılmaz.
LEGACY_AUTO_TAGS = {
    '🧩 Fidget/Oyuncak', '🧸 Bebek/Oyuncak', '📦 Kutu/Depolama', '🔧 Aksesuar/Tutucu', '🚗 Araç Modeli',
    '⚙️ Mekanizma/Dişli', '🎄 Dekorasyon', '🎵 Müzik', '🖨️ Yazıcı Parçası', '🎪 Park/Oyun Alanı',
    '🔑 Anahtarlık', '📸 Kamera/Lens', '🧩 Puzzle/Bulmaca', '✋ Şaka/Eğlence', '🪑 Mobilya',
    '🔋 Pil/Elektronik', '✏️ Kırtasiye', '👓 Giyilebilir', '🐻 Figür/Heykel', '⭐ Harf/Yazı',
}
PRINT_PROFILE_LABELS = {
    'printer': 'Yazıcı', 'layer_height': 'Katman', 'infill': 'Doluluk', 'material': 'Malzeme',
    'nozzle': 'Nozul', 'supports': 'Destek', 'walls': 'Duvar',
}

log = logging.getLogger('model_archive')
bp = Blueprint('main', __name__)


# ─── Yardımcılar ──────────────────────────────────────────────────────


def now():
    return time.time()


def coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_env_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def clean_text(value, max_len, multiline=False):
    """Kullanıcı metnini kırp, kontrol karakterlerini at."""
    text = str(value or '')
    text = unicodedata.normalize('NFC', text)
    pattern = r'[\x00-\x08\x0b-\x1f\x7f]' if multiline else r'[\x00-\x1f\x7f]'
    text = re.sub(pattern, '', text).strip()
    return text[:max_len]


def safe_filename(name, fallback='dosya', max_len=150):
    """Türkçe karakterleri koruyarak dosya adını güvenli hale getir."""
    name = unicodedata.normalize('NFC', str(name or '')).replace('\\', '/').split('/')[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', '', name).strip().strip('.').strip()
    stem, ext = os.path.splitext(name)
    stem = stem.strip()[:max_len].strip() or fallback
    if stem.upper() in WINDOWS_RESERVED:
        stem += '_'
    ext = re.sub(r'[^A-Za-z0-9.]', '', ext)[:12]
    return stem + ext


def safe_relative_path(value):
    """Klasör yüklemelerinden gelen göreli yolu güvenli parçalara ayır."""
    parts = []
    for part in str(value or '').replace('\\', '/').split('/'):
        part = part.strip()
        if not part or part in {'.', '..'} or catalog.is_ignored(part):
            continue
        parts.append(safe_filename(part, fallback='klasor', max_len=100))
    return parts


def unique_path(path):
    """Var olan bir yolun üzerine yazmamak için ' (2)', ' (3)' ekle."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = (path.name, '') if path.is_dir() else (path.stem, path.suffix)
    counter = 2
    while True:
        candidate = path.with_name(f'{stem} ({counter}){suffix}')
        if not candidate.exists():
            return candidate
        counter += 1


def normalize_rel_path(value):
    return str(value or '').replace('\\', '/').strip().lstrip('/')


def file_url(path, member=None, share=None, download=False):
    params = []
    if member:
        params.append('member=' + quote(member, safe=''))
    if share:
        params.append('s=' + quote(share, safe=''))
    if download:
        params.append('download=1')
    suffix = ('?' + '&'.join(params)) if params else ''
    return '/api/file/' + quote(path, safe='/') + suffix


def with_share(url, share):
    if not share:
        return url
    return url + ('&' if '?' in url else '?') + 's=' + quote(share, safe='')


def _title_key(value):
    return ' '.join(categories.tokenize(value))


def format_dims(size_mm):
    """[28.1, 48.2, 48.2] → '28,1 × 48,2 × 48,2 mm' (Türkçe ondalık)."""
    try:
        parts = (f'{float(value):.1f}'.rstrip('0').rstrip('.').replace('.', ',') for value in size_mm)
        return ' × '.join(parts) + ' mm'
    except (TypeError, ValueError):
        return ''


# ─── Veritabanı şeması ────────────────────────────────────────────────


def default_user_record():
    return {
        'title': None, 'category': None, 'tags': None, 'description': None, 'note': '',
        'favorite': False, 'printed': False, 'hidden': False, 'nsfw': None, 'cover': None,
        'author': None, 'source_url': None, 'license': None,
        'added_at': None, 'uploaded_at': None, 'missing_since': None,
    }


def normalize_user_record(record):
    normalized = default_user_record()
    if not isinstance(record, dict):
        return normalized
    for key in ('title', 'description', 'author', 'source_url', 'license', 'cover'):
        value = record.get(key)
        normalized[key] = str(value) if isinstance(value, str) and value.strip() else None
    category = record.get('category')
    normalized['category'] = category if category in categories.CATEGORY_KEYS else None
    tags = record.get('tags')
    if isinstance(tags, list):
        normalized['tags'] = sanitize_tags(tags)
    normalized['note'] = str(record.get('note') or '')[:4000]
    for key in ('favorite', 'printed', 'hidden'):
        normalized[key] = bool(record.get(key, False))
    nsfw = record.get('nsfw')
    normalized['nsfw'] = nsfw if isinstance(nsfw, bool) else None
    for key in ('added_at', 'uploaded_at', 'missing_since'):
        value = record.get(key)
        normalized[key] = float(value) if isinstance(value, (int, float)) else None
    return normalized


def migrate_v1_record(record):
    """Eski (v1) kullanıcı kaydından korunmaya değer alanları taşı."""
    if not isinstance(record, dict):
        return None
    migrated = default_user_record()
    migrated['favorite'] = bool(record.get('favorite'))
    migrated['printed'] = bool(record.get('printed'))
    migrated['note'] = str(record.get('note') or '')[:4000]
    tags = [tag for tag in record.get('tags') or [] if isinstance(tag, str) and tag not in LEGACY_AUTO_TAGS]
    if tags:
        migrated['tags'] = sanitize_tags(tags)
    if migrated['favorite'] or migrated['printed'] or migrated['note'] or migrated['tags']:
        return migrated
    return None


def sanitize_tags(tags):
    cleaned = []
    seen = set()
    for raw in tags or []:
        if not isinstance(raw, str):
            continue
        tag = clean_text(raw, 40)
        key = categories.fold(tag)
        if not tag or key in seen:
            continue
        cleaned.append(tag)
        seen.add(key)
        if len(cleaned) >= 20:
            break
    return cleaned


def normalize_share(share):
    if not isinstance(share, dict) or not isinstance(share.get('model_id'), str):
        return None
    expires = share.get('expires_at')
    return {
        'model_id': share['model_id'],
        'created_at': float(share.get('created_at') or now()),
        'expires_at': float(expires) if isinstance(expires, (int, float)) else None,
        'allow_download': bool(share.get('allow_download', True)),
        'note': str(share.get('note') or '')[:120],
        'views': coerce_int(share.get('views'), 0),
        'last_viewed_at': share.get('last_viewed_at') if isinstance(share.get('last_viewed_at'), (int, float)) else None,
    }


def empty_db():
    return {
        'version': DB_VERSION,
        'settings': dict(DEFAULT_SETTINGS),
        'models': {},
        'catalog': {},
        'derived': {},
        'shares': {},
        'last_scan': None,
        'signature': '',
        'catalog_version': 0,
    }


def normalize_db(raw):
    db = empty_db()
    if not isinstance(raw, dict):
        return db, False

    if raw.get('version') != DB_VERSION:
        for model_id, record in (raw.get('models') or {}).items():
            if ':' in str(model_id):
                continue
            migrated = migrate_v1_record(record)
            if migrated:
                db['models'][str(model_id)] = migrated
        return db, True

    settings = raw.get('settings') if isinstance(raw.get('settings'), dict) else {}
    if settings.get('admin_password_hash'):
        db['_legacy_admin'] = {
            'password_hash': str(settings['admin_password_hash']),
            'session_epoch': coerce_int(settings.get('session_epoch'), 1),
        }
    for key, default in DEFAULT_SETTINGS.items():
        value = settings.get(key, default)
        db['settings'][key] = value if isinstance(value, type(default)) else default
    for model_id, record in (raw.get('models') or {}).items():
        db['models'][str(model_id)] = normalize_user_record(record)
    if isinstance(raw.get('catalog'), dict):
        db['catalog'] = {str(key): value for key, value in raw['catalog'].items() if isinstance(value, dict)}
    if isinstance(raw.get('derived'), dict):
        db['derived'] = {str(key): value for key, value in raw['derived'].items() if isinstance(value, dict)}
    for token, share in (raw.get('shares') or {}).items():
        normalized = normalize_share(share)
        if normalized:
            db['shares'][str(token)] = normalized
    if isinstance(raw.get('last_scan'), (int, float)):
        db['last_scan'] = float(raw['last_scan'])
    db['signature'] = str(raw.get('signature') or '')
    db['catalog_version'] = coerce_int(raw.get('catalog_version'), 0)
    return db, False


# ─── Kütüphane ────────────────────────────────────────────────────────


class Library:
    """Katalog, kullanıcı verisi, küçük resim kuyruğu ve yüklemeleri yöneten nesne."""

    def __init__(self, models_dir, data_dir):
        self.models_dir = Path(models_dir)
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / 'db.json'
        self.last_good_path = self.data_dir / 'db.last-good.json'
        self._last_good_at = 0.0
        self.thumbs_dir = self.data_dir / 'thumbnails'
        self.uploads_dir = self.data_dir / '.uploads'
        self.trash_dir = self.data_dir / '.trash'
        self.admin_path = self.data_dir / '.admin.json'
        self.server_lock_path = self.data_dir / '.server.lock'
        self._admin = None
        self._admin_mtime = None
        self._server_lock = None
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self._db = None
        self._db_mtime = None
        self._mtime_checked = 0.0
        self._index = {}
        self._thumb_queue = deque()
        self._thumb_pending = set()
        self._thumb_cv = threading.Condition()
        self._thumb_active = None
        self._uploads = {}
        self._upload_locks = {}
        self._login_failures = {}
        self._global_failures = deque()
        self._stop = threading.Event()
        self._threads = []
        self._mesh_locks = {}
        self._mesh_slots = threading.BoundedSemaphore(2)
        self._card_lock = threading.Lock()
        self._dirty_since = None

    # ── Kalıcılık ──

    @property
    def db(self):
        with self.lock:
            stamp = time.monotonic()
            if self._db is not None and stamp - self._mtime_checked < 1.0:
                return self._db
            self._mtime_checked = stamp
            mtime = self._current_mtime()
            if self._db is None or (mtime is not None and mtime != self._db_mtime):
                self._db = self._read_db()
                self._db_mtime = self._current_mtime()
                self._rebuild_index()
            return self._db

    def _current_mtime(self):
        try:
            return self.db_path.stat().st_mtime_ns
        except OSError:
            return None

    def _read_db(self):
        if not self.db_path.exists():
            return empty_db()
        try:
            raw = json.loads(self.db_path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('veritabanı bir JSON nesnesi değil')
        except (OSError, ValueError) as exc:
            if self._db is not None:
                # Çalışırken dosya bozulduysa bellekteki sağlam kopyayla devam et; ilk kayıt dosyayı onarır.
                log.error('Veritabanı dosyası okunamadı, bellekteki kopya kullanılıyor: %s', exc)
                return self._db
            return self._recover_db(exc)

        db, migrated = normalize_db(raw)
        legacy_admin = db.pop('_legacy_admin', None)
        if legacy_admin and not self.admin_path.exists():
            self._write_admin(legacy_admin)
            migrated = True
        if migrated and raw.get('version') != DB_VERSION:
            backup = self.db_path.with_name(f'db.v1-backup-{time.strftime("%Y%m%d-%H%M%S")}.json')
            try:
                shutil.copy2(self.db_path, backup)
                log.info('Eski veritabanı v%s şemasına taşındı, yedek: %s', DB_VERSION, backup)
            except OSError:
                pass
        if migrated:
            self._db = db
            self._write(db)
        return db

    def _recover_db(self, error):
        """Bozuk veritabanını yedekle; son sağlam kopyaya dön, o da yoksa arşivi özel modda aç."""
        backup = self.db_path.with_name(f'db.corrupt-{time.strftime("%Y%m%d-%H%M%S")}.json')
        try:
            self.db_path.replace(backup)
        except OSError:
            backup = None
        try:
            restored, _ = normalize_db(json.loads(self.last_good_path.read_text(encoding='utf-8')))
            restored.pop('_legacy_admin', None)
            log.warning('Veritabanı bozuktu (yedek: %s); son sağlam kopyaya dönüldü: %s', backup, error)
            self._write(restored)
            return restored
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        db = empty_db()
        db['settings']['public_browsing'] = False
        log.warning('Veritabanı bozuktu (yedek: %s) ve sağlam kopya yok; güvenlik için arşiv özel modda açıldı: %s', backup, error)
        self._write(db)
        return db

    def _write(self, db):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix='.db-', suffix='.json', dir=self.data_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(db, handle, ensure_ascii=False, separators=(',', ':'))
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.db_path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        self._db_mtime = self._current_mtime()
        if time.monotonic() - self._last_good_at > 600 or not self.last_good_path.exists():
            self._last_good_at = time.monotonic()
            try:
                fd, copy_name = tempfile.mkstemp(prefix='.db-good-', suffix='.json', dir=self.data_dir)
                os.close(fd)
                shutil.copyfile(self.db_path, copy_name)
                os.chmod(copy_name, 0o600)
                os.replace(copy_name, self.last_good_path)
            except OSError:
                log.warning('Veritabanının sağlam kopyası yazılamadı')

    def save(self):
        with self.lock:
            self._write(self._db if self._db is not None else self.db)
            self._dirty_since = None

    def mark_dirty(self):
        """Sık güncellenen alanlar için (küçük resim durumu) gecikmeli kaydet."""
        with self.lock:
            if self._dirty_since is None:
                self._dirty_since = now()
            elif now() - self._dirty_since > 3:
                self.save()

    @property
    def settings(self):
        return self.db['settings']

    # ── Tarama ──

    def ensure_scanned(self):
        if self.db.get('last_scan') is None:
            self.scan()

    def scan(self):
        """Klasörü tara, kullanıcı verisini eşleştir, küçük resim işlerini kuyruğa al."""
        with self.scan_lock:
            fresh = catalog.scan_library(self.models_dir)
            signature = catalog.library_signature(self.models_dir)
            with self.lock:
                db = self.db
                initial = db.get('last_scan') is None
                stamp = now()
                previous = set(db['catalog'])
                for model_id, record in fresh.items():
                    user = db['models'].get(model_id) or default_user_record()
                    if user.get('added_at') is None:
                        user['added_at'] = record['file_date'] if initial else stamp
                    user['missing_since'] = None
                    db['models'][model_id] = user
                for model_id, user in list(db['models'].items()):
                    if model_id in fresh:
                        continue
                    if user.get('missing_since') is None:
                        user['missing_since'] = stamp
                    elif stamp - user['missing_since'] > MISSING_TTL:
                        del db['models'][model_id]
                        db['derived'].pop(model_id, None)
                db['catalog'] = fresh
                db['last_scan'] = stamp
                db['signature'] = signature
                db['catalog_version'] = CATALOG_VERSION
                self._rebuild_index()
                self.save()
                added = sorted(set(fresh) - previous)
                removed = sorted(previous - set(fresh))
            self.queue_derived()
            return {'total': len(fresh), 'added': added, 'removed': removed}

    def _rebuild_index(self):
        index = {}
        for model_id, record in (self._db or {}).get('catalog', {}).items():
            for entry in record.get('files', []) + record.get('assets', []):
                index.setdefault(entry['path'], set()).add(model_id)
        self._index = index

    def models_for_path(self, rel_path):
        with self.lock:
            self.db  # noqa: B018 - önbelleği tazele
            return set(self._index.get(rel_path, set()))

    # ── Etkin değerler ve görünürlük ──

    def record(self, model_id):
        return self.db['catalog'].get(model_id)

    def user(self, model_id):
        return self.db['models'].get(model_id) or default_user_record()

    def effective_nsfw(self, model_id):
        user = self.user(model_id)
        if user.get('nsfw') is not None:
            return bool(user['nsfw'])
        return bool((self.record(model_id) or {}).get('auto_nsfw'))

    def is_public(self, model_id):
        settings = self.settings
        if not settings['public_browsing'] or model_id not in self.db['catalog']:
            return False
        if self.user(model_id).get('hidden'):
            return False
        if settings['hide_nsfw'] and self.effective_nsfw(model_id):
            return False
        return True

    def can_view(self, model_id, viewer):
        if model_id not in self.db['catalog']:
            return False
        if viewer.admin:
            return True
        if viewer.share and viewer.share['model_id'] == model_id:
            return True
        return self.is_public(model_id)

    def can_download(self, model_id, viewer):
        if viewer.admin:
            return True
        if viewer.share and viewer.share['model_id'] == model_id:
            return viewer.share['allow_download']
        return self.is_public(model_id) and self.settings['public_downloads']

    def thumb_source(self, model_id):
        record = self.record(model_id)
        if not record:
            return None
        cover = self.user(model_id).get('cover')
        if cover:
            entry = next((item for item in record['assets'] if item['kind'] == 'image' and item['path'] == cover and not item.get('member')), None)
            if entry:
                return {'kind': 'image', 'path': entry['path'], 'member': None}
        return record.get('thumb_source')

    def _source_key(self, source):
        if not source:
            return None
        try:
            stat = (self.models_dir / source['path']).stat()
        except OSError:
            return None
        raw = json.dumps([RENDER_VERSION, source, stat.st_size, stat.st_mtime_ns], sort_keys=True)
        return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]

    def compact_path(self, rel_path, member=None):
        """Tarayıcı için dönüştürülmüş mesh dosyasının önbellek yolu (kaynak değişince değişir)."""
        try:
            stat = (self.models_dir / rel_path).stat()
        except OSError:
            return None
        raw = f'{MESH_VERSION}|{rel_path}|{member or ""}|{stat.st_size}|{stat.st_mtime_ns}'
        return self.thumbs_dir / 'mesh' / (hashlib.md5(raw.encode('utf-8')).hexdigest()[:20] + '.m3d')

    def compact_mesh(self, rel_path, member=None):
        """Önbellekte yoksa mesh'i ayrı süreçte dönüştür; dosya yolunu (veya None) döndür."""
        target = self.compact_path(rel_path, member)
        if target is None:
            return None
        if target.exists():
            return target
        with self.lock:
            key_lock = self._mesh_locks.setdefault(str(target), threading.Lock())
        with key_lock, self._mesh_slots:
            if target.exists():
                return target
            command = [sys.executable, '-m', 'meshes', 'compact', str(self.models_dir / rel_path), str(target)]
            if member:
                command.append(member)
            env = dict(os.environ, PYTHONPATH=str(BASE_DIR) + os.pathsep + os.environ.get('PYTHONPATH', ''))
            try:
                subprocess.run(command, cwd=str(BASE_DIR), env=env, capture_output=True, timeout=600, check=False)
            except subprocess.TimeoutExpired:
                return None
            return target if target.exists() else None

    def thumb_info(self, model_id):
        """(url_or_None, pending) döndür."""
        derived = self.db['derived'].get(model_id) or {}
        wanted = self._source_key(self.thumb_source(model_id))
        has_file = bool(derived.get('thumb')) and (self.thumbs_dir / derived['thumb']).exists()
        url = f"/api/thumb/{model_id}?v={derived.get('thumb_key', '')[:10]}" if has_file else None
        pending = wanted is not None and derived.get('thumb_key') != wanted and not (
            derived.get('thumb_failed_key') == wanted
        )
        return url, pending or model_id in self._thumb_pending

    def category_label(self, key):
        return categories.CATEGORY_LABELS.get(key, categories.CATEGORY_LABELS[categories.OTHER])

    def effective(self, model_id):
        record = self.record(model_id)
        user = self.user(model_id)
        category = user['category'] or record['auto_category']
        tags = user['tags'] if user['tags'] is not None else list(record.get('auto_tags') or [])
        return {
            'title': user['title'] or record['title'],
            'category': category,
            'tags': tags,
            'author': user['author'] if user['author'] is not None else record.get('author', ''),
            'source_url': user['source_url'] if user['source_url'] is not None else record.get('source_url', ''),
            'license': user['license'] if user['license'] is not None else record.get('license', ''),
            'description': user['description'] if user['description'] is not None else record.get('description', ''),
            'nsfw': self.effective_nsfw(model_id),
        }

    def card(self, model_id, viewer):
        record = self.record(model_id)
        user = self.user(model_id)
        values = self.effective(model_id)
        thumb, pending = self.thumb_info(model_id)
        derived = self.db['derived'].get(model_id) or {}
        stats = derived.get('stats') or {}
        assets = record.get('assets', [])
        flags = {
            'readme': bool(record.get('readme')),
            'license': bool(values['license']),
            'cad': any(entry['kind'] == 'cad' for entry in assets),
            'gcode': any(entry['kind'] == 'gcode' for entry in assets),
            'images': any(entry['kind'] == 'image' for entry in assets),
            'source': bool(values['source_url']),
            'multipart': record['file_count'] > 1,
        }
        card = {
            'id': model_id,
            'title': values['title'],
            'category': values['category'],
            'tags': values['tags'],
            'kind': record['kind'],
            'formats': record['formats'],
            'mainFormat': record['main']['format'],
            'fileCount': record['file_count'],
            'size': record['size'],
            'sizeLabel': catalog.format_size(record['size']),
            'author': values['author'],
            'platform': record.get('source_platform'),
            'collection': record.get('collection'),
            'collectionId': record.get('collection_id'),
            'featured': user['favorite'],
            'printed': user['printed'],
            'nsfw': values['nsfw'],
            'added': user.get('added_at') or record.get('file_date'),
            'modified': record['modified'],
            'thumb': with_share(thumb, viewer.share_token) if thumb else None,
            'thumbPending': pending,
            'dims': format_dims(stats['size_mm']) if stats.get('size_mm') else '',
            'flags': flags,
            'search': ' '.join(filter(None, [
                record.get('search', ''),
                categories.fold(values['title']),
                categories.fold(self.category_label(values['category'])),
                categories.fold(' '.join(values['tags'])),
                categories.fold(values['author'] or ''),
            ])),
        }
        if viewer.admin:
            card['hidden'] = user['hidden']
            card['public'] = self.is_public(model_id)
        return card

    def detail(self, model_id, viewer):
        record = self.record(model_id)
        user = self.user(model_id)
        values = self.effective(model_id)
        derived = self.db['derived'].get(model_id) or {}
        share = viewer.share_token
        can_download = self.can_download(model_id, viewer)

        def entry_payload(entry):
            previewable = entry['format'] in PREVIEW_FORMATS
            item = {
                'name': entry['name'],
                'path': entry['path'],
                'member': entry.get('member'),
                'size': entry['size'],
                'sizeLabel': catalog.format_size(entry['size']),
                'format': entry['format'],
                'kind': entry['kind'],
                'url': file_url(entry['path'], entry.get('member'), share) if previewable or can_download else None,
                'viewable': entry['format'] in catalog.VIEWABLE_FORMATS,
            }
            if entry['format'] in COMPACT_FORMATS:
                item['meshUrl'] = with_share(file_url(entry['path'], entry.get('member')).replace('/api/file/', '/api/mesh/', 1), share)
            if can_download:
                item['downloadUrl'] = file_url(entry['path'], entry.get('member'), share, download=True)
            return item

        images = [entry for entry in record['assets'] if entry['kind'] == 'image']
        main = record['main']
        main_entry = next((entry for entry in record['files'] if entry['path'] == main['path'] and entry.get('member') == main.get('member')), record['files'][0])
        profile = [
            {'key': key, 'label': PRINT_PROFILE_LABELS.get(key, key), 'value': value}
            for key, value in (record.get('print_profile') or {}).items()
            if key in PRINT_PROFILE_LABELS and value
        ]
        stats = derived.get('stats') or {}
        detail = self.card(model_id, viewer)
        detail.update({
            'path': record['path'],
            'rawName': record['raw_name'],
            'originalTitle': record['original_title'] if record.get('original_title') and _title_key(record['original_title']) != _title_key(values['title']) else '',
            'description': values['description'],
            'license': values['license'],
            'licenseText': record.get('license_text', ''),
            'sourceUrl': values['source_url'],
            'sourceId': record.get('source_id'),
            'slicer': record.get('slicer'),
            'printProfile': profile,
            'stats': {
                'dims': format_dims(stats['size_mm']) if stats.get('size_mm') else '',
                'sizeMm': stats.get('size_mm'),
                'triangles': stats.get('triangles'),
                'volumeCm3': stats.get('volume_cm3'),
            } if stats else None,
            'files': [entry_payload(entry) for entry in record['files']],
            'assets': [entry_payload(entry) for entry in record['assets']],
            'images': [entry_payload(entry) for entry in images[:24]],
            'main': entry_payload(main_entry),
            'mainPreview': with_share(f'/api/preview/{quote(main["path"], safe="/")}', share) if main['format'] == '3mf' and not main.get('member') else None,
            'canDownload': can_download,
            'downloadAllUrl': with_share(f'/api/models/{model_id}/download', share) if can_download else None,
            'categoryLabel': self.category_label(values['category']),
        })
        if viewer.admin:
            detail.update({
                'note': user['note'],
                'hidden': user['hidden'],
                'cover': user['cover'],
                'overrides': {
                    'title': user['title'] is not None,
                    'category': user['category'] is not None,
                    'tags': user['tags'] is not None,
                    'description': user['description'] is not None,
                    'author': user['author'] is not None,
                    'source_url': user['source_url'] is not None,
                    'license': user['license'] is not None,
                    'nsfw': user['nsfw'] is not None,
                },
                'auto': {
                    'title': record['title'],
                    'category': record['auto_category'],
                    'tags': record.get('auto_tags') or [],
                    'nsfw': bool(record.get('auto_nsfw')),
                    'scores': record.get('category_scores') or {},
                },
                'shares': self.shares_for(model_id),
                'thumbError': derived.get('thumb_error'),
            })
        return detail

    def library_payload(self, viewer):
        with self.lock:
            ids = [model_id for model_id in self.db['catalog'] if self.can_view(model_id, viewer)]
            cards = [self.card(model_id, viewer) for model_id in ids]
            total_size = sum(card['size'] for card in cards)
            return {
                'models': cards,
                'stats': {
                    'total': len(cards),
                    'totalSize': catalog.format_size(total_size),
                    'featured': sum(1 for card in cards if card['featured']),
                    'printed': sum(1 for card in cards if card['printed']),
                    'files': sum(card['fileCount'] for card in cards),
                },
                'pending': sum(1 for card in cards if card['thumbPending']),
                'lastScan': self.db.get('last_scan'),
            }

    # ── Güncelleme ──

    def update_model(self, model_id, payload):
        with self.lock:
            if model_id not in self.db['catalog']:
                abort(404, description='Model bulunamadı')
            record = self.db['catalog'][model_id]
            user = self.db['models'].setdefault(model_id, default_user_record())
            text_fields = {'title': 160, 'author': 120, 'license': 120, 'source_url': 500}
            for key, limit in text_fields.items():
                if key in payload:
                    value = payload[key]
                    if value is None:
                        user[key] = None
                        continue
                    text = clean_text(value, limit)
                    if key == 'source_url' and text and not re.match(r'^https?://', text, re.IGNORECASE):
                        abort(400, description='Kaynak bağlantısı http:// veya https:// ile başlamalı')
                    if key == 'title':
                        user[key] = text if text and text != record['title'] else None
                    else:
                        user[key] = text
            if 'description' in payload:
                value = payload['description']
                user['description'] = None if value is None else clean_text(value, 6000, multiline=True)
            if 'note' in payload:
                user['note'] = clean_text(payload['note'], 4000, multiline=True)
            if 'category' in payload:
                value = payload['category']
                if value is not None and value not in categories.CATEGORY_KEYS:
                    abort(400, description='Geçersiz kategori')
                user['category'] = None if value is None or value == record['auto_category'] else value
            if 'tags' in payload:
                value = payload['tags']
                if value is None:
                    user['tags'] = None
                elif isinstance(value, list):
                    user['tags'] = sanitize_tags(value)
                else:
                    abort(400, description='Etiketler liste olmalı')
            for key in ('favorite', 'printed', 'hidden'):
                if key in payload:
                    user[key] = bool(payload[key])
            if 'nsfw' in payload:
                value = payload['nsfw']
                user['nsfw'] = None if value is None or bool(value) == bool(record.get('auto_nsfw')) else bool(value)
            if 'cover' in payload:
                value = payload['cover']
                if value is None:
                    user['cover'] = None
                else:
                    valid = {entry['path'] for entry in record['assets'] if entry['kind'] == 'image' and not entry.get('member')}
                    if value not in valid:
                        abort(400, description='Kapak görseli bu modele ait değil')
                    user['cover'] = value
            self.save()
        self.queue_derived([model_id])

    def trash_model(self, model_id):
        """Modeli silmek yerine veri klasöründeki çöp kutusuna taşı."""
        with self.scan_lock:
            with self.lock:
                record = self.record(model_id)
                if not record:
                    abort(404, description='Model bulunamadı')
                root = self.models_dir / record['path']
                destination = self.trash_dir / f'{time.strftime("%Y%m%d-%H%M%S")}-{model_id}'
                destination.mkdir(parents=True, exist_ok=True)
                own_paths = {entry['path'] for entry in record['files'] + record['assets'] if not entry.get('member')}
                shared = {path for path in own_paths if self._index.get(path, set()) - {model_id}}
                nested = [other for other_id, other in self.db['catalog'].items()
                          if other_id != model_id and other['path'].startswith(record['path'] + '/')]
                if record['kind'] == 'folder' and not nested:
                    targets = [root] + [self.models_dir / path for path in own_paths - shared
                                        if not path.startswith(record['path'] + '/')]
                elif record['kind'] == 'folder':
                    # İçinde ayrı modeller var: yalnızca bu modelin kendi dosyalarını taşı.
                    targets = []
                    for path in sorted(own_paths - shared):
                        source = self.models_dir / path
                        if not source.exists():
                            continue
                        relative = Path(path).relative_to(record['path']) if path.startswith(record['path'] + '/') else Path(Path(path).name)
                        target = destination / root.name / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source), str(unique_path(target)))
                    for folder in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
                        if not any(folder.iterdir()):
                            folder.rmdir()
                else:
                    targets = [self.models_dir / path for path in own_paths - shared] or [root]
                for target in targets:
                    if target.exists():
                        shutil.move(str(target), str(unique_path(destination / target.name)))
                parent = root if root.is_dir() else root.parent
                while parent != self.models_dir and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                self.db['models'].pop(model_id, None)
                self._remove_derived_files(model_id)
                self.db['derived'].pop(model_id, None)
                for token in [token for token, share in self.db['shares'].items() if share['model_id'] == model_id]:
                    del self.db['shares'][token]
                self.save()
        self.scan()
        return str(destination)

    # ── Küçük resimler ──

    def queue_derived(self, model_ids=None, force=False):
        with self.lock:
            ids = list(model_ids) if model_ids is not None else list(self.db['catalog'])
            jobs = []
            for model_id in ids:
                record = self.record(model_id)
                if not record:
                    continue
                derived = self.db['derived'].get(model_id) or {}
                thumb_key = self._source_key(self.thumb_source(model_id))
                stats_key = self._source_key(record.get('stats_source'))
                thumb_needed = thumb_key and derived.get('thumb_key') != thumb_key and (force or derived.get('thumb_failed_key') != thumb_key)
                stats_needed = stats_key and derived.get('stats_key') != stats_key and (force or derived.get('stats_failed_key') != stats_key)
                compact_needed = stats_key and self._compact_missing(record.get('stats_source')) and (force or derived.get('compact_failed_key') != stats_key)
                if thumb_needed or stats_needed or compact_needed:
                    jobs.append(model_id)
        with self._thumb_cv:
            for model_id in jobs:
                if model_id not in self._thumb_pending:
                    self._thumb_pending.add(model_id)
                    self._thumb_queue.append(model_id)
            self._thumb_cv.notify_all()
        return len(jobs)

    def _compact_missing(self, source):
        if not source or Path(source.get('member') or source['path']).suffix.lower().lstrip('.') not in COMPACT_FORMATS:
            return False
        target = self.compact_path(source['path'], source.get('member'))
        return target is not None and not target.exists()

    def _remove_derived_files(self, model_id, keep=()):
        for path in self.thumbs_dir.glob(f'{model_id}-*'):
            if path.name not in keep:
                try:
                    path.unlink()
                except OSError:
                    pass

    def _build_job(self, model_id):
        with self.lock:
            record = self.record(model_id)
            if not record:
                return None
            derived = self.db['derived'].get(model_id) or {}
            thumb_source = self.thumb_source(model_id)
            thumb_key = self._source_key(thumb_source)
            stats_source = record.get('stats_source')
            stats_key = self._source_key(stats_source)
            job = {'model_id': model_id, 'thumb_key': thumb_key, 'stats_key': stats_key}
            if thumb_key and derived.get('thumb_key') != thumb_key:
                source = dict(thumb_source)
                source['path'] = str(self.models_dir / source['path'])
                job['thumb'] = source
                job['output'] = str(self.thumbs_dir / f'{model_id}-{thumb_key[:10]}.webp')
                job['og_output'] = str(self.thumbs_dir / f'{model_id}-{thumb_key[:10]}.jpg')
            compact_needed = stats_key and self._compact_missing(stats_source) and derived.get('compact_failed_key') != stats_key
            if stats_key and (derived.get('stats_key') != stats_key or compact_needed):
                source = dict(stats_source)
                if compact_needed:
                    job['compact_output'] = str(self.compact_path(source['path'], source.get('member')))
                source['path'] = str(self.models_dir / source['path'])
                job['stats'] = source
            if 'thumb' not in job and 'stats' not in job:
                return None
            return job

    def run_job(self, job):
        """Render işini ayrı bir Python sürecinde çalıştır (GIL ve bellek izolasyonu)."""
        payload = {key: job[key] for key in ('thumb', 'stats', 'output', 'og_output', 'compact_output') if key in job}
        env = dict(os.environ, PYTHONPATH=str(BASE_DIR) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        try:
            proc = subprocess.run(
                [sys.executable, '-m', 'meshes', 'job'],
                input=json.dumps(payload), capture_output=True, text=True, timeout=900,
                cwd=str(BASE_DIR), env=env,
            )
        except subprocess.TimeoutExpired:
            return {'ok': False, 'thumb': False, 'stats': None, 'errors': ['zaman aşımı']}
        lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
        if proc.returncode != 0 or not lines:
            message = (proc.stderr or '').strip().splitlines()[-1:] or [f'çıkış kodu {proc.returncode}']
            return {'ok': False, 'thumb': False, 'stats': None, 'errors': message}
        try:
            return json.loads(lines[-1])
        except ValueError:
            return {'ok': False, 'thumb': False, 'stats': None, 'errors': ['geçersiz çıktı']}

    def process_job(self, model_id):
        job = self._build_job(model_id)
        if job is None:
            return None
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self._thumb_active = model_id
        try:
            result = self.run_job(job)
        finally:
            self._thumb_active = None
        with self.lock:
            derived = self.db['derived'].setdefault(model_id, {})
            if 'thumb' in job:
                if result.get('thumb'):
                    name = Path(job['output']).name
                    derived.update({'thumb': name, 'thumb_key': job['thumb_key'], 'thumb_error': None})
                    derived['og'] = Path(job['og_output']).name if result.get('og') else None
                    keep = {name}
                    if derived['og']:
                        keep.add(derived['og'])
                    self._remove_derived_files(model_id, keep=keep)
                    derived.pop('thumb_failed_key', None)
                else:
                    derived['thumb_failed_key'] = job['thumb_key']
                    derived['thumb_error'] = '; '.join(result.get('errors') or [])[:300]
            if job.get('compact_output') and not result.get('compact'):
                derived['compact_failed_key'] = job['stats_key']
            if 'stats' in job:
                if result.get('stats'):
                    derived.update({'stats': result['stats'], 'stats_key': job['stats_key']})
                    derived.pop('stats_failed_key', None)
                else:
                    derived['stats_failed_key'] = job['stats_key']
            self.mark_dirty()
        return result

    def _thumb_loop(self):
        while not self._stop.is_set():
            with self._thumb_cv:
                while not self._thumb_queue and not self._stop.is_set():
                    if self._dirty_since is not None:
                        break
                    self._thumb_cv.wait(timeout=5)
                model_id = self._thumb_queue.popleft() if self._thumb_queue else None
            if model_id is None:
                if self._dirty_since is not None:
                    self.save()
                continue
            try:
                self.process_job(model_id)
            except Exception:  # noqa: BLE001
                log.exception('Küçük resim üretilemedi: %s', model_id)
            finally:
                with self._thumb_cv:
                    self._thumb_pending.discard(model_id)
                    if not self._thumb_queue:
                        self.save()
            time.sleep(0.1)

    def run_pending_jobs(self):
        """Kuyruktaki tüm işleri bu thread'de bitir (CLI ve testler için)."""
        while True:
            with self._thumb_cv:
                model_id = self._thumb_queue.popleft() if self._thumb_queue else None
            if model_id is None:
                break
            try:
                self.process_job(model_id)
            finally:
                self._thumb_pending.discard(model_id)
        self.save()

    def status(self):
        with self.lock:
            derived = self.db['derived']
            catalog_ids = list(self.db['catalog'])
            with_thumb = sum(1 for model_id in catalog_ids if (derived.get(model_id) or {}).get('thumb'))
            failed = sum(1 for model_id in catalog_ids if (derived.get(model_id) or {}).get('thumb_failed_key'))
            try:
                usage = shutil.disk_usage(self.models_dir)
                disk = {'free': catalog.format_size(usage.free), 'total': catalog.format_size(usage.total)}
            except OSError:
                disk = None
            return {
                'models': len(catalog_ids),
                'thumbnails': {'done': with_thumb, 'failed': failed, 'queued': len(self._thumb_pending), 'active': self._thumb_active},
                'lastScan': self.db.get('last_scan'),
                'disk': disk,
                'shares': len(self.db['shares']),
            }

    # ── Arka plan ──

    def acquire_server_lock(self):
        """Veritabanına yazan tek süreç olmak için dosya kilidi al (başarısızsa False)."""
        if self._server_lock is not None:
            return True
        try:
            import fcntl
        except ImportError:
            return True
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.server_lock_path, 'a+')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._server_lock = handle
        return True

    def start(self):
        if self._threads:
            return
        if not self.acquire_server_lock():
            log.warning('Başka bir süreç kütüphaneyi yönetiyor; arka plan işçileri başlatılmadı')
            return
        for target, name in ((self._thumb_loop, 'thumbnails'), (self._watch_loop, 'watcher')):
            thread = threading.Thread(target=target, name=f'library-{name}', daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self._stop.set()
        with self._thumb_cv:
            self._thumb_cv.notify_all()

    def _watch_loop(self):
        try:
            self.cleanup_uploads(max_age=UPLOAD_TTL)
            stale = (
                self.db.get('last_scan') is None
                or self.db.get('catalog_version') != CATALOG_VERSION
                or catalog.library_signature(self.models_dir) != self.db.get('signature')
            )
            if stale:
                self.scan()
            else:
                self.queue_derived()
        except Exception:  # noqa: BLE001
            log.exception('İlk tarama başarısız')
        while not self._stop.wait(WATCH_INTERVAL):
            try:
                if catalog.library_signature(self.models_dir) != self.db.get('signature'):
                    log.info('Kütüphanede değişiklik algılandı, yeniden taranıyor')
                    self.scan()
                self.cleanup_uploads(max_age=UPLOAD_TTL)
            except Exception:  # noqa: BLE001
                log.exception('Otomatik tarama başarısız')

    # ── Yüklemeler ──

    def create_upload(self, files):
        if not isinstance(files, list) or not files:
            abort(400, description='Yüklenecek dosya yok')
        if len(files) > MAX_UPLOAD_FILES:
            abort(400, description=f'En fazla {MAX_UPLOAD_FILES} dosya yüklenebilir')
        prepared = []
        total = 0
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                abort(400, description='Geçersiz dosya bilgisi')
            name = safe_filename(item.get('name'))
            size = coerce_int(item.get('size'), -1)
            suffix = Path(name).suffix.lower()
            if suffix not in catalog.SUPPORTED_FORMATS:
                abort(400, description=f'Desteklenmeyen dosya türü: {name}')
            if suffix in {'.rar', '.7z'}:
                abort(400, description=f'{suffix} arşivleri açılamıyor; lütfen ZIP kullanın: {name}')
            if size < 0 or size > MAX_UPLOAD_FILE:
                abort(400, description=f'Dosya çok büyük: {name}')
            rel_parts = safe_relative_path(item.get('path') or '')[:-1][:6]
            total += size
            prepared.append({'name': name, 'dirs': rel_parts, 'size': size, 'received': 0, 'part': f'{index}.part'})
        if total > MAX_UPLOAD_TOTAL:
            abort(400, description='Toplam yükleme boyutu çok büyük')
        try:
            free = shutil.disk_usage(self.models_dir if self.models_dir.exists() else self.data_dir).free
        except OSError:
            free = None
        if free is not None and free < total * 2 + 512 * 1024 * 1024:
            abort(507, description='Sunucuda yeterli disk alanı yok')

        upload_id = secrets.token_hex(12)
        directory = self.uploads_dir / upload_id
        directory.mkdir(parents=True, exist_ok=False)
        for item in prepared:
            (directory / item['part']).touch()
        with self.lock:
            self._uploads[upload_id] = {'id': upload_id, 'created': now(), 'updated': now(), 'files': prepared}
            self._upload_locks[upload_id] = threading.Lock()
        return {'id': upload_id, 'chunkSize': CHUNK_SIZE, 'files': [{'name': item['name'], 'size': item['size']} for item in prepared]}

    def _get_upload(self, upload_id):
        with self.lock:
            upload = self._uploads.get(upload_id)
            if upload is None:
                abort(404, description='Yükleme oturumu bulunamadı veya süresi doldu')
            return upload, self._upload_locks[upload_id]

    def write_chunk(self, upload_id, index, offset, stream, length):
        upload, lock = self._get_upload(upload_id)
        if not 0 <= index < len(upload['files']):
            abort(404, description='Dosya bulunamadı')
        item = upload['files'][index]
        with lock:
            if offset < item['received'] and offset + length <= item['received']:
                return {'received': item['received']}
            if offset != item['received']:
                return {'received': item['received'], 'conflict': True}
            if length <= 0 or length > CHUNK_SIZE + 1024 or item['received'] + length > item['size']:
                abort(400, description='Geçersiz parça boyutu')
            path = self.uploads_dir / upload_id / item['part']
            written = 0
            with open(path, 'r+b') as handle:
                # Önceki yarım kalmış denemeden artan baytları at.
                handle.seek(item['received'])
                handle.truncate()
                try:
                    while written < length:
                        block = stream.read(min(1024 * 1024, length - written))
                        if not block:
                            break
                        handle.write(block)
                        written += len(block)
                except BaseException:
                    handle.seek(item['received'])
                    handle.truncate()
                    raise
                if written != length:
                    handle.seek(item['received'])
                    handle.truncate()
                    abort(400, description='Parça eksik alındı')
            item['received'] += written
            upload['updated'] = now()
            return {'received': item['received']}

    def cancel_upload(self, upload_id):
        if not re.fullmatch(r'[0-9a-f]{24}', str(upload_id or '')):
            return
        with self.lock:
            self._uploads.pop(upload_id, None)
            self._upload_locks.pop(upload_id, None)
        shutil.rmtree(self.uploads_dir / upload_id, ignore_errors=True)

    def cleanup_uploads(self, max_age=UPLOAD_TTL):
        stamp = now()
        with self.lock:
            for upload_id, upload in list(self._uploads.items()):
                if stamp - upload['updated'] > max_age:
                    self.cancel_upload(upload_id)
            active = set(self._uploads)
        if self.uploads_dir.is_dir():
            for path in self.uploads_dir.iterdir():
                if path.name not in active and path.is_dir():
                    try:
                        if stamp - path.stat().st_mtime > max_age:
                            shutil.rmtree(path, ignore_errors=True)
                    except OSError:
                        pass

    def finish_upload(self, upload_id, meta):
        upload, lock = self._get_upload(upload_id)
        with lock:
            incomplete = [item['name'] for item in upload['files'] if item['received'] != item['size']]
            if incomplete:
                abort(400, description='Tamamlanmamış dosyalar var: ' + ', '.join(incomplete[:3]))

            target_id = meta.get('target')
            author_hint = None
            with self.scan_lock:
                if target_id:
                    record = self.record(target_id)
                    if not record:
                        abort(404, description='Hedef model bulunamadı')
                    if record['kind'] != 'folder':
                        abort(400, description='Dosya yalnızca klasör tabanlı modellere eklenebilir')
                    destination = self.models_dir / record['path']
                else:
                    title = clean_text(meta.get('title'), 160)
                    if not title:
                        first = next((item for item in upload['files'] if Path(item['name']).suffix.lower() in catalog.MODEL_FORMATS | {'.zip'}), upload['files'][0])
                        title = catalog.clean_title(first['name'], is_file=True)[0]
                    folder = safe_filename(title, fallback='Yeni model', max_len=120)
                    destination = unique_path(self.models_dir / folder)
                    destination.mkdir(parents=True)

                source_dir = self.uploads_dir / upload_id
                placed = []
                try:
                    for item in upload['files']:
                        part = source_dir / item['part']
                        subdir = destination.joinpath(*item['dirs']) if item['dirs'] else destination
                        subdir.mkdir(parents=True, exist_ok=True)
                        if Path(item['name']).suffix.lower() == '.zip':
                            hint = extract_zip_safely(part, subdir, zip_name=item['name'])
                            author_hint = author_hint or hint
                        else:
                            target = unique_path(subdir / item['name'])
                            shutil.move(str(part), str(target))
                            placed.append((target, part))
                except BaseException:
                    if target_id:
                        for target, part in placed:
                            if target.exists() and not part.exists():
                                shutil.move(str(target), str(part))
                    else:
                        shutil.rmtree(destination, ignore_errors=True)
                    raise

            self.cancel_upload(upload_id)
            self.scan()

        rel_dest = destination.relative_to(self.models_dir).as_posix()
        with self.lock:
            created = [
                model_id for model_id, record in self.db['catalog'].items()
                if record['path'] == rel_dest or record['path'].startswith(rel_dest + '/')
            ]
            if target_id:
                created = [target_id] if target_id in self.db['catalog'] else created
            if not created:
                if not target_id:
                    shutil.move(str(destination), str(unique_path(self.trash_dir / destination.name)))
                    self.scan()
                abort(400, description='Yüklenen dosyalar arasında 3D model bulunamadı (STL, 3MF, OBJ, PLY, GLB...)')
            stamp = now()
            for model_id in created:
                user = self.db['models'].setdefault(model_id, default_user_record())
                if not target_id:
                    user['added_at'] = stamp
                    user['uploaded_at'] = stamp
                    if author_hint and not meta.get('author'):
                        user['author'] = author_hint
            self.save()

        updates = {key: meta[key] for key in ('category', 'tags', 'description', 'author', 'source_url', 'license', 'hidden', 'nsfw') if key in meta}
        if not target_id and len(created) == 1 and meta.get('title'):
            updates['title'] = meta['title']
        for key in ('description', 'author', 'source_url', 'license'):
            if key in updates and not str(updates[key] or '').strip():
                updates.pop(key)
        if 'tags' in updates and not updates['tags']:
            updates.pop('tags')
        if updates.get('category') in (None, ''):
            updates.pop('category', None)
        for model_id in created:
            self.update_model(model_id, updates)
        return created

    # ── Paylaşımlar ──

    def shares_for(self, model_id):
        items = []
        for token, share in self.db['shares'].items():
            if share['model_id'] == model_id:
                items.append(self.share_payload(token, share))
        return sorted(items, key=lambda item: -item['createdAt'])

    def share_payload(self, token, share):
        record = self.record(share['model_id'])
        return {
            'token': token,
            'url': f'/s/{token}',
            'modelId': share['model_id'],
            'modelTitle': self.effective(share['model_id'])['title'] if record else '(silinmiş model)',
            'createdAt': share['created_at'],
            'expiresAt': share['expires_at'],
            'expired': bool(share['expires_at'] and share['expires_at'] < now()),
            'allowDownload': share['allow_download'],
            'note': share['note'],
            'views': share['views'],
            'lastViewedAt': share['last_viewed_at'],
        }

    def create_share(self, model_id, expires_days=None, allow_download=True, note=''):
        with self.lock:
            if model_id not in self.db['catalog']:
                abort(404, description='Model bulunamadı')
            if expires_days is not None and expires_days not in SHARE_EXPIRY_DAYS:
                abort(400, description='Geçersiz süre')
            token = secrets.token_urlsafe(9)
            share = {
                'model_id': model_id,
                'created_at': now(),
                'expires_at': now() + expires_days * 86400 if expires_days else None,
                'allow_download': bool(allow_download),
                'note': clean_text(note, 120),
                'views': 0,
                'last_viewed_at': None,
            }
            self.db['shares'][token] = share
            self.save()
            return self.share_payload(token, share)

    def update_share(self, token, payload):
        with self.lock:
            share = self.db['shares'].get(token)
            if share is None:
                abort(404, description='Paylaşım bulunamadı')
            if 'allow_download' in payload:
                share['allow_download'] = bool(payload['allow_download'])
            if 'note' in payload:
                share['note'] = clean_text(payload['note'], 120)
            if 'expires_days' in payload:
                days = payload['expires_days']
                if days is not None and days not in SHARE_EXPIRY_DAYS:
                    abort(400, description='Geçersiz süre')
                share['expires_at'] = now() + days * 86400 if days else None
            self.save()
            return self.share_payload(token, share)

    def delete_share(self, token):
        with self.lock:
            if self.db['shares'].pop(token, None) is None:
                abort(404, description='Paylaşım bulunamadı')
            self.save()

    def resolve_share(self, token):
        if not token or not re.fullmatch(r'[A-Za-z0-9_-]{8,40}', token):
            return None
        with self.lock:
            share = self.db['shares'].get(token)
            if not share or share['model_id'] not in self.db['catalog']:
                return None
            if share['expires_at'] and share['expires_at'] < now():
                return None
            return share

    def record_share_view(self, token):
        with self.lock:
            share = self.db['shares'].get(token)
            if share:
                share['views'] += 1
                share['last_viewed_at'] = now()
                self.save()

    # ── Kimlik doğrulama ──

    # Kimlik bilgileri db.json'dan ayrı tutulur; böylece CLI ile şifre değiştirmek
    # çalışan sunucunun bellekteki veritabanıyla çakışmaz.

    def _read_admin(self):
        try:
            mtime = self.admin_path.stat().st_mtime_ns
        except OSError:
            return {'password_hash': '', 'session_epoch': 1}
        if self._admin is None or mtime != self._admin_mtime:
            try:
                data = json.loads(self.admin_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                data = {}
            self._admin = {
                'password_hash': str(data.get('password_hash') or ''),
                'session_epoch': coerce_int(data.get('session_epoch'), 1),
            }
            self._admin_mtime = mtime
        return self._admin

    def _write_admin(self, data):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix='.admin-', suffix='.json', dir=self.data_dir)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, self.admin_path)
        self._admin = None

    @property
    def session_epoch(self):
        return self._read_admin()['session_epoch']

    def password_is_set(self):
        return bool(self._read_admin()['password_hash'])

    def set_password(self, password):
        if len(password or '') < MIN_PASSWORD_LENGTH:
            raise ValueError(f'Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı')
        with self.lock:
            current = self._read_admin()
            self._write_admin({
                'password_hash': generate_password_hash(password),
                'session_epoch': current['session_epoch'] + 1,
            })

    def check_password(self, password):
        stored = self._read_admin()['password_hash']
        if not stored or not isinstance(password, str):
            return False
        try:
            return check_password_hash(stored, password)
        except (ValueError, TypeError):
            return False

    def login_blocked(self, client):
        stamp = now()
        with self.lock:
            while self._global_failures and stamp - self._global_failures[0] > LOGIN_WINDOW:
                self._global_failures.popleft()
            failures = self._login_failures.get(client) or deque()
            while failures and stamp - failures[0] > LOGIN_WINDOW:
                failures.popleft()
            if len(failures) >= LOGIN_MAX_FAILURES:
                return int(LOGIN_WINDOW - (stamp - failures[0])) + 1
            if len(self._global_failures) >= LOGIN_MAX_GLOBAL_FAILURES:
                return int(LOGIN_WINDOW - (stamp - self._global_failures[0])) + 1
            return 0

    def record_login_failure(self, client):
        with self.lock:
            self._login_failures.setdefault(client, deque()).append(now())
            self._global_failures.append(now())
            if len(self._login_failures) > 5000:
                self._login_failures.clear()

    def clear_login_failures(self, client):
        with self.lock:
            self._login_failures.pop(client, None)


def extract_zip_safely(zip_path, destination, zip_name=''):
    """Zip'i güvenle aç: yol kaçışı, sembolik bağlantı ve zip bombasına karşı korumalı."""
    destination = Path(destination)
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        abort(400, description=f'Bozuk ZIP dosyası: {zip_name}')
    with archive:
        members = []
        for info in archive.infolist():
            if info.is_dir() or info.flag_bits & 0x1:
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue
            parts = [part for part in info.filename.replace('\\', '/').split('/') if part not in {'', '.'}]
            if not parts or any(part == '..' or catalog.is_ignored(part) for part in parts):
                continue
            if Path(parts[-1]).suffix.lower() not in catalog.SUPPORTED_FORMATS:
                continue
            members.append((info, parts))
        if not members:
            abort(400, description=f'ZIP içinde desteklenen dosya bulunamadı: {zip_name}')
        if len(members) > 5000 or sum(info.file_size for info, _ in members) > MAX_EXTRACT_BYTES:
            abort(400, description=f'ZIP içeriği çok büyük: {zip_name}')

        stripped = []
        while all(len(parts) > 1 for _, parts in members) and len({parts[0] for _, parts in members}) == 1:
            stripped.append(members[0][1][0])
            members = [(info, parts[1:]) for info, parts in members]
        author = stripped[0] if len(stripped) >= 2 and catalog.WRAPPER_SUFFIX.search(Path(zip_name).stem) else None

        root = destination.resolve()
        for info, parts in members:
            safe_parts = [safe_filename(part, fallback='dosya', max_len=120) for part in parts]
            target = destination.joinpath(*safe_parts)
            if not str(target.resolve()).startswith(str(root) + os.sep):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target = unique_path(target)
            written = 0
            with archive.open(info) as source, open(target, 'wb') as handle:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > info.file_size + 1024:
                        break
                    handle.write(block)
        return author


# ─── İstek bağlamı ────────────────────────────────────────────────────


class Viewer:
    def __init__(self, admin=False, share=None, share_token=None):
        self.admin = admin
        self.share = share
        self.share_token = share_token if share else None


def lib():
    return current_app.extensions['library']


def is_admin():
    if not session.get('admin'):
        return False
    return session.get('epoch') == lib().session_epoch


def csrf_token():
    token = session.get('csrf')
    if not token:
        token = secrets.token_urlsafe(24)
        session['csrf'] = token
    return token


def current_viewer(share_token=None):
    token = share_token or request.args.get('s')
    share = lib().resolve_share(token) if token else None
    return Viewer(admin=is_admin(), share=share, share_token=token)


def client_key():
    return request.remote_addr or 'unknown'


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(401, description='Bu işlem için yönetici girişi gerekli')
        return view(*args, **kwargs)
    return wrapper


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description='Geçerli bir JSON nesnesi bekleniyordu')
    return data


def resolve_library_file(rel_path):
    library = lib()
    rel_path = normalize_rel_path(rel_path)
    full = library.models_dir / rel_path
    try:
        resolved = full.resolve()
        resolved.relative_to(library.models_dir.resolve())
    except (ValueError, OSError):
        abort(404)
    if not resolved.is_file() or resolved.suffix.lower() not in catalog.SUPPORTED_FORMATS:
        abort(404)
    return rel_path, resolved


def ensure_file_access(rel_path, viewer, download=False):
    """
    Ziyaretçi erişimi: paylaşım bağlantısı yalnızca kendi modelinin dosyalarını açar;
    herkese açık erişim için dosyayı içeren TÜM modellerin herkese açık olması gerekir
    (bir modeli gizlemek, başka bir modelle ortak dosyayı da gizler).
    """
    if viewer.admin:
        return
    library = lib()
    owners = library.models_for_path(rel_path)
    if not owners:
        abort(404)
    if viewer.share and viewer.share['model_id'] in owners:
        if download and not viewer.share['allow_download']:
            abort(403, description='Bu dosyayı indirme izniniz yok')
        return
    with library.lock:
        if not all(library.is_public(model_id) for model_id in owners):
            abort(404)
        if download and not library.settings['public_downloads']:
            abort(403, description='Bu dosyayı indirme izniniz yok')


def is_preview_format(name):
    """Tarayıcı önizlemesi için gereken dosyalar (3D modeller ve görseller)."""
    return Path(name).suffix.lower().lstrip('.') in PREVIEW_FORMATS


def private_cache(response, max_age=600):
    response.headers['Cache-Control'] = f'private, max-age={max_age}'
    return response


_asset_versions = {}


def asset_url(filename):
    version = _asset_versions.get(filename)
    if version is None:
        try:
            stat = (BASE_DIR / 'static' / filename).stat()
            version = hashlib.md5(f'{stat.st_mtime_ns}:{stat.st_size}'.encode()).hexdigest()[:8]
        except OSError:
            version = '0'
        if not current_app.debug:
            _asset_versions[filename] = version
    return f'/static/{filename}?v={version}'


def boot_payload(**extra):
    library = lib()
    settings = library.settings
    payload = {
        'site': {'title': settings['site_title'], 'tagline': settings['site_tagline']},
        'admin': is_admin(),
        'csrf': csrf_token(),
        'passwordSet': library.password_is_set(),
        'publicBrowsing': settings['public_browsing'],
        'categories': categories.category_payload(),
        'chunkSize': CHUNK_SIZE,
        'uploadFormats': sorted(fmt.lstrip('.') for fmt in catalog.SUPPORTED_FORMATS if fmt not in {'.rar', '.7z'}),
    }
    payload.update(extra)
    return payload


def og_meta(model_id, viewer, share_token=None):
    library = lib()
    values = library.effective(model_id)
    description = values['description'] or ''
    summary = library.category_label(values['category'])
    if values['author']:
        summary += f" · {values['author']}"
    if description:
        summary += ' — ' + description[:160]
    image = f'/api/og/{model_id}'
    derived = library.db['derived'].get(model_id) or {}
    if derived.get('thumb_key'):
        image += f"?v={derived['thumb_key'][:10]}"
    return {
        'title': values['title'],
        'description': summary,
        'image': request.url_root.rstrip('/') + with_share(image, share_token),
        'url': request.url,
    }


# ─── Sayfalar ─────────────────────────────────────────────────────────


@bp.before_app_request
def before_request():
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.path.startswith('/api/'):
        sent = request.headers.get('X-CSRF-Token', '').encode('utf-8', 'surrogateescape')
        expected = str(session.get('csrf', '')).encode('utf-8')
        if not expected or not hmac.compare_digest(sent, expected):
            abort(403, description='Oturum doğrulaması başarısız. Sayfayı yenileyip tekrar deneyin.')


@bp.after_app_request
def security_headers(response):
    headers = response.headers
    headers.setdefault('X-Content-Type-Options', 'nosniff')
    headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
    if request.is_secure:
        headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
    if response.mimetype == 'text/html':
        headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self' blob: data: https://cloudflareinsights.com; worker-src 'self' blob:; "
            "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )
        headers['Cache-Control'] = 'no-store'
    elif request.path.startswith('/static/'):
        if request.args.get('v'):
            headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif response.mimetype == 'application/json':
        headers['Cache-Control'] = 'no-store'
    return response


@bp.app_errorhandler(HTTPException)
def handle_http_error(exc):
    if request.path.startswith('/api/'):
        response = jsonify({'error': exc.description or exc.name})
        response.status_code = exc.code or 500
        return response
    return render_template('error.html', code=exc.code, message=exc.description or exc.name, boot=boot_payload()), exc.code


@bp.route('/')
def index():
    library = lib()
    library.ensure_scanned()
    return render_template('index.html', boot=boot_payload(), og=None)


@bp.route('/m/<model_id>')
def model_page(model_id):
    library = lib()
    library.ensure_scanned()
    viewer = current_viewer()
    og = og_meta(model_id, viewer) if library.can_view(model_id, viewer) else None
    return render_template('index.html', boot=boot_payload(initialModel=model_id), og=og)


@bp.route('/s/<token>')
def share_page(token):
    library = lib()
    library.ensure_scanned()
    share = library.resolve_share(token)
    if not share:
        return render_template('share.html', boot=boot_payload(share=None), og=None), 404
    viewer = current_viewer(share_token=token)
    detail = library.detail(share['model_id'], viewer)
    if not viewer.admin:
        library.record_share_view(token)
    boot = boot_payload(share={'token': token, 'model': detail, 'allowDownload': share['allow_download'], 'expiresAt': share['expires_at']})
    return render_template('share.html', boot=boot, og=og_meta(share['model_id'], viewer, token))


@bp.route('/robots.txt')
def robots():
    return Response('User-agent: *\nDisallow: /\n', mimetype='text/plain')


@bp.route('/healthz')
def healthz():
    return Response('ok', mimetype='text/plain')


# ─── API: oturum ──────────────────────────────────────────────────────


@bp.route('/api/session')
def api_session():
    return jsonify({'admin': is_admin(), 'csrf': csrf_token(), 'passwordSet': lib().password_is_set()})


@bp.route('/api/auth/login', methods=['POST'])
def api_login():
    library = lib()
    client = client_key()
    wait = library.login_blocked(client)
    if wait:
        minutes = max(1, round(wait / 60))
        abort(429, description=f'Çok fazla hatalı deneme. {minutes} dakika sonra tekrar deneyin.')
    if not library.password_is_set():
        abort(503, description='Yönetici şifresi henüz ayarlanmamış. Sunucuda "python app.py set-admin-password" çalıştırın.')
    password = json_body().get('password')
    if not library.check_password(password):
        library.record_login_failure(client)
        time.sleep(0.4)
        abort(401, description='Şifre hatalı')
    library.clear_login_failures(client)
    session.clear()
    session.permanent = True
    session['admin'] = True
    session['epoch'] = library.session_epoch
    session['csrf'] = secrets.token_urlsafe(24)
    return jsonify({'admin': True, 'csrf': session['csrf']})


@bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'admin': False, 'csrf': csrf_token()})


@bp.route('/api/auth/password', methods=['POST'])
@require_admin
def api_change_password():
    library = lib()
    data = json_body()
    if not library.check_password(data.get('current')):
        abort(400, description='Mevcut şifre hatalı')
    try:
        library.set_password(str(data.get('new') or ''))
    except ValueError as exc:
        abort(400, description=str(exc))
    session['epoch'] = library.session_epoch
    return jsonify({'success': True})


# ─── API: kütüphane ───────────────────────────────────────────────────


@bp.route('/api/library')
def api_library():
    library = lib()
    library.ensure_scanned()
    viewer = current_viewer()
    if not viewer.admin and not library.settings['public_browsing']:
        abort(401, description='Bu arşiv özel. Görüntülemek için giriş yapın.')
    return jsonify(library.library_payload(viewer))


@bp.route('/api/models/<model_id>')
def api_model(model_id):
    library = lib()
    viewer = current_viewer()
    with library.lock:
        if not library.can_view(model_id, viewer):
            abort(404, description='Model bulunamadı')
        return jsonify(library.detail(model_id, viewer))


@bp.route('/api/models/<model_id>', methods=['PATCH'])
@require_admin
def api_update_model(model_id):
    library = lib()
    library.update_model(model_id, json_body())
    with library.lock:
        return jsonify(library.detail(model_id, current_viewer()))


@bp.route('/api/models/<model_id>', methods=['DELETE'])
@require_admin
def api_delete_model(model_id):
    lib().trash_model(model_id)
    return jsonify({'success': True})


@bp.route('/api/models/<model_id>/thumbnail', methods=['POST'])
@require_admin
def api_refresh_thumbnail(model_id):
    library = lib()
    with library.lock:
        derived = library.db['derived'].setdefault(model_id, {})
        derived.pop('thumb_key', None)
        derived.pop('thumb_failed_key', None)
        derived.pop('stats_failed_key', None)
    queued = library.queue_derived([model_id], force=True)
    return jsonify({'queued': queued})


@bp.route('/api/models/<model_id>/download')
def api_download_model(model_id):
    library = lib()
    viewer = current_viewer()
    with library.lock:
        if not library.can_view(model_id, viewer):
            abort(404)
        if not library.can_download(model_id, viewer):
            abort(403, description='Bu modeli indirme izniniz yok')
        record = library.record(model_id)
        title = library.effective(model_id)['title']
        entries = [entry for entry in record['files'] + record['assets'] if not entry.get('member')]
        base = library.models_dir / record['path'] if record['kind'] == 'folder' else library.models_dir
    zip_name = safe_filename(title, fallback='model', max_len=80) + '.zip'
    if record['kind'] == 'archive':
        archive = library.models_dir / record['path']
        return private_cache(send_file(archive, as_attachment=True, download_name=zip_name), 0)

    def generate():
        stream = _ZipStream()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for entry in entries:
                path = library.models_dir / entry['path']
                try:
                    arcname = path.relative_to(base).as_posix()
                except ValueError:
                    arcname = path.name
                info = zipfile.ZipInfo(arcname, date_time=time.localtime(entry.get('modified') or now())[:6])
                compressible = entry['format'] in COMPRESSIBLE_FORMATS
                info.compress_type = zipfile.ZIP_DEFLATED if compressible else zipfile.ZIP_STORED
                if compressible:
                    try:
                        info.compress_level = 1
                    except AttributeError:
                        info._compresslevel = 1
                info.file_size = entry['size']
                try:
                    with open(path, 'rb') as source, archive.open(info, 'w', force_zip64=entry['size'] > 2 ** 31) as dest:
                        while True:
                            block = source.read(1024 * 1024)
                            if not block:
                                break
                            dest.write(block)
                            yield from stream.drain()
                except OSError:
                    continue
        yield from stream.drain()

    response = Response(stream_with_context(generate()), mimetype='application/zip')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(zip_name)}"
    return private_cache(response, 0)


class _ZipStream:
    """zipfile'ın akış halinde yazabilmesi için basit, konumlanamayan tampon."""

    def __init__(self):
        self._chunks = []
        self._position = 0

    def write(self, data):
        self._chunks.append(bytes(data))
        self._position += len(data)
        return len(data)

    def tell(self):
        return self._position

    def flush(self):
        pass

    def drain(self):
        chunks, self._chunks = self._chunks, []
        yield from chunks


@bp.route('/api/thumb/<model_id>')
def api_thumb(model_id):
    library = lib()
    viewer = current_viewer()
    with library.lock:
        if not library.can_view(model_id, viewer):
            abort(404)
        name = (library.db['derived'].get(model_id) or {}).get('thumb')
    if not name or not (library.thumbs_dir / name).exists():
        abort(404)
    response = send_file(library.thumbs_dir / name, mimetype='image/webp', conditional=True)
    return private_cache(response, 31536000 if request.args.get('v') else 300)


@bp.route('/api/og/<model_id>')
def api_og(model_id):
    library = lib()
    viewer = current_viewer()
    with library.lock:
        if not library.can_view(model_id, viewer):
            abort(404)
        derived = library.db['derived'].get(model_id) or {}
        nsfw = library.effective_nsfw(model_id)
    name = derived.get('og')
    if nsfw or not name or not (library.thumbs_dir / name).exists():
        default = library.thumbs_dir / '_site-card.jpg'
        with library._card_lock:
            if not default.exists():
                library.thumbs_dir.mkdir(parents=True, exist_ok=True)
                env = dict(os.environ, PYTHONPATH=str(BASE_DIR) + os.pathsep + os.environ.get('PYTHONPATH', ''))
                subprocess.run([sys.executable, '-m', 'meshes', 'default-card', str(default)], cwd=str(BASE_DIR), env=env, timeout=60, check=False)
        if not default.exists():
            abort(404)
        return private_cache(send_file(default, mimetype='image/jpeg'), 3600)
    return private_cache(send_file(library.thumbs_dir / name, mimetype='image/jpeg', conditional=True), 86400)


@bp.route('/api/file/<path:filepath>')
def api_file(filepath):
    viewer = current_viewer()
    download = request.args.get('download') == '1'
    rel_path, full_path = resolve_library_file(filepath)
    member = request.args.get('member')
    # İndirme izni yoksa yalnızca önizleme için gereken dosyalar (model ve görsel) verilir.
    ensure_file_access(rel_path, viewer, download=download or not is_preview_format(member or full_path.name))
    if member:
        if full_path.suffix.lower() != '.zip':
            abort(404)
        listing = catalog.list_zip(full_path) or []
        info = next((item for item in listing if item['member'] == member), None)
        if info is None or Path(member).suffix.lower() not in catalog.SUPPORTED_FORMATS:
            abort(404)
        name = Path(member).name

        def generate():
            with zipfile.ZipFile(full_path) as archive, archive.open(member) as source:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    yield block

        mimetype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        if Path(name).suffix.lower().lstrip('.') in TEXT_FORMATS:
            mimetype = 'text/plain'
        response = Response(generate(), mimetype=mimetype)
        response.headers['Content-Length'] = str(info['size'])
        disposition = 'attachment' if download else 'inline'
        response.headers['Content-Disposition'] = f"{disposition}; filename*=UTF-8''{quote(name)}"
        return private_cache(response)

    suffix = full_path.suffix.lower().lstrip('.')
    mimetype = 'text/plain' if suffix in TEXT_FORMATS else None
    if suffix in {'stl', '3mf', 'obj', 'ply', 'fbx', 'gcode', 'bgcode', 'step', 'stp', 'f3d', 'scad', 'x_t', 'skp', 'dxf', 'iges', 'igs', 'fcstd'}:
        mimetype = 'application/octet-stream'
    response = send_file(
        full_path,
        mimetype=mimetype,
        as_attachment=download,
        download_name=full_path.name,
        conditional=True,
    )
    if mimetype == 'text/plain':
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return private_cache(response)


@bp.route('/api/mesh/<path:filepath>')
def api_mesh(filepath):
    """3MF/OBJ/PLY dosyasını tarayıcının hızlı açabileceği kompakt biçimde döndür."""
    viewer = current_viewer()
    rel_path, full_path = resolve_library_file(filepath)
    ensure_file_access(rel_path, viewer)
    member = request.args.get('member') or None
    if member:
        listing = catalog.list_zip(full_path) or [] if full_path.suffix.lower() == '.zip' else []
        if not any(item['member'] == member for item in listing):
            abort(404)
    fmt = Path(member or full_path.name).suffix.lower().lstrip('.')
    if fmt not in COMPACT_FORMATS:
        abort(404)
    compact = lib().compact_mesh(rel_path, member)
    if compact is None:
        abort(422, description='Mesh dönüştürülemedi')
    return private_cache(send_file(compact, mimetype='application/octet-stream', conditional=True), 86400)


@bp.route('/api/preview/<path:filepath>')
def api_preview(filepath):
    viewer = current_viewer()
    rel_path, full_path = resolve_library_file(filepath)
    ensure_file_access(rel_path, viewer)
    if full_path.suffix.lower() != '.3mf':
        abort(404)
    details = catalog.read_3mf_details(full_path)
    entry = details.get('preview_entry')
    if not entry:
        abort(404)
    try:
        with zipfile.ZipFile(full_path) as archive:
            data = archive.read(entry)
    except (OSError, zipfile.BadZipFile, KeyError):
        abort(404)
    mimetype = mimetypes.guess_type(entry)[0] or 'image/png'
    return private_cache(Response(data, mimetype=mimetype), 3600)


# ─── API: yönetim ─────────────────────────────────────────────────────


@bp.route('/api/scan', methods=['POST'])
@require_admin
def api_scan():
    summary = lib().scan()
    return jsonify({'success': True, 'total': summary['total'], 'added': len(summary['added']), 'removed': len(summary['removed'])})


@bp.route('/api/admin/status')
@require_admin
def api_status():
    return jsonify(lib().status())


@bp.route('/api/admin/thumbnails', methods=['POST'])
@require_admin
def api_rebuild_thumbnails():
    library = lib()
    if json_body().get('all'):
        with library.lock:
            for derived in library.db['derived'].values():
                for key in ('thumb_key', 'thumb_failed_key', 'stats_failed_key'):
                    derived.pop(key, None)
    queued = library.queue_derived(force=True)
    return jsonify({'queued': queued})


@bp.route('/api/settings')
@require_admin
def api_settings():
    settings = lib().settings
    return jsonify({key: settings[key] for key in ('site_title', 'site_tagline', 'public_browsing', 'public_downloads', 'hide_nsfw')})


@bp.route('/api/settings', methods=['PATCH'])
@require_admin
def api_update_settings():
    library = lib()
    data = json_body()
    with library.lock:
        settings = library.settings
        if 'site_title' in data:
            settings['site_title'] = clean_text(data['site_title'], 60) or DEFAULT_SETTINGS['site_title']
        if 'site_tagline' in data:
            settings['site_tagline'] = clean_text(data['site_tagline'], 140)
        for key in ('public_browsing', 'public_downloads', 'hide_nsfw'):
            if key in data:
                settings[key] = bool(data[key])
        library.save()
        return jsonify({key: settings[key] for key in ('site_title', 'site_tagline', 'public_browsing', 'public_downloads', 'hide_nsfw')})


@bp.route('/api/classify', methods=['POST'])
@require_admin
def api_classify():
    """Yükleme formu için başlık ve dosya adlarından kategori/etiket öner."""
    data = json_body()
    title = clean_text(data.get('title'), 160)
    names = [clean_text(name, 200) for name in (data.get('files') or [])[:200] if isinstance(name, str)]
    stems = ' '.join(Path(name).stem for name in names)
    suggested_title = ''
    first = next((name for name in names if Path(name).suffix.lower() in catalog.MODEL_FORMATS | {'.zip'}), names[0] if names else '')
    if first:
        suggested_title = catalog.clean_title(Path(first).name, is_file=True)[0]
    folders = ' '.join({part for name in names for part in name.replace('\\', '/').split('/')[:-1]})
    category, _ = categories.classify([(title or suggested_title, 3.0, None), (folders, 2.0, None), (stems, 1.2, 7.0)])
    texts = [title, suggested_title, stems, folders]
    return jsonify({
        'category': category,
        'tags': categories.auto_tags(texts),
        'nsfw': categories.is_nsfw(texts),
        'title': suggested_title,
    })


@bp.route('/api/uploads', methods=['POST'])
@require_admin
def api_create_upload():
    return jsonify(lib().create_upload(json_body().get('files')))


@bp.route('/api/uploads/<upload_id>/<int:index>', methods=['PUT'])
@require_admin
def api_upload_chunk(upload_id, index):
    offset = coerce_int(request.headers.get('X-Upload-Offset'), -1)
    length = request.content_length
    if offset < 0 or length is None:
        abort(400, description='Parça bilgisi eksik')
    result = lib().write_chunk(upload_id, index, offset, request.stream, length)
    status = 409 if result.get('conflict') else 200
    return jsonify(result), status


@bp.route('/api/uploads/<upload_id>/complete', methods=['POST'])
@require_admin
def api_complete_upload(upload_id):
    library = lib()
    created = library.finish_upload(upload_id, json_body())
    viewer = current_viewer()
    with library.lock:
        return jsonify({'models': [library.detail(model_id, viewer) for model_id in created]})


@bp.route('/api/uploads/<upload_id>', methods=['DELETE'])
@require_admin
def api_cancel_upload(upload_id):
    lib().cancel_upload(upload_id)
    return jsonify({'success': True})


@bp.route('/api/shares')
@require_admin
def api_shares():
    library = lib()
    with library.lock:
        items = [library.share_payload(token, share) for token, share in library.db['shares'].items()]
    return jsonify({'shares': sorted(items, key=lambda item: -item['createdAt'])})


@bp.route('/api/models/<model_id>/shares', methods=['POST'])
@require_admin
def api_create_share(model_id):
    data = json_body()
    days = data.get('expires_days')
    days = coerce_int(days, 0) or None if days is not None else None
    share = lib().create_share(model_id, days, data.get('allow_download', True), data.get('note', ''))
    return jsonify(share), 201


@bp.route('/api/shares/<token>', methods=['PATCH'])
@require_admin
def api_update_share(token):
    data = json_body()
    if 'expires_days' in data and data['expires_days'] is not None:
        data['expires_days'] = coerce_int(data['expires_days'], 0) or None
    return jsonify(lib().update_share(token, data))


@bp.route('/api/shares/<token>', methods=['DELETE'])
@require_admin
def api_delete_share(token):
    lib().delete_share(token)
    return jsonify({'success': True})


# ─── Uygulama fabrikası ──────────────────────────────────────────────


def load_secret_key(data_dir):
    configured = os.getenv('MODEL_MANAGER_SECRET_KEY')
    if configured:
        return configured
    path = Path(data_dir) / '.secret_key'
    try:
        if path.exists():
            value = path.read_text(encoding='utf-8').strip()
            if len(value) >= 32:
                return value
        value = secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        os.chmod(path, 0o600)
        return value
    except OSError:
        log.warning('Gizli anahtar dosyası yazılamadı; oturumlar yeniden başlatmada sıfırlanır')
        return secrets.token_urlsafe(48)


def get_run_settings():
    host = os.getenv('MODEL_MANAGER_HOST', DEFAULT_HOST).strip() or DEFAULT_HOST
    port = coerce_int(os.getenv('MODEL_MANAGER_PORT', DEFAULT_PORT), DEFAULT_PORT)
    if not 1 <= port <= 65535:
        port = DEFAULT_PORT
    return {'host': host, 'port': port, 'debug': parse_env_bool(os.getenv('MODEL_MANAGER_DEBUG'))}


def create_app(models_dir=None, data_dir=None, start_workers=True, testing=False):
    models_dir = Path(models_dir or os.getenv('MODEL_MANAGER_MODELS_DIR') or BASE_DIR / '3d models')
    data_dir = Path(data_dir or os.getenv('MODEL_MANAGER_DATA_DIR') or BASE_DIR)
    app = Flask(__name__, static_folder=str(BASE_DIR / 'static'), template_folder=str(BASE_DIR / 'templates'))
    app.config.update(
        SECRET_KEY=load_secret_key(data_dir),
        SESSION_COOKIE_NAME='archive_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=parse_env_bool(os.getenv('MODEL_MANAGER_SECURE_COOKIES')),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        TESTING=testing,
    )
    app.json.ensure_ascii = False
    app.extensions['library'] = Library(models_dir, data_dir)
    app.register_blueprint(bp)
    app.jinja_env.globals['asset_url'] = asset_url
    if parse_env_bool(os.getenv('MODEL_MANAGER_TRUST_PROXY')):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if start_workers:
        app.extensions['library'].start()
    return app


# Arka plan işçileri (izleyici + önizleme kuyruğu) üretimde MODEL_MANAGER_WORKERS=1 ile,
# yerelde "python app.py" ile başlar; testlerde ve içe aktarmada başlamaz.
app = create_app(start_workers=parse_env_bool(os.getenv('MODEL_MANAGER_WORKERS')) and __name__ != '__main__')


# ─── Komut satırı ────────────────────────────────────────────────────


def main(argv=None):
    parser = argparse.ArgumentParser(description='3D Model Arşivi')
    sub = parser.add_subparsers(dest='command')
    password_cmd = sub.add_parser('set-admin-password', help='Yönetici şifresini ayarla')
    password_cmd.add_argument('--stdin', action='store_true', help='Şifreyi standart girdiden oku')
    sub.add_parser('scan', help='Kütüphaneyi tara')
    thumbs_cmd = sub.add_parser('thumbnails', help='Eksik küçük resimleri üret')
    thumbs_cmd.add_argument('--all', action='store_true', help='Tümünü yeniden üret')
    args = parser.parse_args(argv)
    library = app.extensions['library']

    if args.command == 'set-admin-password':
        if args.stdin:
            password = sys.stdin.readline().rstrip('\r\n')
        else:
            password = getpass.getpass('Yeni yönetici şifresi: ')
            if password != getpass.getpass('Tekrar: '):
                print('Şifreler eşleşmiyor.', file=sys.stderr)
                return 1
        try:
            library.set_password(password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print('Yönetici şifresi güncellendi. Açık oturumlar kapatıldı.')
        return 0
    if args.command in {'scan', 'thumbnails'} and not library.acquire_server_lock():
        print('Sunucu çalışıyor. Tarama ve önizleme işlemlerini web arayüzündeki Ayarlar → Bakım sekmesinden yapın.', file=sys.stderr)
        return 1
    if args.command == 'scan':
        summary = library.scan()
        print(f"{summary['total']} model · {len(summary['added'])} yeni · {len(summary['removed'])} kaldırıldı")
        return 0
    if args.command == 'thumbnails':
        library.ensure_scanned()
        if args.all:
            with library.lock:
                for derived in library.db['derived'].values():
                    derived.pop('thumb_key', None)
                    derived.pop('thumb_failed_key', None)
        queued = library.queue_derived(force=True)
        print(f'{queued} iş kuyrukta, işleniyor...')
        library.run_pending_jobs()
        print('Tamamlandı.')
        return 0

    settings = get_run_settings()
    display_host = 'localhost' if settings['host'] in {'0.0.0.0', '::', DEFAULT_HOST} else settings['host']
    print(f"\n3D Model Arşivi başlıyor\nKlasör: {library.models_dir}\nAdres: http://{display_host}:{settings['port']}\n")
    if not library.password_is_set():
        print('Uyarı: yönetici şifresi ayarlanmamış. "python app.py set-admin-password" ile ayarlayın.\n')
    if not settings['debug'] or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        library.start()
    app.run(**settings, threaded=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
