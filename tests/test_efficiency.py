import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_editor as fixtures
from app import post_processing, working_sessions
from app.project_management import file_digest

m = fixtures.m


class EfficiencyTests(unittest.TestCase):
    setUp = fixtures.EditorTests.setUp
    create = fixtures.EditorTests.create

    def clean_generated(self, text):
        pid = self.create(text)
        path = m.project_path(pid)
        p = m.read_json(path, {})
        for row in p['rows']:
            row.update(status='generated', effective_text=m.prepare_text(row['speech_text']),
                       reference=m.resolve_reference(row), wav='audio/test.wav')
        (path.parent / 'audio').mkdir(exist_ok=True)
        (path.parent / 'audio/test.wav').write_bytes(b'raw audio')
        p['dirty'] = False
        m.atomic_json(path, p, mark_dirty=False)
        return pid

    def test_settings_and_dictionary_only_dirty_affected_projects(self):
        affected = self.clean_generated('対象')
        other = self.clean_generated('別の文章')
        before = {pid: m.project_path(pid).read_bytes() for pid in (affected, other)}
        value = {key: m.settings[key] for key in m.Settings.model_fields}
        self.assertEqual(self.c.put('/api/settings', json=value).status_code, 200)
        self.assertEqual(self.c.put('/api/dictionary', json=[]).status_code, 200)
        self.assertEqual(before, {pid: m.project_path(pid).read_bytes() for pid in before})
        self.assertEqual(self.c.put('/api/dictionary', json=[{'word': '対象', 'reading': 'たいしょう', 'enabled': True}]).status_code, 200)
        self.assertTrue(m.read_json(m.project_path(affected), {})['dirty'])
        self.assertEqual(m.read_json(m.project_path(affected), {})['rows'][0]['status'], 'stale')
        self.assertEqual(before[other], m.project_path(other).read_bytes())

    def test_normalization_setting_invalidates_immediately(self):
        pid = self.clean_generated('123')
        value = {key: m.settings[key] for key in m.Settings.model_fields}
        value['normalize_numbers'] = False
        self.assertEqual(self.c.put('/api/settings', json=value).status_code, 200)
        self.assertTrue(self.c.get(f'/api/projects/{pid}/save-status').json()['dirty'])

    def test_preview_once_and_light_poll_no_text_or_catalog_reads(self):
        pid = self.clean_generated('一行\n二行\n三行')
        with patch.object(m, 'prepare_text', wraps=m.prepare_text) as prepare:
            response = self.c.get(f'/api/projects/{pid}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(prepare.call_count, 3)
        self.assertTrue(all('preview' in row for row in response.json()['rows']))
        self.assertTrue(all('preview' not in row for row in m.read_json(m.project_path(pid), {})['rows']))
        with patch.object(m, 'prepare_text', side_effect=AssertionError('unnecessary text work')):
            self.assertEqual(self.c.get(f'/api/projects/{pid}/save-status').json(), {'dirty': False, 'autosave': False})
        with patch.object(m, 'read_json', side_effect=AssertionError('unnecessary catalog read')):
            response = self.c.get('/api/state?light=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('operation', response.json())
        self.assertNotIn('projects', response.json())

    def test_usage_reads_each_project_once(self):
        self.create('使用状況')
        masters = [{'id': str(i), 'name': str(i), 'reference': m.settings['reference']} for i in range(8)]
        with patch.dict(m.settings, masters=masters):
            with patch.object(m, 'read_json', wraps=m.read_json) as read:
                self.assertEqual(self.c.get('/api/masters').status_code, 200)
        paths = [str(call.args[0]) for call in read.call_args_list]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertGreater(len(paths), 0)

    def test_shared_cache_change_and_missing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / 'dictionaries').mkdir()
            settings_file = source / 'settings.json'
            settings_file.write_text('{"masters": []}')
            dictionary_file = source / 'dictionaries/reading.json'
            dictionary_file.write_text('[]')
            with patch.object(m, 'SHARED_DATA', source), patch.object(m, 'shared_signature', None):
                with patch.object(m, 'read_library', wraps=m.read_library) as read:
                    for _ in range(3):
                        self.assertEqual(self.c.get('/api/state?light=true').status_code, 200)
                    self.assertEqual(read.call_count, 1)
                    response = self.c.get(f'/api/state?light=true&library_revision={m.shared_revision}')
                    self.assertNotIn('dictionary', response.json())
                    self.assertNotIn('settings', response.json())
                    dictionary_file.write_text('[{"word":"a","reading":"b"}]')
                    self.assertEqual(self.c.get('/api/state?light=true').status_code, 200)
                    self.assertEqual(read.call_count, 2)
                    self.assertEqual(m.prepare_text('a'), 'b')
                    settings_file.unlink()
                    self.assertEqual(self.c.get('/api/state?light=true').status_code, 503)
                    self.assertEqual(self.c.get('/').status_code, 200)

    def test_snapshot_only_copies_changed_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            (source / 'audio/processed').mkdir(parents=True)
            raw = source / 'audio/raw.wav'
            raw.write_bytes(b'original')
            (source / 'audio/processed/cache.wav').write_bytes(b'cache')
            project = {'rows': [{'wav': 'audio/raw.wav'}, {'wav': 'audio/raw.wav'}]}
            working_sessions.copy_snapshot(source, target, project)
            self.assertFalse((target / 'audio/processed').exists())
            with patch.object(working_sessions.shutil, 'copy2', wraps=working_sessions.shutil.copy2) as copy_file:
                working_sessions.copy_snapshot(source, target, project)
                self.assertEqual(copy_file.call_count, 0)
                raw.write_bytes(b'changed raw audio')
                working_sessions.copy_snapshot(source, target, project)
                self.assertEqual(copy_file.call_count, 1)
            self.assertEqual(raw.read_bytes(), (target / 'audio/raw.wav').read_bytes())
            self.assertEqual(file_digest(raw), file_digest(target / 'audio/raw.wav'))

    def test_eq_fast_path_matches_fallback_and_zero_gain_skipped(self):
        import numpy as np
        import builtins
        samples = np.random.default_rng(1).normal(size=24000)
        expected = post_processing._peaking_eq(samples, 24000, 3500, -1.5, 1)
        original_import = builtins.__import__
        def without_scipy(name, *args, **kwargs):
            if name == 'scipy.signal':
                raise ImportError('fallback')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_scipy):
            actual = post_processing._peaking_eq(samples, 24000, 3500, -1.5, 1)
        np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=1e-12)
        self.assertEqual(post_processing._build_steps({'eq_enabled': True, 'gain_db': 0}), [])
        self.assertEqual(post_processing._build_steps({'eq_enabled': True, 'gain_db': 0, 'peak_enabled': True}), [('peak', -1.0)])

    def test_import_hashes_registry_once_and_reuses_matches(self):
        from app.project_files import write_project_file
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            voices = []
            for i in range(3):
                audio = root / f'{i}.wav'
                audio.write_bytes(bytes([i]) * 100)
                voices.append({'id': str(i), 'name': str(i), 'reference': str(audio)})
            pid = self.create('一行\n二行')
            project = m.read_json(m.project_path(pid), {})
            for row, voice in zip(project['rows'], voices):
                row.update(master_id=voice['id'], reference=voice['reference'])
            project['masters'] = copy.deepcopy(voices[:2])
            archive = root / 'import.irodori'
            write_project_file(archive, project, m.project_path(pid).parent)
            with patch.dict(m.settings, masters=voices), patch.object(m, 'choose_path', return_value=str(archive)):
                with patch.object(m, 'file_digest', wraps=m.file_digest) as digest:
                    result = self.c.post('/api/projects/open-file')
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(digest.call_count, 5)
                self.assertEqual(len(m.settings['masters']), 3)
                self.assertEqual([r['master_id'] for r in result.json()['project']['rows']], ['0', '1'])

    def test_save_without_audio_then_reopen_and_generate(self):
        pid = self.create('未生成のまま保存')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'pending.irodori'
            with patch.object(m, 'choose_path', return_value=str(target)):
                saved = self.c.post(f'/api/projects/{pid}/save', json={'name': 'pending', 'native_dialog': True})
            self.assertEqual(saved.status_code, 200, saved.text)
            reopened = self.c.post(f'/api/projects/{pid}/open-saved').json()
            result = self.c.post(f"/api/projects/{reopened['id']}/generate", json={'mode': 'all'})
            self.assertEqual(result.status_code, 200, result.text)
            fixtures.EditorTests.wait(self)
            self.assertEqual(self.c.get(f"/api/projects/{reopened['id']}").json()['rows'][0]['status'], 'generated')
