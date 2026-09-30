"""
Model kütüphanesini tarayıp katalog kayıtları üreten modül.

Gruplama kuralları:
  * Kökteki tekil model dosyaları kendi başına bir modeldir.
  * Bir klasör; doğrudan model dosyaları ve "files", "V2", "UPDATES",
    "STL SINGLES" gibi yardımcı alt klasörleriyle birlikte tek modeldir.
  * "isim20250910-1-abc123/yazar/isim" gibi indirme sarmalayıcıları tek
    modele indirgenir; aradaki klasör adı tasarımcı olarak kaydedilir.
  * Doğrudan dosyası olmayan ve birden çok anlamlı alt klasör içeren klasör
    bir koleksiyondur; her alt klasör ayrı bir modeldir.
  * Kökteki açılmamış zip arşivleri (içinde model varsa) arşiv modeli olur.
"""

import hashlib
import html
import json
import logging
import os
import re
import threading
import zipfile
from pathlib import Path

import categories

log = logging.getLogger('model_archive')

MODEL_FORMATS = {'.stl', '.3mf', '.obj', '.ply', '.glb', '.gltf', '.fbx'}
IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
DOCUMENT_FORMATS = {'.pdf', '.txt', '.md'}
ARCHIVE_FORMATS = {'.zip', '.rar', '.7z'}
CAD_FORMATS = {'.step', '.stp', '.scad', '.skp', '.f3d', '.x_t', '.dxf', '.iges', '.igs', '.fcstd'}
MACHINE_FORMATS = {'.gcode', '.bgcode'}
SUPPORTED_FORMATS = (
    MODEL_FORMATS | IMAGE_FORMATS | DOCUMENT_FORMATS | ARCHIVE_FORMATS | CAD_FORMATS | MACHINE_FORMATS
)
VIEWABLE_FORMATS = {'stl', '3mf', 'obj', 'ply', 'glb', 'gltf'}
MAIN_FORMAT_PRIORITY = {'3mf': 0, 'stl': 1, 'obj': 2, 'glb': 3, 'gltf': 4, 'ply': 5, 'fbx': 6}
MAIN_PART_WORDS = {'body', 'main', 'full', 'assembly', 'assembled', 'complete', 'whole', 'chassis', 'govde', 'kasa', 'all'}
MINOR_PART_WORDS = {
    'wheel', 'wheels', 'tire', 'tyre', 'screw', 'screws', 'bolt', 'nut', 'washer', 'pin', 'pins', 'axle', 'spacer',
    'clip', 'peg', 'knob', 'cap', 'button', 'spring', 'hinge', 'latch', 'handle', 'lid', 'cover', 'vida', 'somun',
}
IGNORED_NAMES = {'__macosx', '.ds_store', 'thumbs.db', 'desktop.ini', '@eadir'}
THREEMF_PREVIEW_CANDIDATES = (
    'Auxiliaries/.thumbnails/thumbnail_3mf.png',
    'Auxiliaries/.thumbnails/thumbnail_middle.png',
    'Metadata/plate_1.png',
    'Metadata/top_1.png',
    'Auxiliaries/.thumbnails/thumbnail_small.png',
    'Metadata/plate_1_small.png',
)
WRAPPER_SUFFIX = re.compile(r'\d{8}-\d+-[a-z0-9]{4,8}$', re.IGNORECASE)
THINGIVERSE_HEADER = re.compile(r'^\s*(?P<title>.+?) by (?P<author>\S.*?) on Thingiverse:\s*(?P<url>https?://\S+)', re.IGNORECASE)
PRINTABLES_PDF = re.compile(r'^(?P<id>\d{3,9})-(?P<slug>[a-z0-9-]+?)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$', re.IGNORECASE)
LICENSE_CODES = [
    ('non-commercial - no derivatives', 'CC BY-NC-ND'),
    ('non-commercial - share alike', 'CC BY-NC-SA'),
    ('non-commercial', 'CC BY-NC'),
    ('no derivatives', 'CC BY-ND'),
    ('share alike', 'CC BY-SA'),
    ('creative commons - attribution', 'CC BY'),
    ('gnu - gpl', 'GPL'),
    ('gnu - lgpl', 'LGPL'),
    ('public domain', 'Kamu malı'),
    ('bsd', 'BSD'),
]

_cache_lock = threading.Lock()
_file_cache = {}


def generate_id(path_str):
    """Göreli yoldan tekrarlanabilir kısa kimlik üret."""
    return hashlib.md5(path_str.encode('utf-8')).hexdigest()[:12]


def format_size(size_bytes):
    """Byte değerini okunabilir biçime çevir."""
    size = float(size_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{int(size)} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} GB'


def is_ignored(name):
    lowered = name.lower()
    return lowered.startswith('.') or lowered in IGNORED_NAMES or lowered.startswith('~$')


def file_kind(name):
    """Dosyanın katalogdaki rolünü belirle."""
    lowered = name.lower()
    suffix = Path(lowered).suffix
    if suffix in MODEL_FORMATS:
        return 'model'
    if lowered.startswith('readme') and suffix in DOCUMENT_FORMATS:
        return 'readme'
    if lowered.startswith('license') or lowered.startswith('licence'):
        return 'license'
    if suffix in IMAGE_FORMATS:
        return 'image'
    if suffix in CAD_FORMATS:
        return 'cad'
    if suffix in MACHINE_FORMATS:
        return 'gcode'
    if suffix in ARCHIVE_FORMATS:
        return 'archive'
    if suffix in DOCUMENT_FORMATS:
        return 'document'
    return None


def _cached(kind, path, loader):
    """Dosya imzası (boyut + mtime) değişmedikçe ağır metadata okumalarını tekrarlama."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (kind, str(path))
    signature = (stat.st_size, stat.st_mtime_ns)
    with _cache_lock:
        cached = _file_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    value = loader(path)
    with _cache_lock:
        _file_cache[key] = (signature, value)
    return value


# ─── İsim temizleme ───────────────────────────────────────────────────


def _capitalize(text):
    if not text or not text[0].islower():
        return text
    first = text[0]
    if first == 'i' and re.search(r'[çğıöşüÇĞİÖŞÜ]', text):
        return 'İ' + text[1:]
    return first.upper() + text[1:]


def clean_title(raw, is_file=False):
    """İndirme artıklarını temizleyip okunur başlık üret. (başlık, yazar_ipucu) döner."""
    text = html.unescape(str(raw or '')).strip()
    if is_file:
        while True:
            stem, suffix = os.path.splitext(text)
            if suffix.lower() in SUPPORTED_FORMATS or suffix.lower() == '.stp':
                text = stem
                continue
            break
    author = None
    text = WRAPPER_SUFFIX.sub('', text)
    text = re.sub(r'(?i)^imagetostl\.com[_ -]*', '', text)
    text = re.sub(r'(?i)^obj_\d+_', '', text)
    text = text.replace('+', ' ').replace('_', ' ')
    text = re.sub(r'(?i)[\s-]*(model files|stls|stl files|files)\s*$', '', text)
    text = re.sub(r'(?i)\s+stl\.*\s*$', '', text)
    text = re.sub(r'(?i)\[(no ?supports?|hi ?res|exclusive)\]', ' ', text)
    text = re.sub(r'(?i)\((no|without) ?supports?\)', ' ', text)
    text = re.sub(r'\s+-\s+\d{4,}(?=\s+-\s+|\s*$)', '', text)
    text = re.sub(r'\s*\.?&\.?\s*', ' & ', text) if '&' in text else text
    text = re.sub(r'(?<=[a-zçğıöşü])([vV])(?=\d)', r' \1', text)
    if ' ' not in text.strip() and '-' in text:
        text = text.replace('-', ' ')
    match = re.search(r'(?i)\s+by\s+([\w.-]+)\s*$', text)
    if match and ' ' in text[:match.start()].strip():
        author = match.group(1)
        text = text[:match.start()]
    text = re.sub(r'(?<=[a-z]{2})(?=[A-Z][a-z])', ' ', text)
    text = re.sub(r'\b3d\b', '3D', text)
    text = re.sub(r'\s+', ' ', text).strip(' .-_,')
    return _capitalize(text) or str(raw or '').strip(), author


# ─── Metadata okuyucular ─────────────────────────────────────────────


def _tidy_sentences(text):
    text = re.sub(r'([.!?])(?=[A-ZÇĞİÖŞÜ])', r'\1 ', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def _html_to_text(value):
    text = str(value or '')
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = re.sub(r'(?is)<boostme>.*?</boostme>', ' ', text)
    text = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</h\d>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]
    return '\n'.join(line for line in lines if line).strip()


def _limit(text, max_chars=1800):
    text = str(text or '').strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rsplit(' ', 1)[0].rstrip() + '…'


_PROFILE_KEYS = r'(?:printer(?: brand| model)?|rafts?|supports?|resolution|layer height|infill|filament(?: brand| color| material)?|material|nozzle|notes?|walls?|shells?)'
_MATERIALS = r'(PLA\+?|PLA-CF|PETG-CF|PETG|ABS|ASA|TPU|NYLON|PA-CF|PC|HIPS|RESIN|SILK PLA|WOOD PLA)'


def _profile_value(text, key_pattern, value_pattern):
    """'Anahtar: değer' çiftini, değerin arkasına bitişik yazılmış bir sonraki anahtara taşmadan oku."""
    match = re.search(rf'(?i){key_pattern}\s*:\s*{value_pattern}', text)
    return match.group(1).strip() if match else ''


def extract_print_profile(text):
    """README'deki baskı ayarlarını katı desenlerle ayıkla (Thingiverse satırları bitişik olabilir)."""
    text = str(text or '')
    profile = {}
    layer = _profile_value(text, r'(?:resolution|layer height)', r'(\d+(?:[.,]\d+)?)')
    if layer:
        profile['layer_height'] = f"{layer.replace('.', ',')} mm"
    infill = _profile_value(text, r'infill', r'(\d{1,3})\s*%')
    if infill:
        profile['infill'] = f'%{infill}'
    supports = _profile_value(text, r'supports?', r"(yes|no|evet|hay[ıi]r|none|tree|doesn['’]t matter)")
    if supports:
        profile['supports'] = 'Evet' if supports.lower() in {'yes', 'evet', 'tree'} else 'Hayır'
    material = _profile_value(text, r'(?:filament material|material)', _MATERIALS)
    if material:
        profile['material'] = material.upper()
    nozzle = _profile_value(text, r'nozzle(?: size| diameter)?', r'(\d+(?:[.,]\d+)?)\s*mm')
    if nozzle:
        profile['nozzle'] = f"{nozzle.replace('.', ',')} mm"
    printer = _profile_value(text, r'printer(?: brand| model)?', rf'([A-Za-z0-9][^\n\r:]{{1,40}}?)(?={_PROFILE_KEYS}\s*:|[\n\r.]|$)')
    if printer:
        profile['printer'] = printer.strip(' ,;-')[:40]
    return profile


def parse_readme(path):
    """Thingiverse tarzı README dosyasından başlık, yazar, kaynak ve özet çıkar."""
    try:
        text = Path(path).read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return {}
    info = {}
    header = THINGIVERSE_HEADER.search(text)
    if header:
        info['title'] = header.group('title').strip()
        info['author'] = header.group('author').strip()
        info['url'] = header.group('url').rstrip(').,;')
        info['platform'] = 'Thingiverse'
        thing = re.search(r'thing:(\d+)', info['url'])
        if thing:
            info['source_id'] = thing.group(1)
    else:
        url = re.search(r'https?://\S+', text)
        if url:
            info['url'] = url.group(0).rstrip(').,;')

    summary = re.search(r'(?is)summary:\s*(.+?)(?:\n\s*(?:print settings|post-printing|how i designed this|custom section)\s*:|\Z)', text)
    body = summary.group(1) if summary else text[header.end():] if header else text
    info['summary'] = _limit(_tidy_sentences(' '.join(body.split())))

    info['print_profile'] = extract_print_profile(text)
    return info


def parse_license(path):
    """LICENSE.txt içinden lisans adı ve (varsa) tasarımcıyı çıkar."""
    try:
        text = Path(path).read_text(encoding='utf-8', errors='ignore')[:4000]
    except OSError:
        return {}
    info = {}
    match = re.search(r'licensed under\s+(.+?)(?:\.|\n|$)', text, re.IGNORECASE)
    if match:
        full = ' '.join(match.group(1).split())
        info['license_text'] = full
        lowered = full.lower()
        info['license'] = next((code for needle, code in LICENSE_CODES if needle in lowered), full[:60])
    author = re.search(r'created by (?:Thingiverse user )?(\S+?),', text)
    if author:
        info['author'] = author.group(1)
    return info


def find_3mf_preview_entry(archive):
    """3MF paketindeki en uygun gömülü önizleme görselini bul."""
    names = archive.namelist()
    name_set = set(names)
    for candidate in THREEMF_PREVIEW_CANDIDATES:
        if candidate in name_set:
            return candidate
    suffixes = ('.png', '.webp', '.jpg', '.jpeg')
    preferred = ('auxiliaries/.thumbnails/', 'metadata/', 'auxiliaries/model pictures/')
    for name in names:
        lowered = name.lower()
        if lowered.endswith(suffixes) and lowered.startswith(preferred):
            return name
    for name in names:
        if name.lower().endswith(suffixes):
            return name
    return None


def _slicer_name(application):
    app_name = str(application or '')
    lowered = app_name.lower()
    for needle, label in (
        ('bambustudio', 'Bambu Studio'), ('orcaslicer', 'OrcaSlicer'), ('creality', 'Creality Print'),
        ('prusaslicer', 'PrusaSlicer'), ('superslicer', 'SuperSlicer'), ('cura', 'Cura'),
        ('anycubic', 'Anycubic Slicer'), ('elegoo', 'ElegooSlicer'),
    ):
        if needle in lowered:
            return label
    return app_name.split('-')[0].strip()[:40] or None


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _profile_from_json(data):
    if not isinstance(data, dict):
        return {}
    profile = {}
    printer = data.get('printer_model') or data.get('printer_settings_id')
    if printer:
        profile['printer'] = str(_first(printer)).split('@')[0].strip()[:60]
    if data.get('layer_height'):
        profile['layer_height'] = f"{_first(data['layer_height'])} mm"
    if data.get('sparse_infill_density'):
        profile['infill'] = str(_first(data['sparse_infill_density']))
    if data.get('filament_type'):
        types = data['filament_type'] if isinstance(data['filament_type'], list) else [data['filament_type']]
        profile['material'] = ', '.join(dict.fromkeys(str(item) for item in types if item))[:60]
    if data.get('nozzle_diameter'):
        profile['nozzle'] = f"{_first(data['nozzle_diameter'])} mm"
    if 'enable_support' in data:
        profile['supports'] = 'Evet' if str(_first(data['enable_support'])) in {'1', 'true'} else 'Hayır'
    if data.get('wall_loops'):
        profile['walls'] = str(_first(data['wall_loops']))
    return profile


def _profile_from_ini(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r'^\s*;?\s*([a-z_]+)\s*=\s*(.+?)\s*$', line)
        if match:
            values.setdefault(match.group(1), match.group(2))
    profile = {}
    if values.get('printer_model'):
        profile['printer'] = values['printer_model'][:60]
    if values.get('layer_height'):
        profile['layer_height'] = f"{values['layer_height']} mm"
    if values.get('fill_density'):
        profile['infill'] = values['fill_density']
    if values.get('filament_type'):
        profile['material'] = values['filament_type'].split(';')[0]
    if values.get('nozzle_diameter'):
        profile['nozzle'] = f"{values['nozzle_diameter'].split(',')[0]} mm"
    if 'support_material' in values:
        profile['supports'] = 'Evet' if values['support_material'] == '1' else 'Hayır'
    return profile


def _localize_profile(profile):
    """Baskı profili değerlerini Türkçe biçime getir: 0,2 mm · %15."""
    localized = {}
    for key, value in profile.items():
        value = str(value).strip()
        if key in {'layer_height', 'nozzle'}:
            value = re.sub(r'(?<=\d)\.(?=\d)', ',', value)
        elif key == 'infill':
            number = re.search(r'\d+(?:[.,]\d+)?', value)
            value = f"%{number.group(0).replace('.', ',')}" if number else value
        localized[key] = value
    return localized


def _read_3mf_details(path):
    details = {'preview_entry': None, 'meta': {}, 'print_profile': {}}
    try:
        with zipfile.ZipFile(path) as archive:
            details['preview_entry'] = find_3mf_preview_entry(archive)
            names = {name.lower(): name for name in archive.namelist()}
            model_name = names.get('3d/3dmodel.model')
            if model_name:
                with archive.open(model_name) as stream:
                    head = stream.read(256 * 1024).decode('utf-8', errors='ignore')
                cut = head.find('<resources')
                head = head[:cut] if cut > 0 else head
                for match in re.finditer(r'<metadata\s+name="([^"]+)"[^>]*>(.*?)</metadata>', head, re.S):
                    key, value = match.group(1), match.group(2).strip()
                    if value and key not in details['meta']:
                        details['meta'][key] = value[:6000]
            settings_name = names.get('metadata/project_settings.config')
            if settings_name and archive.getinfo(settings_name).file_size < 4 * 1024 * 1024:
                try:
                    details['print_profile'] = _profile_from_json(json.loads(archive.read(settings_name)))
                except (ValueError, TypeError):
                    pass
            prusa_name = names.get('metadata/slic3r_pe.config')
            if prusa_name and not details['print_profile'] and archive.getinfo(prusa_name).file_size < 4 * 1024 * 1024:
                details['print_profile'] = _profile_from_ini(archive.read(prusa_name).decode('utf-8', 'ignore'))
    except Exception:  # noqa: BLE001 - bozuk/kötü niyetli 3MF taramayı durdurmamalı
        return details

    meta = details['meta']
    title = html.unescape(meta.get('Title', '')).strip()
    if title.lower() in {'(unsaved)', 'untitled', 'scene_mesh_textured', ''}:
        title = ''
    details['title'] = title
    details['designer'] = html.unescape(meta.get('Designer', '')).strip()
    details['description'] = _limit(_html_to_text(meta.get('Description', '')))
    license_value = html.unescape(meta.get('License', '')).strip()
    if re.fullmatch(r'(?i)by(-nc)?(-sa|-nd)?', license_value):
        license_value = 'CC ' + license_value.upper()
    details['license'] = license_value
    details['slicer'] = _slicer_name(meta.get('Application'))
    details['makerworld'] = bool(
        meta.get('DesignModelId') or meta.get('DesignProfileId') or meta.get('DesignerUserId') or meta.get('DesignerCover')
    )
    return details


def read_3mf_details(path):
    return _cached('3mf', path, _read_3mf_details) or {'preview_entry': None, 'meta': {}, 'print_profile': {}}


def _list_zip(path):
    try:
        with zipfile.ZipFile(path) as archive:
            members = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.replace('\\', '/').split('/')
                if any(is_ignored(part) for part in parts if part):
                    continue
                members.append({'member': info.filename, 'size': info.file_size})
            return members
    except Exception:  # noqa: BLE001 - bozuk zip taramayı durdurmamalı
        return None


def list_zip(path):
    return _cached('zip', path, _list_zip)


# ─── Tarama ───────────────────────────────────────────────────────────


class _Unit:
    def __init__(self, root, kind, collection=None, author=None, exclude=()):
        self.root = root
        self.kind = kind
        self.collection = collection
        self.author = author
        self.exclude = set(exclude)


def _entries(directory):
    try:
        with os.scandir(directory) as iterator:
            items = [entry for entry in iterator if not is_ignored(entry.name)]
    except OSError:
        return [], []
    files = sorted((Path(entry.path) for entry in items if entry.is_file(follow_symlinks=False)), key=lambda p: p.name.lower())
    dirs = sorted((Path(entry.path) for entry in items if entry.is_dir(follow_symlinks=False)), key=lambda p: p.name.lower())
    return files, dirs


def _has_models(directory):
    for _root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not is_ignored(name)]
        if any(Path(name).suffix.lower() in MODEL_FORMATS for name in files if not is_ignored(name)):
            return True
    return False


def _discover_directory(directory, collection=None, author=None):
    """Bir klasörü model birimlerine ayır (bkz. modül açıklaması)."""
    current = directory
    for _ in range(6):
        files, dirs = _entries(current)
        direct_models = [path for path in files if path.suffix.lower() in MODEL_FORMATS]
        model_dirs = [path for path in dirs if _has_models(path)]
        if direct_models or len(model_dirs) != 1:
            break
        child = model_dirs[0]
        if categories.is_generic_dir_name(child.name):
            break
        if WRAPPER_SUFFIX.search(current.name):
            grandchildren = [path for path in _entries(child)[1] if _has_models(path)]
            child_models = [path for path in _entries(child)[0] if path.suffix.lower() in MODEL_FORMATS]
            if len(grandchildren) == 1 and not child_models and author is None:
                author = child.name
        current = child
    else:
        files, dirs = _entries(current)
        direct_models = [path for path in files if path.suffix.lower() in MODEL_FORMATS]
        model_dirs = [path for path in dirs if _has_models(path)]

    generic = [path for path in model_dirs if categories.is_generic_dir_name(path.name)]
    meaningful = [path for path in model_dirs if path not in generic]

    if not direct_models and not generic:
        if len(meaningful) >= 2:
            collection_name = collection or clean_title(current.name)[0]
            units = []
            for sub in meaningful:
                units.extend(_discover_directory(sub, collection=collection_name, author=author))
            return units
        return []

    separate = [path for path in meaningful if WRAPPER_SUFFIX.search(path.name)]
    units = [_Unit(current, 'folder', collection=collection, author=author, exclude=separate)]
    for sub in separate:
        units.extend(_discover_directory(sub, collection=collection))
    return units


def discover_units(models_dir):
    """Kütüphane kökünü model birimlerine ayır."""
    models_dir = Path(models_dir)
    if not models_dir.is_dir():
        return [], {}
    root_files, root_dirs = _entries(models_dir)
    units = []
    for path in root_files:
        if path.suffix.lower() in MODEL_FORMATS:
            units.append(_Unit(path, 'file'))
    dir_names = {path.name.lower() for path in root_dirs}
    root_archives = {}
    for path in root_files:
        if path.suffix.lower() != '.zip':
            continue
        if path.stem.lower() in dir_names:
            root_archives[path.stem.lower()] = path
            continue
        members = list_zip(path) or []
        if any(Path(item['member']).suffix.lower() in MODEL_FORMATS for item in members):
            units.append(_Unit(path, 'archive'))
    for path in root_dirs:
        units.extend(_discover_directory(path))
    return units, root_archives


def _rel(models_dir, path):
    return Path(path).relative_to(models_dir).as_posix()


def _entry(models_dir, path, stat=None):
    try:
        stat = stat or path.stat()
    except OSError:
        return None
    kind = file_kind(path.name)
    if kind is None:
        return None
    return {
        'path': _rel(models_dir, path),
        'name': path.name,
        'size': stat.st_size,
        'format': path.suffix.lower().lstrip('.'),
        'kind': kind,
        'modified': stat.st_mtime,
    }


def _collect_unit_entries(models_dir, unit, root_files):
    entries = []
    if unit.kind == 'file':
        entries.append(_entry(models_dir, unit.root))
        stem = unit.root.stem.lower()
        for sibling in root_files:
            if sibling != unit.root and sibling.stem.lower() == stem and sibling.suffix.lower() not in MODEL_FORMATS:
                entries.append(_entry(models_dir, sibling))
    elif unit.kind == 'archive':
        stat = unit.root.stat()
        rel = _rel(models_dir, unit.root)
        for item in list_zip(unit.root) or []:
            kind = file_kind(Path(item['member']).name)
            if kind is None or kind == 'archive':
                continue
            entries.append({
                'path': rel,
                'member': item['member'],
                'name': Path(item['member']).name,
                'size': item['size'],
                'format': Path(item['member']).suffix.lower().lstrip('.'),
                'kind': kind,
                'modified': stat.st_mtime,
            })
        entries.append(_entry(models_dir, unit.root, stat))
    else:
        excluded = {str(path) for path in unit.exclude}
        for root, dirs, files in os.walk(unit.root):
            dirs[:] = sorted(name for name in dirs if not is_ignored(name) and str(Path(root) / name) not in excluded)
            for name in sorted(files, key=str.lower):
                if not is_ignored(name):
                    entries.append(_entry(models_dir, Path(root) / name))
    return [entry for entry in entries if entry]


def _choose_main(model_entries, details_for, title=''):
    title_tokens = {token for token in categories.tokenize(title) if len(token) >= 3 and not token.isdigit()}

    def sort_key(entry):
        has_preview = entry['format'] == '3mf' and not entry.get('member') and bool(details_for(entry).get('preview_entry'))
        stem_tokens = set(categories.tokenize(Path(entry['name']).stem))
        shares_name = bool(title_tokens & stem_tokens)
        if stem_tokens & MAIN_PART_WORDS:
            role = 0
        elif stem_tokens & MINOR_PART_WORDS:
            role = 2
        else:
            role = 1
        return (
            0 if shares_name else 1,
            MAIN_FORMAT_PRIORITY.get(entry['format'], 99),
            0 if has_preview else 1,
            role,
            -entry['size'],
            entry['name'].lower(),
        )
    return min(model_entries, key=sort_key)


def _choose_cover_image(images):
    def score(entry):
        name = entry['name'].lower()
        bonus = 0 if re.search(r'cover|thumb|preview|render|main|hero', name) else 1
        return (bonus, entry['path'].count('/'), entry['name'].lower())
    return min(images, key=score) if images else None


def build_record(models_dir, unit, root_files, root_archives, archive_units=()):
    """Bir model birimi için katalog kaydı üret."""
    models_dir = Path(models_dir)
    entries = _collect_unit_entries(models_dir, unit, [path for path in root_files if path not in archive_units])
    if unit.kind == 'folder' and unit.root.parent == models_dir:
        archive = root_archives.get(unit.root.name.lower())
        if archive is not None:
            extra = _entry(models_dir, archive)
            if extra:
                entries.append(extra)

    model_entries = [entry for entry in entries if entry['kind'] == 'model']
    if not model_entries:
        return None

    rel_root = _rel(models_dir, unit.root)
    model_id = generate_id(rel_root)
    raw_name = unit.root.name if unit.kind == 'folder' else unit.root.name
    title, slug_author = clean_title(raw_name, is_file=unit.kind != 'folder')

    def details_for(entry):
        if entry['format'] != '3mf' or entry.get('member'):
            return {}
        return read_3mf_details(models_dir / entry['path'])

    main = _choose_main(model_entries, details_for, title)
    main_details = details_for(main)

    # "v29" gibi sürüm adlı klasörlerde ve "Holder" gibi tek kelimelik dosyalarda daha açıklayıcı başlık bul.
    if re.fullmatch(r'(?i)v?\d+(\.\d+)*[a-z]?', raw_name.strip()):
        title = clean_title(main['name'], is_file=True)[0]
    elif unit.kind == 'file' and main_details.get('title') and len(categories.tokenize(title)) <= 1:
        title = main_details['title']

    readme_entry = next((entry for entry in entries if entry['kind'] == 'readme' and not entry.get('member')), None)
    license_entry = next((entry for entry in entries if entry['kind'] == 'license' and not entry.get('member')), None)
    readme = _cached('readme', models_dir / readme_entry['path'], parse_readme) if readme_entry else {}
    license_info = _cached('license', models_dir / license_entry['path'], parse_license) if license_entry else {}
    readme = readme or {}
    license_info = license_info or {}
    if readme.get('source_id'):
        # "Gear Set - 123" → README thing:123 ile doğrulanan kimliği başlıktan at.
        title = re.sub(rf"\s+-\s+{re.escape(readme['source_id'])}(?=\s+-\s+|\s*$)", '', title).strip() or title

    threemf = [details_for(entry) for entry in model_entries if entry['format'] == '3mf' and not entry.get('member')]
    designer = next((item.get('designer') for item in [main_details, *threemf] if item.get('designer')), '')
    description_3mf = next((item.get('description') for item in [main_details, *threemf] if item.get('description')), '')
    title_3mf = next((item.get('title') for item in [main_details, *threemf] if item.get('title')), '')

    source_url, platform, source_id = readme.get('url', ''), readme.get('platform'), readme.get('source_id')
    for entry in entries:
        match = PRINTABLES_PDF.match(entry['name']) if entry['format'] == 'pdf' else None
        if match and not source_url:
            source_id = match.group('id')
            source_url = f"https://www.printables.com/model/{source_id}-{match.group('slug')}"
            platform = 'Printables'
    if not platform and any(item.get('makerworld') for item in [main_details, *threemf]):
        platform = 'MakerWorld'
    if not platform and raw_name.lower().endswith('model_files'):
        platform = 'Printables'

    author = readme.get('author') or license_info.get('author') or designer or unit.author or slug_author or ''
    license_value = license_info.get('license') or next((item.get('license') for item in threemf if item.get('license')), '')
    description = readme.get('summary') or description_3mf or ''

    print_profile = dict(main_details.get('print_profile') or {})
    for key, value in (readme.get('print_profile') or {}).items():
        print_profile.setdefault(key, value)
    print_profile = _localize_profile(print_profile)
    slicer = main_details.get('slicer') or next((item.get('slicer') for item in threemf if item.get('slicer')), None)

    images = [entry for entry in entries if entry['kind'] == 'image']
    cover = _choose_cover_image(images)
    formats = sorted({entry['format'] for entry in model_entries}, key=lambda value: MAIN_FORMAT_PRIORITY.get(value, 99))
    file_names = ' '.join(Path(entry['name']).stem for entry in model_entries[:60])
    readme_title = readme.get('title', '')

    sources = [
        (title, 3.0, None),
        (readme_title if readme_title and readme_title.lower() != title.lower() else '', 1.5, None),
        (unit.collection or '', 3.0, None),
        (file_names, 1.2, 7.0),
        (title_3mf, 2.0, 12.0),
        (description, 0.35, 3.0),
    ]
    category, scores = categories.classify(sources)

    extra_tags = []
    if any(entry['format'] in {'scad', 'f3d', 'fcstd'} for entry in entries) or 'parametric' in categories.fold(file_names + ' ' + title):
        extra_tags.append('Parametrik')
    supports = str(print_profile.get('supports', '')).lower()
    if supports in {'no', 'hayır', 'none'}:
        extra_tags.append('Desteksiz')
    tag_texts = [title, raw_name, readme_title, file_names, title_3mf, description[:400]]
    tags = categories.auto_tags(tag_texts, extra_tags)
    all_names = ' '.join(Path(entry.get('member') or entry['name']).name for entry in entries)
    nsfw = categories.is_nsfw([title, raw_name, readme_title, title_3mf, unit.collection or '', all_names])
    if nsfw:
        category = 'figure'
        tags = [tag for tag in tags if tag not in categories.CHILD_BRAND_TAGS]

    size = sum(entry['size'] for entry in entries if not (entry.get('member') is None and entry['kind'] == 'archive' and unit.kind == 'archive'))
    if unit.kind == 'archive':
        size = next((entry['size'] for entry in entries if entry['kind'] == 'archive' and not entry.get('member')), size)
    modified = max(entry['modified'] for entry in entries)
    oldest = min(entry['modified'] for entry in entries)

    if cover:
        thumb = {'kind': 'image', 'path': cover['path'], 'member': cover.get('member')}
    elif main_details.get('preview_entry'):
        thumb = {'kind': '3mf', 'path': main['path'], 'entry': main_details['preview_entry']}
    elif main['format'] in {'stl', '3mf', 'obj', 'ply'}:
        thumb = {'kind': 'mesh', 'path': main['path'], 'member': main.get('member')}
    else:
        thumb = None
    stats_source = {'path': main['path'], 'member': main.get('member')} if main['format'] in {'stl', '3mf', 'obj', 'ply'} else None

    search_text = categories.fold(' '.join(filter(None, [
        title, raw_name, readme_title, title_3mf, author, unit.collection or '', file_names,
        ' '.join(tags), description[:300],
    ])))

    return {
        'id': model_id,
        'kind': unit.kind,
        'path': rel_root,
        'title': title,
        'raw_name': raw_name,
        'original_title': readme_title or title_3mf or '',
        'collection': unit.collection,
        'collection_id': generate_id('collection:' + unit.collection) if unit.collection else None,
        'auto_category': category,
        'auto_tags': tags,
        'auto_nsfw': nsfw,
        'category_scores': {key: round(value, 2) for key, value in sorted(scores.items(), key=lambda kv: -kv[1])[:3] if value},
        'author': author,
        'license': license_value,
        'license_text': license_info.get('license_text', ''),
        'source_url': source_url,
        'source_platform': platform,
        'source_id': source_id,
        'description': description,
        'print_profile': print_profile,
        'slicer': slicer,
        'main': {'path': main['path'], 'member': main.get('member'), 'name': main['name'], 'format': main['format']},
        'formats': formats,
        'files': model_entries,
        'assets': [entry for entry in entries if entry['kind'] != 'model'],
        'readme': readme_entry['path'] if readme_entry else None,
        'license_file': license_entry['path'] if license_entry else None,
        'file_count': len(model_entries),
        'asset_count': len(entries) - len(model_entries),
        'image_count': len(images),
        'size': size,
        'modified': modified,
        'file_date': oldest,
        'thumb_source': thumb,
        'stats_source': stats_source,
        'search': search_text,
    }


def scan_library(models_dir):
    """Tüm kütüphaneyi tarayıp {model_id: kayıt} döndür."""
    models_dir = Path(models_dir)
    units, root_archives = discover_units(models_dir)
    root_files, _ = _entries(models_dir) if models_dir.is_dir() else ([], [])
    catalog = {}
    archive_units = {unit.root for unit in units if unit.kind == 'archive'}
    for unit in units:
        try:
            record = build_record(models_dir, unit, root_files, root_archives, archive_units)
        except Exception:  # noqa: BLE001 - tek bir bozuk model tüm kataloğu düşürmemeli
            log.exception('Model taranamadı, atlanıyor: %s', unit.root)
            continue
        if record is not None:
            catalog[record['id']] = record
    return catalog


def library_signature(models_dir):
    """Dosya sistemindeki değişiklikleri ucuzca tespit etmek için imza üret."""
    digest = hashlib.md5()
    models_dir = Path(models_dir)
    if not models_dir.is_dir():
        return ''
    for root, dirs, files in os.walk(models_dir):
        dirs[:] = sorted(name for name in dirs if not is_ignored(name))
        for name in sorted(files):
            if is_ignored(name):
                continue
            try:
                stat = os.stat(os.path.join(root, name))
            except OSError:
                continue
            digest.update(f'{root}/{name}:{stat.st_size}:{stat.st_mtime_ns}\n'.encode('utf-8', 'surrogateescape'))
    return digest.hexdigest()
