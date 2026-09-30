import io
import json
import re
import struct
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app
import catalog
import categories
import meshes

CUBE_FACES = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
              (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
CUBE_VERTS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
PNG_1X1 = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02'
    '0000000b4944415478da63fcff1f0003030200efaf17d90000000049454e44ae426082'
)


def cube_stl_bytes(size=20.0):
    data = bytearray(b'\0' * 80 + struct.pack('<I', len(CUBE_FACES)))
    for face in CUBE_FACES:
        data += struct.pack('<3f', 0, 0, 0)
        for index in face:
            data += struct.pack('<3f', *(value * size for value in CUBE_VERTS[index]))
        data += b'\0\0'
    return bytes(data)


def write_stl(path, size=20.0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cube_stl_bytes(size))
    return path


def write_production_3mf(path):
    """Bambu tarzı: kök modeldeki bileşen başka bir .model dosyasına p:path ile bağlı."""
    verts = ''.join(f'<vertex x="{x * 10}" y="{y * 10}" z="{z * 10}"/>' for x, y, z in CUBE_VERTS)
    tris = ''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in CUBE_FACES)
    part = ('<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
            f'<resources><object id="1" type="model"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object></resources>'
            '<build/></model>')
    root = ('<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">'
            '<metadata name="Title">Test Kutusu</metadata><metadata name="Designer">Ayşe</metadata>'
            '<resources><object id="2" type="model"><components>'
            '<component p:path="/3D/Objects/object_1.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 5"/>'
            '</components></object></resources><build><item objectid="2"/></build></model>')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('_rels/.rels', '<Relationships><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        archive.writestr('3D/3dmodel.model', root)
        archive.writestr('3D/Objects/object_1.model', part)
        archive.writestr('Metadata/plate_1.png', PNG_1X1)
    return path


class TokenizeAndClassifyTests(unittest.TestCase):
    def test_tokenize_folds_turkish_and_splits_camel_case_and_versions(self):
        tokens = categories.tokenize('NameWithEmojiTopper anahtarlıkv2 NAH_İŞARETİ')
        for expected in ('name', 'with', 'emoji', 'topper', 'anahtarlik', 'v2', 'nah', 'isareti'):
            self.assertIn(expected, tokens)

    def test_keywords_match_whole_words_only(self):
        cases = {
            'WILLYS JEEP - Fully printable': 'vehicle',
            'USB-SD-MicroSD Card Holder': 'tech',
            'Fidget Spinner 608 Bearing caps': 'fidget',
            'Extreme Gearbox Fidget Toy': 'fidget',
            'Sustalı Anahtarlık Switchblade Keychain': 'keychain',
            'Ratcheted Toothpaste Tube Squeezer': 'home',
            'Christmas Decorations - bauble styles': 'seasonal',
            'Lens Hood Canon': 'tech',
            'Kölner Dom': 'decor',
            'Galata Kulesi': 'decor',
            'Süleymaniye Camii': 'decor',
            'Drawer tower storage box': 'storage',
            'Eiffel Tower keychain': 'keychain',
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(categories.classify([(title, 3.0, None)])[0], expected)

    def test_unknown_names_fall_back_to_other(self):
        self.assertEqual(categories.classify([('317', 3.0, None)])[0], categories.OTHER)

    def test_collection_context_outweighs_generic_title(self):
        category, _ = categories.classify([('Polar Bear', 3.0, None), ('Monitor Grinch v1.2', 3.0, None)])
        self.assertEqual(category, 'seasonal')

    def test_nsfw_detection_and_generic_dirs(self):
        self.assertTrue(categories.is_nsfw(['Nude Sexy Woman.zip']))
        self.assertFalse(categories.is_nsfw(['Sussex landmark', 'Essex']))
        for name in ('files', 'STL SINGLES', 'V2.5', 'UPDATES', 'FILE PARAMETRIC'):
            self.assertTrue(categories.is_generic_dir_name(name), name)
        self.assertFalse(categories.is_generic_dir_name('Climbing+Santa_stls'))

    def test_clean_title_removes_download_artifacts(self):
        cases = {
            ('Fully 3D-printable wind-up car gift card - 3308710 - part 1 of 2', False): 'Fully 3D-printable wind-up car gift card - part 1 of 2',
            ('3d-printer-spool-stop20210313-13893-1vjlcob', False): '3D printer spool stop',
            ('Chair-leg+paper+towel+rack', False): 'Chair-leg paper towel rack',
            ('Tray_between_cushions_stls', False): 'Tray between cushions',
            ('the-ultimate-bag-clip-model_files', False): 'The ultimate bag clip',
            ('standing rope.stl.stl', True): 'Standing rope',
            ('KeyCover_ofis.stl', True): 'Key Cover ofis',
            ('Pokemon-Pikachu(NO+SUPPORT)', False): 'Pokemon Pikachu',
        }
        for (raw, is_file), expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(catalog.clean_title(raw, is_file=is_file)[0], expected)
        title, author = catalog.clean_title('desk-mounted-trash-bin-by-miadesign')
        self.assertEqual((title, author), ('Desk mounted trash bin', 'miadesign'))


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'models'
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self):
        return {record['path']: record for record in catalog.scan_library(self.root).values()}

    def test_download_wrapper_collapses_and_records_author(self):
        write_stl(self.root / 'spool-stop20210313-13893-1vjlcob' / 'naedioba1' / 'spool-stop' / 'part.stl')
        records = self.scan()
        record = records['spool-stop20210313-13893-1vjlcob/naedioba1/spool-stop']
        self.assertEqual(record['title'], 'Spool stop')
        self.assertEqual(record['author'], 'naedioba1')
        self.assertEqual(record['auto_category'], 'printer')

    def test_version_folders_merge_and_collections_split(self):
        write_stl(self.root / 'bin' / 'a.stl')
        write_stl(self.root / 'bin' / 'V2' / 'b.stl')
        write_stl(self.root / 'bin' / 'UPDATES' / 'c.stl')
        write_stl(self.root / 'Pack' / 'Monitor Santa' / 'santa.stl')
        write_stl(self.root / 'Pack' / 'Polar Bear' / 'bear.stl')
        records = self.scan()
        self.assertEqual(records['bin']['file_count'], 3)
        self.assertIn('Pack/Monitor Santa', records)
        self.assertEqual(records['Pack/Polar Bear']['collection'], 'Pack')

    def test_thingiverse_metadata_license_and_images(self):
        project = self.root / 'Gear Set - 123'
        write_stl(project / 'files' / 'gear.stl')
        (project / 'images').mkdir()
        (project / 'images' / 'photo.png').write_bytes(PNG_1X1)
        (project / 'README.txt').write_text(
            'Gear Set by Ali on Thingiverse: https://www.thingiverse.com/thing:123\n\nSummary:\nNice gears.Printed in PLA.\n', encoding='utf-8')
        (project / 'LICENSE.txt').write_text(
            'This thing was created by Thingiverse user Ali, and is licensed under Creative Commons - Attribution - Share Alike', encoding='utf-8')
        record = self.scan()['Gear Set - 123']
        self.assertEqual(record['title'], 'Gear Set')
        self.assertEqual(record['author'], 'Ali')
        self.assertEqual(record['license'], 'CC BY-SA')
        self.assertEqual(record['source_platform'], 'Thingiverse')
        self.assertEqual(record['description'], 'Nice gears. Printed in PLA.')
        self.assertEqual(record['thumb_source']['kind'], 'image')
        self.assertEqual(record['auto_category'], 'mechanical')

    def test_printables_pdf_becomes_source_link(self):
        write_stl(self.root / 'battery pack' / 'pack.stl')
        (self.root / 'battery pack' / '38002-battery-pack-aa-48dca04e-9f47-495b-85e0-262ebb512aaf.pdf').write_bytes(b'%PDF-1.4')
        record = self.scan()['battery pack']
        self.assertEqual(record['source_url'], 'https://www.printables.com/model/38002-battery-pack-aa')
        self.assertEqual(record['source_platform'], 'Printables')

    def test_root_zip_without_folder_is_an_archive_model(self):
        with zipfile.ZipFile(self.root / 'letters.zip', 'w') as archive:
            archive.writestr('author/letters/A.stl', cube_stl_bytes())
            archive.writestr('author/letters/B.stl', cube_stl_bytes())
        write_stl(self.root / 'Park Slide' / 'slide.stl')
        with zipfile.ZipFile(self.root / 'Park Slide.zip', 'w') as archive:
            archive.writestr('slide.stl', cube_stl_bytes())
        records = self.scan()
        self.assertEqual(records['letters.zip']['kind'], 'archive')
        self.assertEqual(records['letters.zip']['file_count'], 2)
        self.assertNotIn('Park Slide.zip', records)
        self.assertTrue(any(entry['path'] == 'Park Slide.zip' for entry in records['Park Slide']['assets']))

    def test_nsfw_names_hide_category_and_child_brand_tags(self):
        write_stl(self.root / 'mesa polly' / 'nude sexy woman.stl')
        record = self.scan()['mesa polly']
        self.assertTrue(record['auto_nsfw'])
        self.assertEqual(record['auto_category'], 'figure')
        self.assertNotIn('Polly Pocket', record['auto_tags'])

    def test_generic_single_file_uses_embedded_3mf_title(self):
        write_production_3mf(self.root / 'Holder.3mf')
        record = self.scan()['Holder.3mf']
        self.assertEqual(record['title'], 'Test Kutusu')
        self.assertEqual(record['author'], 'Ayşe')
        self.assertEqual(record['thumb_source']['kind'], '3mf')


class MeshTests(unittest.TestCase):
    def test_binary_ascii_and_production_3mf_meshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            stl = write_stl(Path(tmp) / 'cube.stl', 20)
            info = meshes.analyze_mesh(stl)
            self.assertEqual(info['triangles'], 12)
            self.assertEqual(info['size_mm'], [20.0, 20.0, 20.0])
            self.assertAlmostEqual(info['volume_cm3'], 8.0, places=2)

            ascii_path = Path(tmp) / 'ascii.stl'
            lines = ['solid t']
            for face in CUBE_FACES:
                lines.append('facet normal 0 0 0\nouter loop')
                lines += [f'vertex {x * 5} {y * 5} {z * 5}' for x, y, z in (CUBE_VERTS[i] for i in face)]
                lines.append('endloop\nendfacet')
            ascii_path.write_text('\n'.join(lines + ['endsolid t']))
            self.assertEqual(meshes.analyze_mesh(ascii_path)['size_mm'], [5.0, 5.0, 5.0])

            model = write_production_3mf(Path(tmp) / 'prod.3mf')
            vertices, faces = meshes.load_indexed(model)
            self.assertEqual(len(faces), 12)
            self.assertAlmostEqual(float(vertices[:, 2].min()), 5.0)

            image = meshes.render_mesh(stl, width=160, height=120)
            self.assertEqual(image.size, (160, 120))
            self.assertGreater(image.getchannel('A').getextrema()[1], 0)

            out = Path(tmp) / 'mesh.m3d'
            meshes.write_compact((vertices, faces), out)
            data = out.read_bytes()
            self.assertEqual(data[:4], b'M3DB')
            self.assertEqual(struct.unpack('<3I', data[4:16]), (1, len(vertices), 36))


class ApiTestCase(unittest.TestCase):
    password = 'Gizli.Sifre1'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.models = base / 'models'
        self.data = base / 'data'
        self.models.mkdir()
        self.data.mkdir()
        write_stl(self.models / 'Kutu' / 'box.stl')
        write_stl(self.models / 'Anahtarlık.stl')
        self.flask_app = app.create_app(models_dir=self.models, data_dir=self.data, start_workers=False, testing=True)
        self.library = self.flask_app.extensions['library']
        self.library.set_password(self.password)
        self.client = self.flask_app.test_client()
        self.csrf = self.fresh_csrf(self.client)

    def tearDown(self):
        self.tmp.cleanup()

    def fresh_csrf(self, client):
        html = client.get('/').get_data(as_text=True)
        return json.loads(re.search(r'id="boot">(.*?)</script>', html, re.S).group(1))['csrf']

    def post(self, url, payload=None, client=None, csrf=None, method='POST'):
        client = client or self.client
        return client.open(url, method=method, json=payload if payload is not None else {}, headers={'X-CSRF-Token': csrf or self.csrf})

    def login(self):
        response = self.post('/api/auth/login', {'password': self.password})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf = response.get_json()['csrf']

    def model_id(self, path):
        return catalog.generate_id(path)


class AuthTests(ApiTestCase):
    def test_login_requires_csrf_and_correct_password(self):
        self.assertEqual(self.client.post('/api/auth/login', json={'password': self.password}).status_code, 403)
        self.assertEqual(self.post('/api/auth/login', {'password': 'yanlis'}).status_code, 401)
        self.login()
        self.assertTrue(self.client.get('/api/session').get_json()['admin'])

    def test_login_is_rate_limited(self):
        with patch('app.time.sleep'):
            for _ in range(app.LOGIN_MAX_FAILURES):
                self.post('/api/auth/login', {'password': 'yanlis'})
            response = self.post('/api/auth/login', {'password': self.password})
        self.assertEqual(response.status_code, 429)

    def test_rate_limit_is_per_real_client_behind_cloudflare(self):
        with patch('app.time.sleep'):
            for _ in range(app.LOGIN_MAX_FAILURES):
                self.client.post('/api/auth/login', json={'password': 'yanlis'},
                                 headers={'X-CSRF-Token': self.csrf, 'CF-Connecting-IP': '203.0.113.7'})
            other = self.client.post('/api/auth/login', json={'password': self.password},
                                     headers={'X-CSRF-Token': self.csrf, 'CF-Connecting-IP': '198.51.100.9'})
        self.assertEqual(other.status_code, 200)

    def test_admin_endpoints_reject_visitors(self):
        for method, url in (('POST', '/api/scan'), ('PATCH', f"/api/models/{self.model_id('Kutu')}"), ('POST', '/api/uploads'), ('GET', '/api/settings')):
            response = self.post(url, method=method) if method != 'GET' else self.client.get(url)
            self.assertEqual(response.status_code, 401, url)

    def test_password_change_logs_out_other_sessions(self):
        self.login()
        other = self.flask_app.test_client()
        other_csrf = self.fresh_csrf(other)
        other_login = self.post('/api/auth/login', {'password': self.password}, client=other, csrf=other_csrf)
        self.assertEqual(other_login.status_code, 200)
        response = self.post('/api/auth/password', {'current': self.password, 'new': 'Yeni.Sifre2'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get('/api/session').get_json()['admin'])
        self.assertFalse(other.get('/api/session').get_json()['admin'])

    def test_password_set_by_another_process_is_picked_up_without_touching_db(self):
        self.login()
        box = self.model_id('Kutu')
        self.post(f'/api/models/{box}', {'note': 'korunmalı'}, method='PATCH')
        cli = app.Library(self.models, self.data)
        cli.set_password('Baska.Sifre9')
        self.assertFalse(self.client.get('/api/session').get_json()['admin'])
        self.assertEqual(self.post('/api/auth/login', {'password': 'Baska.Sifre9'}).status_code, 200)
        self.assertEqual(self.library.db['models'][box]['note'], 'korunmalı')
        self.assertNotIn('Baska', (self.data / 'db.json').read_text(encoding='utf-8'))

    def test_security_headers(self):
        response = self.client.get('/')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


class LibraryApiTests(ApiTestCase):
    def test_library_lists_models_with_categories(self):
        data = self.client.get('/api/library').get_json()
        titles = {model['title']: model for model in data['models']}
        self.assertEqual(set(titles), {'Kutu', 'Anahtarlık'})
        self.assertEqual(titles['Anahtarlık']['category'], 'keychain')
        self.assertEqual(titles['Kutu']['category'], 'storage')

    def test_hidden_model_is_private_but_shareable(self):
        self.login()
        box = self.model_id('Kutu')
        self.assertEqual(self.post(f'/api/models/{box}', {'hidden': True}, method='PATCH').status_code, 200)
        share = self.post(f'/api/models/{box}/shares', {'expires_days': 7, 'allow_download': False}).get_json()

        visitor = self.flask_app.test_client()
        self.assertNotIn(box, {model['id'] for model in visitor.get('/api/library').get_json()['models']})
        self.assertEqual(visitor.get(f'/api/models/{box}').status_code, 404)
        self.assertEqual(visitor.get('/api/file/Kutu/box.stl').status_code, 404)

        token = share['token']
        page = visitor.get(f'/s/{token}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('og:image', page.get_data(as_text=True))
        self.assertEqual(visitor.get(f'/api/file/Kutu/box.stl?s={token}').status_code, 200)
        self.assertEqual(visitor.get(f'/api/file/Kutu/box.stl?s={token}&download=1').status_code, 403)
        self.assertEqual(visitor.get(f'/api/models/{box}/download?s={token}').status_code, 403)

        self.library.db['shares'][token]['expires_at'] = time.time() - 1
        self.assertEqual(visitor.get(f'/s/{token}').status_code, 404)
        self.assertEqual(visitor.get(f'/api/file/Kutu/box.stl?s={token}').status_code, 404)

    def test_file_endpoint_blocks_traversal_and_unknown_types(self):
        (self.models / 'Kutu' / 'notes.html').write_text('<script>alert(1)</script>')
        (self.data / 'secret.stl').write_bytes(b'x')
        self.assertEqual(self.client.get('/api/file/Kutu/notes.html').status_code, 404)
        self.assertEqual(self.client.get('/api/file/../data/secret.stl').status_code, 404)
        self.assertEqual(self.client.get('/api/file/%2e%2e/data/secret.stl').status_code, 404)
        response = self.client.get('/api/file/Kutu/box.stl')
        self.assertEqual(response.status_code, 200)
        self.assertIn('private', response.headers['Cache-Control'])

    def test_private_archive_requires_login(self):
        self.login()
        self.post('/api/settings', {'public_browsing': False}, method='PATCH')
        visitor = self.flask_app.test_client()
        self.assertEqual(visitor.get('/api/library').status_code, 401)
        self.assertEqual(visitor.get('/api/file/Kutu/box.stl').status_code, 404)
        self.assertEqual(self.client.get('/api/library').status_code, 200)

    def test_patch_overrides_and_resets_to_auto(self):
        self.login()
        box = self.model_id('Kutu')
        detail = self.post(f'/api/models/{box}', {'category': 'decor', 'tags': ['A', 'a', ' B '], 'title': 'Güzel kutu'}, method='PATCH').get_json()
        self.assertEqual((detail['category'], detail['tags'], detail['title']), ('decor', ['A', 'B'], 'Güzel kutu'))
        self.assertTrue(detail['overrides']['category'])
        detail = self.post(f'/api/models/{box}', {'category': None, 'tags': None, 'title': ''}, method='PATCH').get_json()
        self.assertEqual((detail['category'], detail['title']), ('storage', 'Kutu'))
        self.assertFalse(detail['overrides']['tags'])
        self.assertEqual(self.post(f'/api/models/{box}', {'category': 'nope'}, method='PATCH').status_code, 400)
        self.assertEqual(self.post(f'/api/models/{box}', {'source_url': 'javascript:alert(1)'}, method='PATCH').status_code, 400)

    def test_zip_download_contains_all_files(self):
        (self.models / 'Kutu' / 'README.txt').write_text('Merhaba', encoding='utf-8')
        self.library.scan()
        response = self.client.get(f"/api/models/{self.model_id('Kutu')}/download")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.get_data())) as archive:
            self.assertEqual(sorted(archive.namelist()), ['README.txt', 'box.stl'])
            self.assertEqual(archive.read('box.stl'), cube_stl_bytes())

    def test_thumbnails_stats_and_compact_mesh(self):
        write_production_3mf(self.models / 'Holder.3mf')
        self.library.scan()
        self.library.run_pending_jobs()
        box = self.model_id('Kutu')
        card = next(model for model in self.client.get('/api/library').get_json()['models'] if model['id'] == box)
        self.assertTrue(card['thumb'])
        self.assertEqual(card['dims'], '20 × 20 × 20 mm')
        self.assertEqual(app.format_dims([28.14, 48.2, 5]), '28,1 × 48,2 × 5 mm')
        thumb = self.client.get(card['thumb'])
        self.assertEqual((thumb.status_code, thumb.mimetype), (200, 'image/webp'))
        self.assertEqual(self.client.get(f'/api/og/{box}').mimetype, 'image/jpeg')
        mesh = self.client.get('/api/mesh/Holder.3mf')
        self.assertEqual(mesh.status_code, 200)
        self.assertEqual(mesh.get_data()[:4], b'M3DB')

    def test_trash_moves_files_and_removes_shares(self):
        self.login()
        box = self.model_id('Kutu')
        self.post(f'/api/models/{box}/shares', {})
        self.assertEqual(self.post(f'/api/models/{box}', method='DELETE').status_code, 200)
        self.assertFalse((self.models / 'Kutu').exists())
        self.assertTrue(any((self.data / '.trash').iterdir()))
        self.assertEqual(self.library.db['shares'], {})


class ReviewRegressionTests(ApiTestCase):
    """Güvenlik incelemesinde bulunan açıkların geri gelmemesi için."""

    def test_view_only_share_and_disabled_downloads_block_non_preview_files(self):
        (self.models / 'Kutu' / 'kaynak.step').write_text('ISO-10303-21;', encoding='utf-8')
        (self.models / 'Kutu' / 'kilavuz.pdf').write_bytes(b'%PDF-1.4')
        self.library.scan()
        self.login()
        box = self.model_id('Kutu')
        token = self.post(f'/api/models/{box}/shares', {'allow_download': False}).get_json()['token']
        visitor = self.flask_app.test_client()
        self.assertEqual(visitor.get(f'/api/file/Kutu/kaynak.step?s={token}').status_code, 403)
        self.assertEqual(visitor.get(f'/api/file/Kutu/box.stl?s={token}').status_code, 200)
        detail = visitor.get(f'/api/models/{box}?s={token}').get_json()
        step = next(item for item in detail['assets'] if item['name'] == 'kaynak.step')
        self.assertIsNone(step['url'])
        self.post('/api/settings', {'public_downloads': False}, method='PATCH')
        self.assertEqual(visitor.get('/api/file/Kutu/kilavuz.pdf').status_code, 403)
        self.assertEqual(visitor.get('/api/file/Kutu/box.stl').status_code, 200)

    def test_hidden_archive_is_not_exposed_through_a_public_sibling(self):
        write_stl(self.models / 'Dragon.stl')
        with zipfile.ZipFile(self.models / 'Dragon.zip', 'w') as archive:
            archive.writestr('extra/part.stl', cube_stl_bytes())
            archive.writestr('extra/secret.txt', 'GİZLİ')
        self.library.scan()
        archive_id = self.model_id('Dragon.zip')
        sibling = self.library.record(self.model_id('Dragon.stl'))
        self.assertFalse(any(entry['path'] == 'Dragon.zip' for entry in sibling['assets']))
        self.login()
        self.post(f'/api/models/{archive_id}', {'hidden': True}, method='PATCH')
        visitor = self.flask_app.test_client()
        self.assertEqual(visitor.get('/api/file/Dragon.zip?member=extra/secret.txt').status_code, 404)
        self.assertEqual(visitor.get('/api/file/Dragon.zip?download=1').status_code, 404)
        self.assertEqual(visitor.get('/api/file/Dragon.stl').status_code, 200)

    def test_malformed_3mf_does_not_break_the_site(self):
        with zipfile.ZipFile(self.models / 'bozuk.3mf', 'w') as archive:
            archive.writestr('3D/3dmodel.model', '<model><resources/></model>')
            archive.writestr('Metadata/project_settings.config', '[1, 2, 3]')
        with open(self.models / 'bozuk2.3mf', 'wb') as handle:
            handle.write(b'PK\x03\x04 bu bir zip degil')
        self.library.scan()
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/library').status_code, 200)

    def test_retried_chunk_after_partial_write_does_not_corrupt_file(self):
        self.login()
        data = cube_stl_bytes(12)
        session = self.post('/api/uploads', {'files': [{'name': 'parca.stl', 'size': len(data)}]}).get_json()
        part = self.data / '.uploads' / session['id'] / '0.part'
        part.write_bytes(data[:100])  # yarım kalmış bir denemenin artığı
        response = self.client.put(f"/api/uploads/{session['id']}/0", data=data,
                                   headers={'X-CSRF-Token': self.csrf, 'X-Upload-Offset': '0'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(part.read_bytes(), data)

    def test_cancel_upload_rejects_path_like_ids(self):
        self.login()
        response = self.client.delete('/api/uploads/%2e%2e', headers={'X-CSRF-Token': self.csrf})
        self.assertIn(response.status_code, (200, 404))
        self.assertTrue((self.data / 'db.json').exists())
        self.assertTrue((self.data / '.users.json').exists())

    def test_non_ascii_csrf_header_is_rejected_cleanly(self):
        response = self.client.post('/api/auth/login', json={'password': 'x'}, headers={'X-CSRF-Token': 'ş'.encode('utf-8').decode('latin-1')})
        self.assertEqual(response.status_code, 403)

    def test_trashing_parent_keeps_nested_separate_model(self):
        write_stl(self.models / 'Ebeveyn' / 'ana.stl')
        write_stl(self.models / 'Ebeveyn' / 'cocuk20250101-1-abcdef' / 'yazar' / 'cocuk' / 'cocuk.stl')
        self.library.scan()
        parent = self.model_id('Ebeveyn')
        child_path = 'Ebeveyn/cocuk20250101-1-abcdef/yazar/cocuk'
        self.assertIn(self.model_id(child_path), self.library.db['catalog'])
        self.login()
        self.assertEqual(self.post(f'/api/models/{parent}', method='DELETE').status_code, 200)
        self.assertTrue((self.models / child_path / 'cocuk.stl').exists())
        self.assertFalse((self.models / 'Ebeveyn' / 'ana.stl').exists())
        self.assertIn(self.model_id(child_path), self.library.db['catalog'])

    def test_corrupt_database_restores_last_good_copy_or_fails_closed(self):
        self.login()
        self.post('/api/settings', {'public_browsing': False}, method='PATCH')
        self.library._last_good_at = 0
        self.library.save()
        (self.data / 'db.json').write_text('{bozuk', encoding='utf-8')
        restored = app.Library(self.models, self.data)
        self.assertFalse(restored.settings['public_browsing'])
        (self.data / 'db.json').write_text('{bozuk', encoding='utf-8')
        (self.data / 'db.last-good.json').unlink()
        fresh = app.Library(self.models, self.data)
        self.assertFalse(fresh.settings['public_browsing'])

    def test_running_server_keeps_memory_copy_when_file_is_corrupted(self):
        self.login()
        self.post(f"/api/models/{self.model_id('Kutu')}", {'note': 'kalsın'}, method='PATCH')
        (self.data / 'db.json').write_text('[]', encoding='utf-8')
        self.library._mtime_checked = 0
        self.assertEqual(self.library.db['models'][self.model_id('Kutu')]['note'], 'kalsın')
        self.library.save()
        self.assertIn('kalsın', (self.data / 'db.json').read_text(encoding='utf-8'))


class VisibilityTests(ApiTestCase):
    def test_new_models_hidden_setting_applies_only_to_new_models(self):
        self.login()
        self.post('/api/settings', {'new_models_hidden': True}, method='PATCH')
        write_stl(self.models / 'Yeni Model' / 'yeni.stl')
        self.library.scan()
        visitor = self.flask_app.test_client()
        titles = {model['title'] for model in visitor.get('/api/library').get_json()['models']}
        self.assertEqual(titles, {'Kutu', 'Anahtarlık'})
        self.assertTrue(self.library.db['models'][self.model_id('Yeni Model')]['hidden'])

    def test_bulk_visibility_hides_everything_then_publishes_selection(self):
        self.login()
        self.assertEqual(self.post('/api/admin/bulk', {'ids': 'all', 'changes': {'hidden': True}}).get_json()['updated'], 2)
        box = self.model_id('Kutu')
        self.post('/api/admin/bulk', {'ids': [box, 'yok'], 'changes': {'hidden': False}})
        visitor = self.flask_app.test_client()
        self.assertEqual([model['id'] for model in visitor.get('/api/library').get_json()['models']], [box])
        self.assertEqual(self.post('/api/admin/bulk', {'ids': 'all', 'changes': {'note': 'x'}}).status_code, 400)
        anonymous = self.flask_app.test_client()
        anon_csrf = self.fresh_csrf(anonymous)
        self.assertEqual(self.post('/api/admin/bulk', {'ids': 'all', 'changes': {'hidden': False}}, client=anonymous, csrf=anon_csrf).status_code, 401)


class UserRoleTests(ApiTestCase):
    def make_user(self, username, role, password='Kullanici.1'):
        self.login()
        response = self.post('/api/users', {'username': username, 'password': password, 'role': role, 'name': username.title()})
        self.assertEqual(response.status_code, 201, response.get_json())
        client = self.flask_app.test_client()
        csrf = self.fresh_csrf(client)
        login = self.post('/api/auth/login', {'username': username, 'password': password}, client=client, csrf=csrf)
        self.assertEqual(login.status_code, 200, login.get_json())
        return client, login.get_json()['csrf']

    def test_admin_logs_in_with_username_and_legacy_body(self):
        response = self.post('/api/auth/login', {'username': 'admin', 'password': self.password})
        self.assertEqual(response.get_json()['user']['role'], 'admin')
        self.csrf = response.get_json()['csrf']
        self.assertEqual(self.post('/api/auth/login', {'username': 'yok', 'password': self.password}).status_code, 401)

    def test_member_sees_hidden_models_but_not_nsfw_and_cannot_edit(self):
        self.login()
        box = self.model_id('Kutu')
        key = self.model_id('Anahtarlık.stl')
        self.post(f'/api/models/{box}', {'hidden': True}, method='PATCH')
        self.post(f'/api/models/{key}', {'nsfw': True}, method='PATCH')
        member, csrf = self.make_user('uye', 'member')
        ids = {model['id'] for model in member.get('/api/library').get_json()['models']}
        self.assertIn(box, ids)
        self.assertNotIn(key, ids)
        self.assertEqual(member.get('/api/file/Kutu/box.stl?download=1').status_code, 200)
        self.assertEqual(self.post(f'/api/models/{box}', {'title': 'x'}, client=member, csrf=csrf, method='PATCH').status_code, 403)
        self.assertEqual(self.post('/api/uploads', {'files': []}, client=member, csrf=csrf).status_code, 403)
        detail = member.get(f'/api/models/{box}').get_json()
        self.assertNotIn('note', detail)

    def test_editor_can_edit_and_share_but_not_delete_or_change_settings(self):
        editor, csrf = self.make_user('editor', 'editor')
        box = self.model_id('Kutu')
        self.assertEqual(self.post(f'/api/models/{box}', {'category': 'decor'}, client=editor, csrf=csrf, method='PATCH').status_code, 200)
        self.assertEqual(self.post(f'/api/models/{box}/shares', {}, client=editor, csrf=csrf).status_code, 201)
        self.assertEqual(self.post(f'/api/models/{box}', client=editor, csrf=csrf, method='DELETE').status_code, 403)
        self.assertEqual(self.post('/api/settings', {'public_browsing': False}, client=editor, csrf=csrf, method='PATCH').status_code, 403)
        self.assertEqual(editor.get('/api/users').status_code, 403)

    def test_member_can_browse_private_archive_and_change_own_password(self):
        member, csrf = self.make_user('aile', 'member')
        self.post('/api/settings', {'public_browsing': False}, method='PATCH')
        self.assertEqual(member.get('/api/library').status_code, 200)
        self.assertEqual(self.flask_app.test_client().get('/api/library').status_code, 401)
        changed = self.post('/api/auth/password', {'current': 'Kullanici.1', 'new': 'Yepyeni.2'}, client=member, csrf=csrf)
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(member.get('/api/session').get_json()['user'])
        self.assertIsNotNone(self.library.check_login('aile', 'Yepyeni.2'))

    def test_last_admin_is_protected_and_disabled_users_are_logged_out(self):
        member, _ = self.make_user('misafir', 'member')
        self.assertEqual(self.post('/api/users/admin', {'role': 'member'}, method='PATCH').status_code, 400)
        self.assertEqual(self.post('/api/users/admin', method='DELETE').status_code, 400)
        self.assertEqual(self.post('/api/users/misafir', {'disabled': True}, method='PATCH').status_code, 200)
        self.assertIsNone(member.get('/api/session').get_json()['user'])
        self.assertEqual(self.post('/api/users', {'username': 'A B', 'password': 'Uzun.Sifre1'}).status_code, 400)
        self.assertEqual(self.post('/api/users', {'username': 'misafir', 'password': 'Uzun.Sifre1'}).status_code, 409)
        self.assertEqual(self.post('/api/users/misafir', method='DELETE').status_code, 200)
        self.assertNotIn('misafir', {user['username'] for user in self.library.list_users()})


class UploadTests(ApiTestCase):
    def upload(self, files, meta):
        created = self.post('/api/uploads', {'files': [{'name': name, 'size': len(data)} for name, data in files]})
        self.assertEqual(created.status_code, 200, created.get_json())
        session = created.get_json()
        for index, (_, data) in enumerate(files):
            half = len(data) // 2 or len(data)
            for offset, chunk in ((0, data[:half]), (half, data[half:])):
                if not chunk:
                    continue
                response = self.client.put(
                    f"/api/uploads/{session['id']}/{index}", data=chunk,
                    headers={'X-CSRF-Token': self.csrf, 'X-Upload-Offset': str(offset), 'Content-Type': 'application/octet-stream'},
                )
                self.assertEqual(response.status_code, 200, response.get_json())
        return self.post(f"/api/uploads/{session['id']}/complete", meta)

    def test_chunked_upload_creates_model_with_metadata(self):
        self.login()
        response = self.upload([('Ejderha Yumurtası.stl', cube_stl_bytes(30))], {
            'title': 'Ejderha yumurtası', 'category': 'figure', 'tags': ['Hediye'],
            'description': 'Test', 'author': 'Deniz', 'hidden': True,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        model = response.get_json()['models'][0]
        self.assertEqual((model['title'], model['category'], model['tags'], model['author'], model['hidden']),
                         ('Ejderha yumurtası', 'figure', ['Hediye'], 'Deniz', True))
        self.assertTrue((self.models / 'Ejderha yumurtası' / 'Ejderha Yumurtası.stl').exists())

    def test_offset_conflict_reports_expected_position(self):
        self.login()
        session = self.post('/api/uploads', {'files': [{'name': 'a.stl', 'size': 10}]}).get_json()
        response = self.client.put(f"/api/uploads/{session['id']}/0", data=b'12345',
                                   headers={'X-CSRF-Token': self.csrf, 'X-Upload-Offset': '5'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['received'], 0)

    def test_zip_upload_is_extracted_safely(self):
        self.login()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Dragon - 99/files/egg.stl', cube_stl_bytes())
            archive.writestr('Dragon - 99/../../../evil.stl', cube_stl_bytes())
            archive.writestr('Dragon - 99/run.sh', 'rm -rf /')
            archive.writestr('Dragon - 99/README.txt', 'Dragon by Mert on Thingiverse: https://www.thingiverse.com/thing:99\n\nSummary:\nPrint in place.')
        response = self.upload([('Dragon - 99.zip', buffer.getvalue())], {})
        self.assertEqual(response.status_code, 200, response.get_json())
        model = response.get_json()['models'][0]
        self.assertEqual((model['title'], model['author']), ('Dragon', 'Mert'))
        self.assertIn('Print-in-place', model['tags'])
        self.assertFalse(any(path.name == 'evil.stl' for path in Path(self.tmp.name).rglob('*') if 'models' not in path.parts[-3:]))
        self.assertFalse(list(self.models.rglob('run.sh')))

    def test_rejects_unsupported_files_and_models_without_meshes(self):
        self.login()
        response = self.post('/api/uploads', {'files': [{'name': 'virus.exe', 'size': 3}]})
        self.assertEqual(response.status_code, 400)
        response = self.upload([('sadece-resim.png', PNG_1X1)], {})
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.models / 'Sadece resim').exists())

    def test_explicit_upload_visibility_overrides_hidden_default(self):
        self.login()
        self.post('/api/settings', {'new_models_hidden': True}, method='PATCH')
        public = self.upload([('acik.stl', cube_stl_bytes(8))], {'title': 'Açık model', 'hidden': False}).get_json()['models'][0]
        default = self.upload([('gizli.stl', cube_stl_bytes(9))], {'title': 'Varsayılan model'}).get_json()['models'][0]
        self.assertFalse(public['hidden'])
        self.assertTrue(default['hidden'])

    def test_files_can_be_added_to_existing_folder_model(self):
        self.login()
        box = self.model_id('Kutu')
        response = self.upload([('kapak.stl', cube_stl_bytes(5))], {'target': box})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['models'][0]['fileCount'], 2)


class DatabaseTests(unittest.TestCase):
    def test_v1_database_is_migrated_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            models, data = Path(tmp) / 'models', Path(tmp) / 'data'
            write_stl(models / 'real.stl')
            data.mkdir()
            real_id = catalog.generate_id('real.stl')
            (data / 'db.json').write_text(json.dumps({
                'models': {
                    real_id: {'tags': ['🔑 Anahtarlık', 'benim'], 'favorite': True, 'note': 'not', 'printed': False},
                    'folder:abc': {'tags': ['x'], 'favorite': True},
                    'plain': {'tags': ['📦 Kutu/Depolama'], 'favorite': False, 'note': '', 'printed': False},
                },
                'catalog': {}, 'catalogs': {}, 'last_scan': 1.0,
            }), encoding='utf-8')
            library = app.Library(models, data)
            library.scan()
            record = library.db['models'][real_id]
            self.assertEqual((record['favorite'], record['note'], record['tags']), (True, 'not', ['benim']))
            self.assertNotIn('folder:abc', library.db['models'])
            self.assertNotIn('plain', library.db['models'])
            self.assertEqual(len(list(data.glob('db.v1-backup-*.json'))), 1)
            self.assertEqual(json.loads((data / 'db.json').read_text())['version'], app.DB_VERSION)

    def test_legacy_password_hash_moves_out_of_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            legacy_hash = app.generate_password_hash('Eski.Sifre1')
            (data / 'db.json').write_text(json.dumps({
                'version': app.DB_VERSION,
                'settings': {'admin_password_hash': legacy_hash, 'session_epoch': 4, 'site_title': 'Arşivim'},
                'models': {}, 'catalog': {}, 'derived': {}, 'shares': {},
            }), encoding='utf-8')
            library = app.Library(data / 'models', data)
            self.assertEqual(library.settings['site_title'], 'Arşivim')
            self.assertTrue(library.check_password('Eski.Sifre1'))
            self.assertEqual(library.get_user('admin')['epoch'], 4)
            self.assertNotIn('admin_password_hash', json.loads((data / 'db.json').read_text())['settings'])
            self.assertEqual(oct((data / '.users.json').stat().st_mode & 0o777), '0o600')

    def test_single_admin_file_migrates_to_admin_user_with_same_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / '.admin.json').write_text(json.dumps({
                'password_hash': app.generate_password_hash('Alibaba.1960'), 'session_epoch': 7,
            }), encoding='utf-8')
            library = app.Library(data / 'models', data)
            user = library.check_login('admin', 'Alibaba.1960')
            self.assertEqual((user['role'], user['epoch']), ('admin', 7))
            self.assertFalse((data / '.admin.json').exists())

    def test_cli_scan_is_refused_while_server_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = app.Library(Path(tmp) / 'models', Path(tmp))
            self.assertTrue(server.acquire_server_lock())
            self.assertFalse(app.Library(Path(tmp) / 'models', Path(tmp)).acquire_server_lock())

    def test_corrupt_database_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / 'db.json').write_text('{bozuk', encoding='utf-8')
            library = app.Library(data / 'models', data)
            self.assertEqual(library.db['version'], app.DB_VERSION)
            self.assertFalse(library.settings['public_browsing'])
            self.assertEqual(len(list(data.glob('db.corrupt-*.json'))), 1)


class HelperTests(unittest.TestCase):
    def test_safe_filename_keeps_turkish_and_blocks_paths(self):
        self.assertEqual(app.safe_filename('Çiçek Saksısı.stl'), 'Çiçek Saksısı.stl')
        self.assertEqual(app.safe_filename('../../etc/passwd'), 'passwd')
        self.assertEqual(app.safe_filename('CON.stl'), 'CON_.stl')
        self.assertEqual(app.safe_relative_path('a/../b/./c.stl'), ['a', 'b', 'c.stl'])

    def test_run_settings_use_safe_defaults(self):
        with patch.dict('os.environ', {'MODEL_MANAGER_HOST': '0.0.0.0', 'MODEL_MANAGER_PORT': 'x', 'MODEL_MANAGER_DEBUG': '1'}):
            settings = app.get_run_settings()
        self.assertEqual((settings['host'], settings['port'], settings['debug']), ('0.0.0.0', 5000, True))


if __name__ == '__main__':
    unittest.main()
