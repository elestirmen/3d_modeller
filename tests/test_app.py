import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


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
        scanned = make_model('real-model')
        with patch('app.scan_models', return_value=scanned):
            response = self.client.post('/api/models/fake-model/favorite')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['error'], 'Model not found')
        self.assertNotIn('fake-model', self.read_db()['models'])

    def test_rescan_prunes_stale_records(self):
        app.save_db({
            'models': {
                'real-model': {'tags': ['live'], 'favorite': False, 'note': '', 'printed': False},
                'stale-model': {'tags': ['old'], 'favorite': True, 'note': '', 'printed': False},
            },
            'catalog': {},
            'last_scan': None,
        })

        with patch('app.scan_models', return_value=make_model('real-model', tags=['suggested'])):
            response = self.client.post('/api/scan')

        self.assertEqual(response.status_code, 200)
        db = self.read_db()
        self.assertEqual(set(db['models']), {'real-model'})
        self.assertEqual(db['models']['real-model']['tags'], ['live'])

    def test_stats_and_tags_ignore_stale_entries(self):
        app.save_db({
            'models': {
                'real-model': {'tags': ['live'], 'favorite': True, 'note': '', 'printed': True},
                'stale-model': {'tags': ['old'], 'favorite': True, 'note': '', 'printed': True},
            },
            'catalog': {},
            'last_scan': None,
        })

        with patch('app.scan_models', return_value=make_model('real-model')):
            stats_response = self.client.get('/api/stats')
            tags_response = self.client.get('/api/tags')

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.get_json()['favorites'], 1)
        self.assertEqual(stats_response.get_json()['printed'], 1)
        self.assertEqual(stats_response.get_json()['total'], 1)

        self.assertEqual(tags_response.status_code, 200)
        self.assertEqual(tags_response.get_json()['tags'], [{'name': 'live', 'count': 1}])

    def test_models_endpoint_uses_cached_catalog_after_initial_scan(self):
        scanned = make_model('real-model')
        with patch('app.scan_models', return_value=scanned) as scan_mock:
            first_response = self.client.get('/api/models')
            second_response = self.client.get('/api/models')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(scan_mock.call_count, 1)
        self.assertEqual(self.read_db()['catalog'], scanned)

    def test_old_schema_db_without_catalog_triggers_refresh(self):
        app.DB_PATH.write_text(json.dumps({
            'models': {'legacy-model': {'tags': ['legacy'], 'favorite': False, 'note': '', 'printed': False}},
            'last_scan': 123.0,
        }), encoding='utf-8')

        with patch('app.scan_models', return_value=make_model('real-model')) as scan_mock:
            response = self.client.get('/api/models')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 1)
        self.assertEqual(scan_mock.call_count, 1)
        self.assertEqual(set(self.read_db()['catalog']), {'real-model'})

    def test_invalid_db_file_recovers_and_backs_up_corrupt_data(self):
        app.DB_PATH.write_text('{invalid', encoding='utf-8')

        with patch('app.scan_models', return_value=make_model('real-model')):
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
        self.assertEqual(model['main_file'], 'mixed-project\\small.stl')


if __name__ == '__main__':
    unittest.main()
