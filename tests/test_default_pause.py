import copy
import json
import unittest
from tests import test_editor as fixtures

m = fixtures.m


class DefaultPauseTests(unittest.TestCase):
    def setUp(self):
        fixtures.EditorTests.setUp(self)
        self.previous = copy.deepcopy(m.settings)

    def tearDown(self):
        m.settings.clear()
        m.settings.update(self.previous)

    def save(self, value):
        return self.c.put('/api/settings', json={'reference': m.settings['reference'], 'default_pause_ms': value})

    def test_import_defaults_override_and_existing_rows(self):
        self.assertEqual(self.save(350).status_code, 200)
        txt = self.c.post('/api/projects', files={'file': ('script.txt', '一行\n二行'.encode())}).json()
        self.assertEqual([r['pause_ms'] for r in txt['rows']], [350, 350])
        csv = 'text,master,pause_ms\n省略,,\nゼロ,,0\n指定,,725'
        result = self.c.post('/api/projects', files={'file': ('script.csv', csv.encode())}).json()
        self.assertEqual([r['pause_ms'] for r in result['rows']], [350, 0, 725])
        self.save(0)
        self.assertEqual(self.c.get('/api/projects/'+txt['id']).json()['rows'][0]['pause_ms'], 350)
        fresh = self.c.post('/api/projects', files={'file': ('script.csv', 'text\n省略'.encode())}).json()
        self.assertEqual(fresh['rows'][0]['pause_ms'], 0)
        self.assertEqual(json.loads((m.DATA/'settings.json').read_text())['default_pause_ms'], 0)

    def test_validation_and_legacy_settings_request(self):
        self.save(60000)
        for value in (-1, 60001, 1.5, True, '200'):
            self.assertEqual(self.save(value).status_code, 422)
        self.c.put('/api/settings', json={'reference': m.settings['reference'], 'duration_scale': .9})
        self.assertEqual(m.settings['default_pause_ms'], 60000)
