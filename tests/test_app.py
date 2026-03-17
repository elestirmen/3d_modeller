import base64
import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app

PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII='
)


def make_model(model_id, tags=None):
    return {
        model_id: {
            'id': model_id,
            'name': model_id,
            'display_name': model_id,
            'type': 'file',
            'format': 'stl',
            'path': f'{model_id}.stl',
            'abs_path': f'{model_id}.stl',
            'size': 1,
            'size_display': '1 B',
            'modified': 0,
            'files': [f'{model_id}.stl'],
            'file_count': 1,
            'suggested_tags': list(tags or []),
        }
    }


def make_snapshot(paths):
    root_files = []
    for path in paths:
        path_obj = Path(path)
        root_files.append({
            'path_obj': path_obj,
            'root_path': Path('3d models'),
            'name': path_obj.stem,
            'format': path_obj.suffix.lstrip('.').lower(),
            'rel_path': str(path_obj).replace('\\', '/'),
            'size': 1,
            'modified': 0,
        })

    return {
        'root_files': root_files,
        'groups': {'project': {}, 'folder': {}},
    }


class AppBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app.DB_PATH
        app.DB_PATH = Path(self.temp_dir.name) / 'db.json'
        app.save_db(app.default_db())
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def read_db(self):
        return json.loads(app.DB_PATH.read_text(encoding='utf-8'))

    def test_invalid_model_mutation_returns_404_and_does_not_persist(self):
        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot):
            response = self.client.post('/api/models/fake-model/favorite')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['error'], 'Model not found')
        self.assertNotIn('fake-model', self.read_db()['models'])

    def test_rescan_prunes_stale_records(self):
        project_id = app.build_model_id('real-model.stl', group_mode='project')
        app.save_db({
            'models': {
                project_id: {'tags': ['live'], 'favorite': False, 'note': '', 'printed': False},
                'stale-model': {'tags': ['old'], 'favorite': True, 'note': '', 'printed': False},
            },
            'catalog': {},
            'last_scan': None,
        })

        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot):
            response = self.client.post('/api/scan?group=project&mode=full')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['mode'], 'full')
        db = self.read_db()
        folder_id = app.build_model_id('real-model.stl', group_mode='folder')
        self.assertEqual(set(db['models']), {project_id, folder_id})
        self.assertEqual(db['models'][project_id]['tags'], ['live'])

    def test_incremental_scan_adds_new_model_without_pruning_stale_entries(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        models_root.mkdir(parents=True)
        (models_root / 'existing.stl').write_bytes(b'abc')

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            initial_response = self.client.get('/api/models?group=project')
            self.assertEqual(initial_response.status_code, 200)

            stale_id = app.build_model_id('ghost.stl', group_mode='project')
            db = self.read_db()
            db['models'][stale_id] = {'tags': ['ghost'], 'favorite': False, 'note': '', 'printed': False}
            db['catalog'][stale_id] = {
                'id': stale_id,
                'name': 'ghost',
                'display_name': 'ghost',
                'type': 'file',
                'format': 'stl',
                'path': 'ghost.stl',
                'size': 1,
                'size_display': '1 B',
                'modified': 0,
                'files': ['ghost.stl'],
                'file_count': 1,
                'suggested_tags': [],
            }
            app.save_db(db)

            time.sleep(0.02)
            (models_root / 'new.stl').write_bytes(b'def')
            scan_response = self.client.post('/api/scan?group=project')
            models_response = self.client.get('/api/models?group=project')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(scan_response.status_code, 200)
        self.assertEqual(scan_response.get_json()['mode'], 'incremental')
        self.assertEqual(scan_response.get_json()['updated'], 1)

        model_paths = {model['path'] for model in models_response.get_json()['models']}
        self.assertEqual(model_paths, {'existing.stl', 'new.stl', 'ghost.stl'})

    def test_stats_and_tags_ignore_stale_entries(self):
        project_id = app.build_model_id('real-model.stl', group_mode='project')
        app.save_db({
            'models': {
                project_id: {'tags': ['live'], 'favorite': True, 'note': '', 'printed': True},
                'stale-model': {'tags': ['old'], 'favorite': True, 'note': '', 'printed': True},
            },
            'catalog': {},
            'last_scan': None,
        })

        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot):
            stats_response = self.client.get('/api/stats?group=project')
            tags_response = self.client.get('/api/tags?group=project')

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.get_json()['favorites'], 1)
        self.assertEqual(stats_response.get_json()['printed'], 1)
        self.assertEqual(stats_response.get_json()['total'], 1)

        self.assertEqual(tags_response.status_code, 200)
        self.assertEqual(tags_response.get_json()['tags'], [{'name': 'live', 'count': 1}])

    def test_models_endpoint_uses_cached_catalog_after_initial_scan(self):
        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot) as scan_mock:
            first_response = self.client.get('/api/models?group=project')
            second_response = self.client.get('/api/models?group=project')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(scan_mock.call_count, 1)
        project_id = app.build_model_id('real-model.stl', group_mode='project')
        self.assertNotIn('abs_path', self.read_db()['catalog'][project_id])
        self.assertEqual(self.read_db()['catalog'][project_id]['path'], 'real-model.stl')

    def test_old_schema_db_without_catalog_triggers_refresh(self):
        app.DB_PATH.write_text(json.dumps({
            'models': {'legacy-model': {'tags': ['legacy'], 'favorite': False, 'note': '', 'printed': False}},
            'last_scan': 123.0,
        }), encoding='utf-8')

        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot) as scan_mock:
            response = self.client.get('/api/models?group=project')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 1)
        self.assertEqual(scan_mock.call_count, 1)
        self.assertEqual(set(self.read_db()['catalog']), {app.build_model_id('real-model.stl', group_mode='project')})

    def test_invalid_db_file_recovers_and_backs_up_corrupt_data(self):
        app.DB_PATH.write_text('{invalid', encoding='utf-8')

        snapshot = make_snapshot(['real-model.stl'])
        with patch('app.scan_model_snapshot', return_value=snapshot):
            response = self.client.get('/api/models')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 1)
        backups = list(Path(self.temp_dir.name).glob('db.corrupt-*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'), '{invalid')

    def test_scan_prefers_stl_main_file_when_project_contains_multiple_formats(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        project_dir = models_root / 'mixed-project'
        project_dir.mkdir(parents=True)
        (project_dir / 'small.stl').write_bytes(b'abc')
        (project_dir / 'large.3mf').write_bytes(b'0123456789')

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            scanned = app.scan_models()
        finally:
            app.MODELS_DIR = original_models_dir

        model = next(iter(scanned.values()))
        self.assertEqual(model['format'], 'stl')
        self.assertEqual(model['main_file'], 'mixed-project/small.stl')

    def test_file_endpoint_supports_download_mode(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        models_root.mkdir(parents=True)
        (models_root / 'part.stl').write_bytes(b'abc')

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            response = self.client.get('/api/file/part.stl?download=1')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
        response.close()

    def test_preview_endpoint_returns_embedded_3mf_thumbnail(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        models_root.mkdir(parents=True)

        model_path = models_root / 'previewable.3mf'
        with zipfile.ZipFile(model_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                '[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            archive.writestr(
                '3D/3dmodel.model',
                '<?xml version="1.0" encoding="UTF-8"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"></model>',
            )
            archive.writestr('Auxiliaries/.thumbnails/thumbnail_3mf.png', PNG_1X1)

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            response = self.client.get('/api/preview/previewable.3mf')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'image/png')
        self.assertEqual(response.data, PNG_1X1)
        response.close()

    def test_preview_endpoint_returns_404_without_embedded_image(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        models_root.mkdir(parents=True)

        model_path = models_root / 'no-preview.3mf'
        with zipfile.ZipFile(model_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                '[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            archive.writestr(
                '3D/3dmodel.model',
                '<?xml version="1.0" encoding="UTF-8"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"></model>',
            )

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            response = self.client.get('/api/preview/no-preview.3mf')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(response.status_code, 404)

    def test_scanned_catalog_strips_abs_paths_and_normalizes_separators(self):
        project_id = app.build_model_id('folder/real-model', group_mode='project')
        app.save_db({
            'models': {
                project_id: {'tags': [], 'favorite': False, 'note': '', 'printed': False},
            },
            'catalog': {
                project_id: {
                    'id': project_id,
                    'name': 'real-model',
                    'display_name': 'real-model',
                    'type': 'project',
                    'format': 'stl',
                    'path': 'folder\\real-model',
                    'main_file': 'folder\\real-model\\part.stl',
                    'abs_path': 'C:\\secret\\folder\\real-model\\part.stl',
                    'size': 1,
                    'size_display': '1 B',
                    'modified': 0,
                    'files': ['folder\\real-model\\part.stl'],
                    'file_count': 1,
                    'suggested_tags': ['tag'],
                }
            },
            'last_scan': 1.0,
        })

        response = self.client.get('/api/models?group=project')

        self.assertEqual(response.status_code, 200)
        model = response.get_json()['models'][0]
        self.assertEqual(model['path'], 'folder/real-model')
        self.assertEqual(model['main_file'], 'folder/real-model/part.stl')
        self.assertEqual(model['files'], ['folder/real-model/part.stl'])
        self.assertNotIn('abs_path', model)

        catalog_model = self.read_db()['catalog'][project_id]
        self.assertEqual(catalog_model['path'], 'folder/real-model')
        self.assertEqual(catalog_model['main_file'], 'folder/real-model/part.stl')
        self.assertNotIn('abs_path', catalog_model)

    def test_folder_group_mode_groups_by_immediate_parent_folder(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        (models_root / 'set-a' / 'alpha').mkdir(parents=True)
        (models_root / 'set-a' / 'beta').mkdir(parents=True)
        (models_root / 'set-a' / 'alpha' / 'part-1.stl').write_bytes(b'abc')
        (models_root / 'set-a' / 'alpha' / 'part-2.stl').write_bytes(b'def')
        (models_root / 'set-a' / 'beta' / 'single.stl').write_bytes(b'ghi')
        (models_root / 'loose.stl').write_bytes(b'xyz')

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            project_response = self.client.get('/api/models?group=project')
            folder_response = self.client.get('/api/models')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(project_response.get_json()['total'], 2)

        self.assertEqual(folder_response.status_code, 200)
        self.assertEqual(folder_response.get_json()['total'], 3)
        folder_models = folder_response.get_json()['models']
        grouped = {model['display_name']: model for model in folder_models}
        self.assertEqual(grouped['alpha']['file_count'], 2)
        self.assertEqual(grouped['alpha']['type'], 'folder')
        self.assertTrue(grouped['alpha']['id'].startswith('folder:'))

    def test_folder_group_mode_preserves_project_view_metadata(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        (models_root / 'set-a' / 'alpha').mkdir(parents=True)
        (models_root / 'set-a' / 'beta').mkdir(parents=True)
        (models_root / 'set-a' / 'alpha' / 'part-1.stl').write_bytes(b'abc')
        (models_root / 'set-a' / 'beta' / 'single.stl').write_bytes(b'def')

        original_models_dir = app.MODELS_DIR
        app.MODELS_DIR = models_root
        try:
            project_response = self.client.get('/api/models?group=project')
            project_model_id = next(
                model['id']
                for model in project_response.get_json()['models']
                if model['type'] == 'project'
            )
            favorite_response = self.client.post(f'/api/models/{project_model_id}/favorite')
            folder_response = self.client.get('/api/models')
        finally:
            app.MODELS_DIR = original_models_dir

        self.assertEqual(favorite_response.status_code, 200)
        self.assertEqual(folder_response.status_code, 200)

        db = self.read_db()
        self.assertTrue(db['models'][project_model_id]['favorite'])
        self.assertTrue(any(model_id.startswith('folder:') for model_id in db['models']))

    def test_invalid_json_body_returns_400_without_clearing_tags(self):
        scanned = make_model('real-model')
        model_id = 'real-model'
        app.save_db({
            'models': {
                model_id: {'tags': ['keep'], 'favorite': False, 'note': '', 'printed': False},
            },
            'catalog': scanned,
            'last_scan': 1.0,
        })

        response = self.client.post(
            f'/api/models/{model_id}/tags',
            data='{bad',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'Invalid JSON body')
        self.assertEqual(self.read_db()['models'][model_id]['tags'], ['keep'])

    def test_invalid_json_body_returns_400_without_clearing_note(self):
        scanned = make_model('real-model')
        model_id = 'real-model'
        app.save_db({
            'models': {
                model_id: {'tags': [], 'favorite': False, 'note': 'keep', 'printed': False},
            },
            'catalog': scanned,
            'last_scan': 1.0,
        })

        response = self.client.post(
            f'/api/models/{model_id}/note',
            data='{bad',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'Invalid JSON body')
        self.assertEqual(self.read_db()['models'][model_id]['note'], 'keep')

    def test_concurrent_mutations_preserve_both_updates(self):
        models_root = Path(self.temp_dir.name) / '3d models'
        models_root.mkdir(parents=True)
        (models_root / 'a.stl').write_bytes(b'abc')
        (models_root / 'b.stl').write_bytes(b'def')

        original_models_dir = app.MODELS_DIR
        original_save = app._save_db_unlocked
        app.MODELS_DIR = models_root
        try:
            self.client.get('/api/models')
            model_a = app.generate_id('a.stl')
            model_b = app.generate_id('b.stl')
            statuses = []

            def slow_save(db):
                time.sleep(0.05)
                return original_save(db)

            def toggle_favorite():
                client = app.app.test_client()
                statuses.append(client.post(f'/api/models/{model_a}/favorite').status_code)

            def toggle_printed():
                client = app.app.test_client()
                statuses.append(client.post(f'/api/models/{model_b}/printed').status_code)

            with patch('app._save_db_unlocked', side_effect=slow_save):
                first = threading.Thread(target=toggle_favorite)
                second = threading.Thread(target=toggle_printed)
                first.start()
                second.start()
                first.join()
                second.join()
        finally:
            app.MODELS_DIR = original_models_dir

        db = self.read_db()
        self.assertEqual(sorted(statuses), [200, 200])
        self.assertTrue(db['models'][model_a]['favorite'])
        self.assertTrue(db['models'][model_b]['printed'])

    def test_safe_console_text_replaces_unencodable_characters(self):
        self.assertEqual(app.safe_console_text('🧊', encoding='cp1254'), '?')

    def test_print_startup_banner_supports_legacy_console_encodings(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding='cp1254', errors='strict')

        app.print_startup_banner(stream=stream)
        stream.flush()

        banner = buffer.getvalue().decode('cp1254')
        self.assertIn('3D Model Manager starting...', banner)
        self.assertIn('Open http://localhost:5000', banner)

    def test_get_run_settings_uses_env_overrides_with_safe_defaults(self):
        with patch.dict('os.environ', {
            'MODEL_MANAGER_HOST': '0.0.0.0',
            'MODEL_MANAGER_PORT': 'not-a-port',
            'MODEL_MANAGER_DEBUG': '1',
        }, clear=False):
            settings = app.get_run_settings()

        self.assertEqual(settings['host'], '0.0.0.0')
        self.assertEqual(settings['port'], 5000)
        self.assertTrue(settings['debug'])


if __name__ == '__main__':
    unittest.main()
