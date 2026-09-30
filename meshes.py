"""
Mesh okuma, ölçü hesaplama ve sunucu tarafı küçük resim üretimi.

Sadece numpy ve Pillow kullanır; GPU veya OpenGL gerektirmez. Büyük dosyalar
parça parça işlenir, böylece 250 MB'lık bir STL bile birkaç yüz MB bellekle
render edilebilir.
"""

import math
import re
import xml.etree.ElementTree as ET
import zipfile
from array import array
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RENDERABLE_FORMATS = {'.stl', '.3mf', '.obj', '.ply'}
CHUNK_TRIANGLES = 200_000
MAX_3MF_XML_BYTES = 400 * 1024 * 1024
STL_RECORD = np.dtype([
    ('normal', '<f4', (3,)),
    ('vertices', '<f4', (3, 3)),
    ('attr', '<u2'),
])

# Görsel ayarlar: marka rengiyle uyumlu mor-mavi bir "stüdyo" görünümü.
BASE_COLOR = np.array([0.40, 0.42, 0.98], dtype=np.float32)
SPECULAR_COLOR = np.array([1.0, 1.0, 1.0], dtype=np.float32)
OUTLINE_STRENGTH = 0.55


class MeshError(Exception):
    """Mesh okunamadığında veya boş olduğunda fırlatılır."""


# ─── Okuyucular ───────────────────────────────────────────────────────


def iter_triangle_chunks(path, chunk=CHUNK_TRIANGLES, mesh=None):
    """Dosyadaki üçgenleri (n, 3, 3) float32 dizileri halinde üret."""
    if mesh is not None:
        yield from _iter_indexed(mesh, chunk)
        return
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.stl':
        yield from _iter_stl(path, chunk)
    elif suffix == '.3mf':
        yield from _iter_indexed(_load_3mf(path), chunk)
    elif suffix == '.obj':
        yield from _iter_indexed(_load_obj(path), chunk)
    elif suffix == '.ply':
        yield from _iter_indexed(_load_ply(path), chunk)
    else:
        raise MeshError(f'Desteklenmeyen format: {suffix}')


def _stl_is_binary(path):
    size = path.stat().st_size
    if size < 84:
        return False
    with open(path, 'rb') as handle:
        header = handle.read(84)
    count = int.from_bytes(header[80:84], 'little')
    expected = 84 + count * STL_RECORD.itemsize
    if count > 0 and expected <= size <= expected + 4096:
        return True
    return not header[:5].lower().startswith(b'solid')


def _iter_stl(path, chunk):
    if _stl_is_binary(path):
        with open(path, 'rb') as handle:
            handle.seek(80)
            count = int.from_bytes(handle.read(4), 'little')
        available = (path.stat().st_size - 84) // STL_RECORD.itemsize
        count = min(count, available)
        if count <= 0:
            raise MeshError('STL dosyasında üçgen yok')
        records = np.memmap(path, dtype=STL_RECORD, mode='r', offset=84, shape=(count,))
        try:
            for start in range(0, count, chunk):
                yield np.array(records['vertices'][start:start + chunk], dtype=np.float32)
        finally:
            del records
        return

    yield from _iter_ascii_stl(path, chunk)


_ASCII_VERTEX = re.compile(rb'vertex\s+(\S+)\s+(\S+)\s+(\S+)', re.IGNORECASE)


def _iter_ascii_stl(path, chunk):
    block_size = 8 * 1024 * 1024
    pending = np.empty((0, 3), dtype=np.float32)
    tail = b''
    produced = False
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(block_size)
            data = tail + block
            if block:
                cut = data.rfind(b'\n')
                if cut == -1:
                    tail = data
                    continue
                data, tail = data[:cut], data[cut:]
            else:
                tail = b''
            matches = _ASCII_VERTEX.findall(data)
            if matches:
                values = np.array(matches, dtype='S32').astype(np.float32)
                pending = np.concatenate([pending, values]) if len(pending) else values
                usable = (len(pending) // 3) * 3
                triangles = pending[:usable].reshape(-1, 3, 3)
                pending = pending[usable:]
                for start in range(0, len(triangles), chunk):
                    produced = True
                    yield triangles[start:start + chunk]
            if not block:
                break
    if not produced:
        raise MeshError('ASCII STL içinde üçgen bulunamadı')


def _iter_indexed(mesh, chunk):
    vertices, faces = mesh
    if len(vertices) == 0 or len(faces) == 0:
        raise MeshError('Mesh boş')
    for start in range(0, len(faces), chunk):
        yield vertices[faces[start:start + chunk]]


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _parse_transform(value):
    if not value:
        return None
    try:
        numbers = [float(item) for item in value.split()]
    except ValueError:
        return None
    if len(numbers) != 12:
        return None
    linear = np.array(numbers[:9], dtype=np.float64).reshape(3, 3)
    offset = np.array(numbers[9:], dtype=np.float64)
    return linear, offset


def _compose(inner, outer):
    """Önce inner sonra outer uygulanan dönüşümü döndür (satır vektörü)."""
    if inner is None:
        return outer
    if outer is None:
        return inner
    return inner[0] @ outer[0], inner[1] @ outer[0] + outer[1]


def _parse_3mf_objects(stream):
    objects = {}
    build = []
    current = None
    vertices = triangles = None
    for event, element in ET.iterparse(stream, events=('start', 'end')):
        name = _local(element.tag)
        if event == 'start':
            if name == 'object':
                current = {'id': element.get('id'), 'mesh': None, 'components': []}
            elif name == 'mesh' and current is not None:
                vertices, triangles = array('f'), array('i')
            continue

        if name == 'vertex' and vertices is not None:
            vertices.extend((float(element.get('x', 0)), float(element.get('y', 0)), float(element.get('z', 0))))
        elif name == 'triangle' and triangles is not None:
            triangles.extend((int(element.get('v1', 0)), int(element.get('v2', 0)), int(element.get('v3', 0))))
        elif name == 'mesh' and current is not None and vertices is not None:
            current['mesh'] = (
                np.frombuffer(vertices, dtype=np.float32).reshape(-1, 3),
                np.frombuffer(triangles, dtype=np.int32).reshape(-1, 3),
            )
            vertices = triangles = None
        elif name == 'component' and current is not None:
            path_value = next((value for key, value in element.attrib.items() if _local(key) == 'path'), '')
            current['components'].append((element.get('objectid'), _parse_transform(element.get('transform')), path_value))
        elif name == 'object' and current is not None:
            objects[current['id']] = current
            current = None
        elif name == 'item':
            path_value = next((value for key, value in element.attrib.items() if _local(key) == 'path'), '')
            build.append((element.get('objectid'), _parse_transform(element.get('transform')), path_value))
        element.clear()
    return objects, build


def _load_3mf(path):
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise MeshError(f'3MF açılamadı: {exc}') from exc

    with archive:
        names = {name.lower(): name for name in archive.namelist()}
        root_name = names.get('3d/3dmodel.model')
        if root_name is None:
            candidates = [name for key, name in names.items() if key.endswith('.model')]
            if not candidates:
                raise MeshError('3MF içinde model bulunamadı')
            root_name = candidates[0]

        total_xml = sum(info.file_size for info in archive.infolist() if info.filename.lower().endswith('.model'))
        if total_xml > MAX_3MF_XML_BYTES:
            raise MeshError('3MF modeli sunucuda işlenemeyecek kadar büyük')

        cache = {}

        def objects_for(model_path):
            key = (model_path or '/' + root_name).lstrip('/').lower()
            if key not in cache:
                real_name = names.get(key)
                if real_name is None:
                    cache[key] = ({}, [])
                else:
                    with archive.open(real_name) as stream:
                        cache[key] = _parse_3mf_objects(stream)
            return cache[key]

        root_objects, build = objects_for(None)
        vertex_parts, face_parts = [], []
        offset = 0

        def emit(objects, object_id, transform, depth=0):
            nonlocal offset
            if depth > 8:
                return
            obj = objects.get(object_id)
            if obj is None:
                return
            if obj['mesh'] is not None:
                verts, faces = obj['mesh']
                if len(verts) and len(faces):
                    verts = verts.astype(np.float64)
                    if transform is not None:
                        verts = verts @ transform[0] + transform[1]
                    valid = (faces >= 0).all(axis=1) & (faces < len(verts)).all(axis=1)
                    vertex_parts.append(verts.astype(np.float32))
                    face_parts.append(faces[valid] + offset)
                    offset += len(verts)
            for component_id, component_transform, component_path in obj['components']:
                child_objects = objects_for(component_path)[0] if component_path else objects
                emit(child_objects, component_id, _compose(component_transform, transform), depth + 1)

        items = build or [(object_id, None, '') for object_id in root_objects]
        for object_id, transform, item_path in items:
            emit(objects_for(item_path)[0] if item_path else root_objects, object_id, transform)

    if not vertex_parts:
        raise MeshError('3MF içinde mesh bulunamadı')
    return np.concatenate(vertex_parts), np.concatenate(face_parts)


def _load_obj(path):
    vertices = array('f')
    faces = array('i')
    vertex_count = 0
    with open(path, 'rb') as handle:
        for raw_line in handle:
            if raw_line.startswith(b'v '):
                parts = raw_line.split()
                if len(parts) >= 4:
                    vertices.extend((float(parts[1]), float(parts[2]), float(parts[3])))
                    vertex_count += 1
            elif raw_line.startswith(b'f '):
                indices = []
                for part in raw_line.split()[1:]:
                    token = part.split(b'/', 1)[0]
                    if not token:
                        continue
                    index = int(token)
                    indices.append(index - 1 if index > 0 else vertex_count + index)
                for i in range(1, len(indices) - 1):
                    faces.extend((indices[0], indices[i], indices[i + 1]))
    verts = np.frombuffer(vertices, dtype=np.float32).reshape(-1, 3)
    tris = np.frombuffer(faces, dtype=np.int32).reshape(-1, 3)
    valid = (tris >= 0).all(axis=1) & (tris < len(verts)).all(axis=1)
    return verts, tris[valid]


_PLY_TYPES = {
    'char': 'i1', 'int8': 'i1', 'uchar': 'u1', 'uint8': 'u1',
    'short': 'i2', 'int16': 'i2', 'ushort': 'u2', 'uint16': 'u2',
    'int': 'i4', 'int32': 'i4', 'uint': 'u4', 'uint32': 'u4',
    'float': 'f4', 'float32': 'f4', 'double': 'f8', 'float64': 'f8',
}


def _load_ply(path):
    with open(path, 'rb') as handle:
        if handle.readline().strip() != b'ply':
            raise MeshError('Geçersiz PLY dosyası')
        fmt = None
        elements = []
        while True:
            line = handle.readline()
            if not line:
                raise MeshError('PLY başlığı tamamlanmamış')
            parts = line.decode('ascii', 'ignore').split()
            if not parts:
                continue
            if parts[0] == 'format':
                fmt = parts[1]
            elif parts[0] == 'element':
                elements.append({'name': parts[1], 'count': int(parts[2]), 'props': []})
            elif parts[0] == 'property' and elements:
                elements[-1]['props'].append(parts[1:])
            elif parts[0] == 'end_header':
                break
        data = handle.read()

    vertex_el = next((el for el in elements if el['name'] == 'vertex'), None)
    face_el = next((el for el in elements if el['name'] == 'face'), None)
    if vertex_el is None or face_el is None:
        raise MeshError('PLY içinde vertex/face bulunamadı')

    if fmt == 'ascii':
        tokens = data.split()
        cursor = 0
        verts = np.zeros((vertex_el['count'], 3), dtype=np.float32)
        faces = array('i')
        for el in elements:
            for row in range(el['count']):
                values = {}
                for prop in el['props']:
                    if prop[0] == 'list':
                        n = int(tokens[cursor])
                        cursor += 1
                        values[prop[-1]] = [int(float(tok)) for tok in tokens[cursor:cursor + n]]
                        cursor += n
                    else:
                        values[prop[-1]] = float(tokens[cursor])
                        cursor += 1
                if el is vertex_el:
                    verts[row] = (values.get('x', 0), values.get('y', 0), values.get('z', 0))
                elif el is face_el:
                    idx = values.get('vertex_indices') or values.get('vertex_index') or []
                    for i in range(1, len(idx) - 1):
                        faces.extend((idx[0], idx[i], idx[i + 1]))
        tris = np.frombuffer(faces, dtype=np.int32).reshape(-1, 3)
        return verts, tris

    endian = '<' if fmt == 'binary_little_endian' else '>'
    cursor = 0
    verts = tris = None
    for el in elements:
        if all(prop[0] != 'list' for prop in el['props']):
            dtype = np.dtype([(prop[1], endian + _PLY_TYPES[prop[0]]) for prop in el['props']])
            block = np.frombuffer(data, dtype=dtype, count=el['count'], offset=cursor)
            cursor += dtype.itemsize * el['count']
            if el is vertex_el:
                verts = np.stack([block['x'], block['y'], block['z']], axis=1).astype(np.float32)
            continue

        if el is not face_el or len(el['props']) != 1:
            raise MeshError('Desteklenmeyen PLY yapısı')
        _, count_type, index_type, _ = el['props'][0]
        count_dtype = np.dtype(endian + _PLY_TYPES[count_type])
        index_dtype = np.dtype(endian + _PLY_TYPES[index_type])
        tri_dtype = np.dtype([('n', count_dtype), ('i', index_dtype, (3,))])
        block = np.frombuffer(data, dtype=tri_dtype, count=el['count'], offset=cursor)
        if not (block['n'] == 3).all():
            raise MeshError('PLY yalnızca üçgen yüzlerle destekleniyor')
        cursor += tri_dtype.itemsize * el['count']
        tris = block['i'].astype(np.int32)

    if verts is None or tris is None:
        raise MeshError('PLY okunamadı')
    return verts, tris


# ─── Kompakt mesh (tarayıcı için) ─────────────────────────────────────

INDEXED_FORMATS = {'.3mf', '.obj', '.ply'}
COMPACT_MAGIC = b'M3DB'
COMPACT_VERSION = 1


def load_indexed(path):
    """3MF/OBJ/PLY dosyasını (köşeler, yüzler) olarak yükle."""
    suffix = Path(path).suffix.lower()
    if suffix == '.3mf':
        return _load_3mf(path)
    if suffix == '.obj':
        return _load_obj(path)
    if suffix == '.ply':
        return _load_ply(path)
    raise MeshError(f'İndeksli yükleme desteklenmiyor: {suffix}')


def write_compact(mesh, output):
    """Köşe ve indeksleri küçük bir ikili dosyaya yaz: M3DB | sürüm | köşe | indeks | veri."""
    vertices, faces = mesh
    vertices = np.ascontiguousarray(vertices, dtype='<f4')
    faces = np.ascontiguousarray(faces, dtype='<u4')
    if not len(vertices) or not len(faces):
        raise MeshError('Mesh boş')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix('.tmp')
    header = COMPACT_MAGIC + np.array([COMPACT_VERSION, len(vertices), faces.size], dtype='<u4').tobytes()
    with open(tmp, 'wb') as handle:
        handle.write(header)
        handle.write(vertices.tobytes())
        handle.write(faces.tobytes())
    tmp.replace(output)


# ─── Ölçü ve render ───────────────────────────────────────────────────


def up_axis_for(path):
    """3D baskı formatları Z-yukarı, OBJ genelde Y-yukarı kaydedilir."""
    return 'y' if Path(path).suffix.lower() == '.obj' else 'z'


def _view_rotation(up='z', azimuth_deg=-38.0, elevation_deg=26.0):
    """Dünya koordinatını kamera koordinatına çeviren matris."""
    if up == 'y':
        to_y_up = np.eye(3)
    else:
        to_y_up = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    rot_y = np.array([[math.cos(az), 0, math.sin(az)], [0, 1, 0], [-math.sin(az), 0, math.cos(az)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(el), -math.sin(el)], [0, math.sin(el), math.cos(el)]])
    return rot_x @ rot_y @ to_y_up


def analyze_mesh(path, mesh=None):
    """Üçgen sayısı, sınır kutusu ve hacmi tek geçişte hesapla."""
    rotation = _view_rotation(up_axis_for(path))
    count = 0
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    view_lo = np.full(3, np.inf)
    view_hi = np.full(3, -np.inf)
    volume = 0.0
    for tris in iter_triangle_chunks(path, mesh=mesh):
        finite = np.isfinite(tris).all(axis=(1, 2))
        tris = tris[finite]
        if not len(tris):
            continue
        count += len(tris)
        flat = tris.reshape(-1, 3)
        lo = np.minimum(lo, flat.min(axis=0))
        hi = np.maximum(hi, flat.max(axis=0))
        view = flat.astype(np.float64) @ rotation.T
        view_lo = np.minimum(view_lo, view.min(axis=0))
        view_hi = np.maximum(view_hi, view.max(axis=0))
        t64 = tris.astype(np.float64)
        volume += float(np.einsum('ij,ij->i', t64[:, 0], np.cross(t64[:, 1], t64[:, 2])).sum()) / 6.0

    if count == 0 or not np.isfinite(lo).all():
        raise MeshError('Mesh boş veya geçersiz')

    size = hi - lo
    return {
        'triangles': int(count),
        'size_mm': [round(float(value), 2) for value in size],
        'volume_cm3': round(abs(volume) / 1000.0, 2),
        '_bounds': (lo, hi),
        '_view_bounds': (view_lo, view_hi),
    }


def _shade(normals):
    """Yüzey normallerinden diffuse ve specular yoğunluk üret (iki taraflı)."""
    lengths = np.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1.0
    n = normals / lengths[:, None]
    n *= np.where(n[:, 2:3] < 0, -1.0, 1.0)

    key = np.array([-0.45, 0.75, 0.55])
    key /= np.linalg.norm(key)
    fill = np.array([0.8, 0.1, 0.45])
    fill /= np.linalg.norm(fill)
    half = key + np.array([0.0, 0.0, 1.0])
    half /= np.linalg.norm(half)

    diffuse = (
        0.30
        + 0.12 * n[:, 1]
        + 0.62 * np.clip(n @ key, 0, None)
        + 0.18 * np.clip(n @ fill, 0, None)
        + 0.10 * (1 - np.abs(n[:, 2])) ** 2
    )
    specular = 0.32 * np.clip(n @ half, 0, None) ** 40
    return diffuse.astype(np.float32), specular.astype(np.float32)


class _Canvas:
    """Z-buffer tutan basit bir yazılım rasterleştirici."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.depth = np.full(width * height, -np.inf, dtype=np.float32)
        self.diffuse = np.zeros(width * height, dtype=np.float32)
        self.specular = np.zeros(width * height, dtype=np.float32)

    def merge(self, pixels, depth, diffuse, specular):
        if not len(pixels):
            return
        order = np.lexsort((-depth, pixels))
        pixels = pixels[order]
        first = np.ones(len(pixels), dtype=bool)
        first[1:] = pixels[1:] != pixels[:-1]
        pixels = pixels[first]
        depth = depth[order][first]
        better = depth > self.depth[pixels]
        target = pixels[better]
        self.depth[target] = depth[better]
        self.diffuse[target] = diffuse[order][first][better]
        self.specular[target] = specular[order][first][better]

    def rasterize(self, screen, diffuse, specular):
        """screen: (n, 3, 3) piksel x, piksel y, derinlik."""
        xs, ys, zs = screen[:, :, 0], screen[:, :, 1], screen[:, :, 2]
        x_min = np.floor(xs.min(axis=1)).astype(np.int64)
        y_min = np.floor(ys.min(axis=1)).astype(np.int64)
        span = np.maximum(
            np.ceil(xs.max(axis=1)).astype(np.int64) - x_min,
            np.ceil(ys.max(axis=1)).astype(np.int64) - y_min,
        )

        # Çok küçük üçgenler: ağırlık merkezini tek piksel olarak işle (delik kalmasın).
        tiny = span <= 1
        if tiny.any():
            cx = xs[tiny].mean(axis=1).astype(np.int64)
            cy = ys[tiny].mean(axis=1).astype(np.int64)
            cz = zs[tiny].max(axis=1)
            self._merge_points(cx, cy, cz, diffuse[tiny], specular[tiny])

        # Orta boy üçgenler: aynı boyuttaki ızgaralarla toplu (vektörel) işle.
        lower = 1
        for upper, batch in ((2, 60_000), (4, 30_000), (8, 8_000), (16, 2_000), (32, 500), (64, 120)):
            selected = np.nonzero((span > lower) & (span <= upper))[0]
            for start in range(0, len(selected), batch):
                idx = selected[start:start + batch]
                self._rasterize_grid(screen[idx], x_min[idx], y_min[idx], upper + 1, diffuse[idx], specular[idx])
            lower = upper

        # Büyük üçgenler (düşük poligonlu modeller): tek tek işle.
        for idx in np.nonzero(span > lower)[0]:
            one = slice(idx, idx + 1)
            self._rasterize_grid(screen[one], x_min[one], y_min[one], int(span[idx]) + 1, diffuse[one], specular[one])

    def _merge_points(self, x, y, z, diffuse, specular):
        inside = (x >= 0) & (x < self.width) & (y >= 0) & (y < self.height)
        self.merge((y[inside] * self.width + x[inside]), z[inside].astype(np.float32), diffuse[inside], specular[inside])

    def _rasterize_grid(self, screen, x_min, y_min, size, diffuse, specular):
        offsets = np.arange(size)
        grid_x = (x_min[:, None, None] + offsets[None, None, :]).astype(np.float32)
        grid_y = (y_min[:, None, None] + offsets[None, :, None]).astype(np.float32)
        px = grid_x + 0.5
        py = grid_y + 0.5

        x0, y0, z0 = (screen[:, 0, k][:, None, None] for k in range(3))
        x1, y1, z1 = (screen[:, 1, k][:, None, None] for k in range(3))
        x2, y2, z2 = (screen[:, 2, k][:, None, None] for k in range(3))
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        valid_area = np.abs(area) > 1e-9
        safe_area = np.where(valid_area, area, 1.0)
        w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / safe_area
        w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / safe_area
        w2 = 1.0 - w0 - w1
        eps = -1e-4
        inside = (w0 >= eps) & (w1 >= eps) & (w2 >= eps) & valid_area
        inside &= (grid_x >= 0) & (grid_x < self.width) & (grid_y >= 0) & (grid_y < self.height)

        tri_index = np.broadcast_to(np.arange(len(screen))[:, None, None], inside.shape)[inside]
        pixels = (grid_y.astype(np.int64) * self.width + grid_x.astype(np.int64))
        pixels = np.broadcast_to(pixels, inside.shape)[inside]
        depth = (w0 * z0 + w1 * z1 + w2 * z2)[inside].astype(np.float32)
        self.merge(pixels, depth, diffuse[tri_index], specular[tri_index])

        # Kenarları kaçan ince üçgenler için ağırlık merkezi yedeği.
        covered = inside.reshape(len(screen), -1).any(axis=1)
        if not covered.all():
            missing = ~covered
            cx = screen[missing, :, 0].mean(axis=1).astype(np.int64)
            cy = screen[missing, :, 1].mean(axis=1).astype(np.int64)
            cz = screen[missing, :, 2].max(axis=1)
            self._merge_points(cx, cy, cz, diffuse[missing], specular[missing])


def render_mesh(path, width=640, height=480, supersample=2, analysis=None, mesh=None):
    """Mesh'i şeffaf arka planlı RGBA PIL görseli olarak render et."""
    analysis = analysis or analyze_mesh(path, mesh=mesh)
    rotation = _view_rotation(up_axis_for(path))
    lo, hi = analysis['_bounds']
    view_lo, view_hi = analysis['_view_bounds']

    render_w, render_h = width * supersample, height * supersample
    margin = 0.1
    extent_x = max(view_hi[0] - view_lo[0], 1e-6)
    extent_y = max(view_hi[1] - view_lo[1], 1e-6)
    shadow_room = 0.06
    scale = min(render_w * (1 - 2 * margin) / extent_x, render_h * (1 - 2 * margin - shadow_room) / extent_y)
    offset_x = (render_w - extent_x * scale) / 2
    offset_y = (render_h * (1 - shadow_room) - extent_y * scale) / 2

    canvas = _Canvas(render_w, render_h)
    for tris in iter_triangle_chunks(path, mesh=mesh):
        finite = np.isfinite(tris).all(axis=(1, 2))
        tris = tris[finite].astype(np.float64)
        if not len(tris):
            continue
        view = tris @ rotation.T
        normals = np.cross(view[:, 1] - view[:, 0], view[:, 2] - view[:, 0])
        diffuse, specular = _shade(normals)
        screen = np.empty_like(view, dtype=np.float32)
        screen[:, :, 0] = (view[:, :, 0] - view_lo[0]) * scale + offset_x
        screen[:, :, 1] = (view_hi[1] - view[:, :, 1]) * scale + offset_y
        screen[:, :, 2] = view[:, :, 2]
        canvas.rasterize(screen, diffuse, specular)

    covered = np.isfinite(canvas.depth)
    if not covered.any():
        raise MeshError('Render boş çıktı')

    image = _compose_image(canvas, covered, render_w, render_h, view_hi[2] - view_lo[2])
    image = _add_ground_shadow(image, lo, hi, rotation, view_lo, view_hi, scale, offset_x, offset_y, up_axis_for(path))
    return image.resize((width, height), Image.LANCZOS)


def _compose_image(canvas, covered, width, height, depth_range):
    depth = canvas.depth.reshape(height, width)
    mask = covered.reshape(height, width)
    diffuse = canvas.diffuse.reshape(height, width)
    specular = canvas.specular.reshape(height, width)

    # Siluet ve derinlik kırılmalarında ince kontur çiz.
    filled = np.where(mask, depth, np.nanmin(np.where(mask, depth, np.inf)) - depth_range)
    threshold = max(depth_range, 1e-6) * 0.035
    edge = np.zeros_like(mask)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        shifted = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
        edge |= np.abs(filled - shifted) > threshold
    edge &= mask

    shade = np.where(edge, diffuse * (1 - OUTLINE_STRENGTH), diffuse)
    rgb = shade[..., None] * BASE_COLOR[None, None, :] + specular[..., None] * SPECULAR_COLOR[None, None, :]
    rgb = np.clip(rgb, 0, 1)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = (rgb * 255).astype(np.uint8)
    rgba[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def _add_ground_shadow(image, lo, hi, rotation, view_lo, view_hi, scale, offset_x, offset_y, up='z'):
    """Modelin taban izdüşümüne yumuşak bir temas gölgesi ekle."""
    if up == 'y':
        corners = np.array([[x, lo[1], z] for x in (lo[0], hi[0]) for z in (lo[2], hi[2])])
    else:
        corners = np.array([[x, y, lo[2]] for x in (lo[0], hi[0]) for y in (lo[1], hi[1])])
    view = corners @ rotation.T
    sx = (view[:, 0] - view_lo[0]) * scale + offset_x
    sy = (view_hi[1] - view[:, 1]) * scale + offset_y
    cx, cy = sx.mean(), sy.mean()
    rx = max((sx.max() - sx.min()) / 2 * 0.92, 6)
    ry = max((sy.max() - sy.min()) / 2 * 0.92, rx * 0.12, 4)

    shadow = Image.new('L', image.size, 0)
    ImageDraw.Draw(shadow).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(image.size[0] * 0.02, 2)))
    base = Image.new('RGBA', image.size, (8, 10, 30, 0))
    base.putalpha(shadow)
    return Image.alpha_composite(base, image)


def fit_image(source, width, height, mode='contain', background=None):
    """Bir görseli hedef boyuta sığdır (contain) veya kırp (cover)."""
    image = source.convert('RGBA')
    ratio = min(width / image.width, height / image.height) if mode == 'contain' else max(width / image.width, height / image.height)
    new_size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    image = image.resize(new_size, Image.LANCZOS)
    canvas = Image.new('RGBA', (width, height), background or (0, 0, 0, 0))
    canvas.alpha_composite(image, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
    return canvas


def social_card(thumbnail, width=1200, height=630):
    """Paylaşım önizlemeleri (Open Graph) için degrade arka planlı JPEG görseli."""
    gradient = np.zeros((height, width, 3), dtype=np.float32)
    yy, xx = np.mgrid[0:height, 0:width]
    dist = np.sqrt(((xx - width * 0.5) / width) ** 2 + ((yy - height * 0.42) / height) ** 2)
    top = np.array([46, 50, 92], dtype=np.float32)
    bottom = np.array([12, 13, 24], dtype=np.float32)
    t = np.clip(dist * 1.6, 0, 1)[..., None]
    gradient[:] = top * (1 - t) + bottom * t
    card = Image.fromarray(gradient.astype(np.uint8), 'RGB').convert('RGBA')
    fitted = fit_image(thumbnail, int(width * 0.9), int(height * 0.9))
    card.alpha_composite(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return card.convert('RGB')


# ─── Arka plan işi (ayrı süreçte çalışır) ───────────────────────────────


def _materialize(source, workdir):
    """Zip içindeki bir üyeyi geçici dosyaya çıkar; normal dosyada yolu aynen döndür."""
    path = Path(source['path'])
    member = source.get('member')
    if not member:
        return path
    suffix = Path(member).suffix.lower()
    target = Path(workdir) / f'member{suffix}'
    with zipfile.ZipFile(path) as archive, archive.open(member) as src, open(target, 'wb') as dst:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
    return target


def _open_image_source(source, workdir):
    from PIL import ImageOps

    kind = source['kind']
    if kind == '3mf':
        with zipfile.ZipFile(source['path']) as archive:
            data = archive.read(source['entry'])
        import io
        return Image.open(io.BytesIO(data)), 'contain'
    image = Image.open(_materialize(source, workdir))
    try:
        image.seek(0)
    except EOFError:
        pass
    image = ImageOps.exif_transpose(image)
    return image, 'cover'


def public_stats(analysis):
    return {key: value for key, value in analysis.items() if not key.startswith('_')}


def run_job(job):
    """Küçük resim ve/veya mesh ölçülerini üret. Sonuç sözlüğü döndürür."""
    import tempfile

    result = {'ok': True, 'thumb': False, 'og': False, 'stats': None, 'errors': []}
    width, height = job.get('size', (640, 480))
    with tempfile.TemporaryDirectory(prefix='thumbjob-') as workdir:
        analysis = None
        mesh = None
        stats_source = job.get('stats')
        thumb_source = job.get('thumb')
        if stats_source:
            try:
                stats_path = _materialize(stats_source, workdir)
                if Path(stats_path).suffix.lower() in INDEXED_FORMATS:
                    mesh = load_indexed(stats_path)
                    if job.get('compact_output'):
                        try:
                            write_compact(mesh, job['compact_output'])
                            result['compact'] = True
                        except Exception as exc:  # noqa: BLE001
                            result['errors'].append(f'compact: {exc}')
                analysis = analyze_mesh(stats_path, mesh=mesh)
                result['stats'] = public_stats(analysis)
            except Exception as exc:  # noqa: BLE001 - hata raporlanır, iş devam eder
                result['errors'].append(f'stats: {exc}')

        image = None
        if thumb_source:
            try:
                if thumb_source['kind'] == 'mesh':
                    mesh_path = _materialize(thumb_source, workdir)
                    same = stats_source and stats_source.get('path') == thumb_source.get('path') and stats_source.get('member') == thumb_source.get('member')
                    image = render_mesh(
                        mesh_path, width, height,
                        analysis=analysis if same and analysis else None,
                        mesh=mesh if same else None,
                    )
                else:
                    source_image, mode = _open_image_source(thumb_source, workdir)
                    image = fit_image(source_image, width, height, mode=mode)
                output = Path(job['output'])
                output.parent.mkdir(parents=True, exist_ok=True)
                tmp = output.with_suffix('.tmp')
                image.save(tmp, 'WEBP', quality=84, method=5)
                tmp.replace(output)
                result['thumb'] = True
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'thumb: {exc}')

        if image is not None and job.get('og_output'):
            try:
                og_path = Path(job['og_output'])
                tmp = og_path.with_suffix('.tmp')
                social_card(image).save(tmp, 'JPEG', quality=86, optimize=True, progressive=True)
                tmp.replace(og_path)
                result['og'] = True
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'og: {exc}')

    result['ok'] = not result['errors'] or result['thumb'] or bool(result['stats'])
    return result


def default_social_card(output):
    """Sitenin genel paylaşım görseli: degrade üzerinde izometrik küp."""
    card = social_card(Image.new('RGBA', (8, 6), (0, 0, 0, 0))).convert('RGBA')
    draw = ImageDraw.Draw(card)
    cx, cy, r = card.width / 2, card.height / 2, 150
    top = [(cx, cy - r), (cx + r * 0.87, cy - r / 2), (cx, cy), (cx - r * 0.87, cy - r / 2)]
    left = [(cx - r * 0.87, cy - r / 2), (cx, cy), (cx, cy + r), (cx - r * 0.87, cy + r / 2)]
    right = [(cx + r * 0.87, cy - r / 2), (cx, cy), (cx, cy + r), (cx + r * 0.87, cy + r / 2)]
    draw.polygon(top, fill=(165, 170, 255))
    draw.polygon(left, fill=(92, 98, 240))
    draw.polygon(right, fill=(62, 64, 190))
    card.convert('RGB').save(output, 'JPEG', quality=88)


def main(argv=None):
    import json
    import os
    import sys

    argv = sys.argv[1:] if argv is None else argv
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    if argv[:1] == ['job']:
        job = json.loads(sys.stdin.read())
        print(json.dumps(run_job(job)))
        return 0
    if argv[:1] == ['compact'] and len(argv) in (3, 4):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='compact-') as workdir:
            source = {'path': argv[1], 'member': argv[3] if len(argv) == 4 else None}
            write_compact(load_indexed(_materialize(source, workdir)), argv[2])
        return 0
    if argv[:1] == ['default-card'] and len(argv) == 2:
        default_social_card(argv[1])
        return 0
    print('Kullanım: python -m meshes job < job.json', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
