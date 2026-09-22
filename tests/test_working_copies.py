import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from tests import test_editor as fixtures
from app import working_sessions, project_files

m = fixtures.m


class WorkingCopyTests(unittest.TestCase):
    setUp = fixtures.EditorTests.setUp
    create = fixtures.EditorTests.create
    wait = fixtures.EditorTests.wait

    def test_open_legacy_open_and_save_as_copy_only_referenced_audio(self):
        pid = self.create('コピー確認')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'source.irodori'
            with patch.object(m, 'choose_path', return_value=str(target)):
                result = self.c.post(f'/api/projects/{pid}/save', json={'name': 'source', 'native_dialog': True})
            self.assertEqual(result.status_code, 200, result.text)
            p = result.json()['project']
            catalog = m.DATA / 'projects' / p['catalog_id']
            work = m.project_path(pid).parent
            raw = (work / p['rows'][0]['wav']).read_bytes()
            for root in (catalog, work):
                (root / 'audio/processed').mkdir()
                (root / 'audio/processed/cache.wav').write_bytes(b'cache')
                (root / 'audio/unused.wav').write_bytes(b'unused')
            original = {str(f): f.read_bytes() for root in (catalog, work) for f in root.rglob('*') if f.is_file()}
            opened = self.c.post(f"/api/projects/{p['catalog_id']}/open-saved").json()
            clone = m.project_path(opened['id']).parent
            self.assertEqual((clone / p['rows'][0]['wav']).read_bytes(), raw)
            self.assertFalse((clone / 'audio/processed').exists())
            self.assertFalse((clone / 'audio/unused.wav').exists())
            second = Path(folder) / 'copy.irodori'
            with patch.object(m, 'choose_path', return_value=str(second)):
                result = self.c.post(f'/api/projects/{pid}/save', json={'name': 'copy', 'native_dialog': True, 'copy_project': True})
            self.assertEqual(result.status_code, 200, result.text)
            clone = m.project_path(result.json()['project']['id']).parent
            self.assertFalse((clone / 'audio/processed').exists())
            self.assertEqual((clone / p['rows'][0]['wav']).read_bytes(), raw)
            self.assertEqual(original, {name: Path(name).read_bytes() for name in original})
            # The older direct-ID open path also omits caches.
            self.c.post(f'/api/projects/{pid}/close')
            reopened = self.c.get(f'/api/projects/{pid}')
            self.assertEqual(reopened.status_code, 200)
            self.assertFalse((m.project_path(pid).parent / 'audio/processed').exists())

    def test_missing_audio_can_open_for_regeneration(self):
        pid = self.create('欠落音声')
        p = m.read_json(m.project_path(pid), {})
        p['rows'][0].update(status='generated', wav='audio/missing.wav',
                            effective_text=m.prepare_text('欠落音声'), reference=m.settings['reference'])
        catalog = m.DATA / 'projects' / pid
        catalog.mkdir()
        m.atomic_json(catalog / 'project.json', p)
        opened = self.c.post(f'/api/projects/{pid}/open-saved')
        self.assertEqual(opened.status_code, 200, opened.text)
        new_id = opened.json()['id']
        self.assertEqual(self.c.get(f'/api/projects/{new_id}').json()['rows'][0]['status'], 'error')
        self.c.post(f'/api/projects/{new_id}/generate', json={'mode': 'all'})
        self.wait()
        self.assertEqual(self.c.get(f'/api/projects/{new_id}').json()['rows'][0]['status'], 'generated')

    def test_archive_failure_preserves_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / 'raw.wav'
            raw.write_bytes(b'original audio')
            project = {'rows': [{'id': 1, 'wav': 'raw.wav'}], 'masters': []}
            target = root / 'project.irodori'
            project_files.write_project_file(target, project, root)
            original = target.read_bytes()
            for failure in ('write', 'replace'):
                raw.write_bytes(b'new audio')
                mocked = patch.object(zipfile.ZipFile, 'write', side_effect=OSError('disk failure')) if failure == 'write' else patch.object(project_files.os, 'replace', side_effect=OSError('replace failure'))
                with mocked, self.assertRaises(OSError):
                    project_files.write_project_file(target, project, root)
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse(list(root.glob('*.tmp')))
                with zipfile.ZipFile(target) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(archive.read('audio/001.wav'), b'original audio')
            project_files.write_project_file(target, project, root)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read('audio/001.wav'), b'new audio')
