import copy
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from tests import test_editor as fixtures

m = fixtures.m


class SharedLibraryTests(unittest.TestCase):
    def setUp(self):
        fixtures.EditorTests.setUp(self)
        self.before = copy.deepcopy(m.settings)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'normal'
        (self.source / 'dictionaries').mkdir(parents=True)
        self.voice = self.source / 'voice.wav'
        with wave.open(str(self.voice), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b'\0\0' * 240)
        self.master = {'id': 'master1', 'name': '通常マスター', 'reference': 'voice.wav'}
        self.write_source('参照した読み')
        self.original = {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        self.shared = patch.object(m, 'SHARED_DATA', self.source)
        self.shared.start()
        self.addCleanup(self.shared.stop)

    def tearDown(self):
        m.job['running'] = False
        m.settings.clear()
        m.settings.update(self.before)
        m.dictionary.clear()

    def write_source(self, reading):
        (self.source / 'settings.json').write_text(json.dumps({'masters': [self.master], 'duration_scale': 3.5}), encoding='utf-8')
        (self.source / 'dictionaries/reading.json').write_text(json.dumps([{'word': '共有語', 'reading': reading, 'enabled': True}]), encoding='utf-8')

    def test_read_only_and_local_settings(self):
        state = self.c.get('/api/state').json()
        master = next(x for x in state['settings']['masters'] if x.get('shared'))
        self.assertEqual(master['reference'], str(self.voice.resolve()))
        self.assertEqual(m.prepare_text('共有語'), '参照した読み')
        self.assertEqual(state['settings']['duration_scale'], 1)
        for method, path, data in [
            ('PUT', '/api/dictionary', []),
            ('POST', '/api/masters', {'name': '追加', 'reference': str(self.voice)}),
            ('PUT', '/api/masters/shared:master1', {'name': '改名'}),
            ('DELETE', '/api/masters/shared:master1', None),
        ]:
            result = self.c.request(method, path, json=data)
            self.assertEqual(result.status_code, 403, result.text)
        result = self.c.post('/api/masters/upload', data={'name': '追加'}, files={'file': ('voice.wav', self.voice.read_bytes())})
        self.assertEqual(result.status_code, 403)
        result = self.c.put('/api/settings', json={'reference': master['reference'], 'duration_scale': .8})
        self.assertEqual(result.status_code, 200, result.text)
        stored = json.loads((m.DATA / 'settings.json').read_text())
        self.assertFalse(any(x.get('shared') for x in stored['masters']))
        self.assertEqual(stored['reference'], master['reference'])
        self.assertEqual(self.original, {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_refresh_deferred_during_generation_and_missing_source(self):
        self.c.get('/api/state')
        m.job['running'] = True
        self.master['name'] = '変更後'
        self.write_source('更新後')
        self.c.get('/api/state')
        self.assertEqual(m.prepare_text('共有語'), '参照した読み')
        m.job['running'] = False
        result = self.c.get('/api/state').json()
        self.assertEqual(m.prepare_text('共有語'), '更新後')
        self.assertEqual(next(x for x in result['settings']['masters'] if x.get('shared'))['name'], '変更後')
        (self.source / 'settings.json').unlink()
        self.assertEqual(self.c.get('/api/state').status_code, 503)

    def test_project_round_trip_reuses_shared_master(self):
        self.c.get('/api/state')
        pid = fixtures.EditorTests.create(self, '共有語')
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        result = self.c.put(f'/api/projects/{pid}/rows/1', json={**row, 'master_id': 'shared:master1'})
        self.assertEqual(result.status_code, 200, result.text)
        target = Path(self.directory.name) / 'trial.irodori'
        with patch.object(m, 'choose_path', return_value=str(target)):
            result = self.c.post(f'/api/projects/{pid}/save', json={'name': 'trial', 'native_dialog': True})
        self.assertEqual(result.status_code, 200, result.text)
        count = len(m.settings['masters'])
        for _ in range(2):
            with patch.object(m, 'choose_path', return_value=str(target)):
                result = self.c.post('/api/projects/open-file')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['project']['rows'][0]['master_id'], 'shared:master1')
            self.assertEqual(len(m.settings['masters']), count)
        with patch.object(m, 'choose_path', return_value=str(self.source / 'blocked.irodori')):
            result = self.c.post(f'/api/projects/{pid}/save', json={'name': 'blocked', 'native_dialog': True})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.original, {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
