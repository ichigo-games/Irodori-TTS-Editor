import threading
import uuid
from pathlib import Path
from unittest.mock import patch
from tests import test_editor as fixtures
import unittest

m = fixtures.m


class OperationTests(unittest.TestCase):
    setUp = fixtures.EditorTests.setUp
    create = fixtures.EditorTests.create
    wait = fixtures.EditorTests.wait

    def test_generation_scope_duplicates_and_other_project_edits(self):
        a, b = self.create('一\n二'), self.create('別')
        entered, release = threading.Event(), threading.Event()
        original = m.engine.generate
        def generate(*args):
            entered.set()
            release.wait(5)
            return original(*args)
        token = uuid.uuid4().hex
        with patch.object(m.engine, 'generate', side_effect=generate):
            try:
                result = self.c.post(f'/api/projects/{a}/generate', json={'mode': 'all'}, headers={'X-Operation-ID': token})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertTrue(entered.wait(2))
                for pid in (a, b):
                    for route in ('generate', 'export'):
                        r = self.c.post(f'/api/projects/{pid}/{route}', json={})
                        self.assertEqual(r.status_code, 409)
                r = self.c.post(f'/api/projects/{b}/rows', json={'text': '追記'})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(self.c.post(f'/api/projects/{a}/rows', json={'text': '拒否'}).status_code, 409)
                for pid, key in ((b, token), (a, 'old-token')):
                    self.assertEqual(self.c.post(f'/api/projects/{pid}/stop-generation', headers={'X-Operation-ID': key}).status_code, 409)
                    self.assertFalse(m.stop_event.is_set())
                self.assertEqual(self.c.post(f'/api/projects/{a}/stop-generation', headers={'X-Operation-ID': token}).status_code, 200)
            finally:
                release.set()
                self.wait()
        self.assertIsNone(m.operations.snapshot())
        self.assertEqual(self.c.post(f'/api/projects/{a}/generate', json={'mode': 'all'}, headers={'X-Operation-ID': token}).status_code, 409)

    def test_shared_export_stop_and_no_queued_duplicates(self):
        a, b = self.create('一\n二'), self.create('別')
        self.c.post(f'/api/projects/{a}/generate', json={'mode': 'all'})
        self.wait()
        entered, release = threading.Event(), threading.Event()
        original = m.publish_export_pair
        results = []
        token = uuid.uuid4().hex
        folder = Path(fixtures.temp.name) / uuid.uuid4().hex
        def publish(*args):
            entered.set()
            release.wait(5)
            return original(*args)
        with patch.object(m, 'SHARED_DATA', Path(fixtures.temp.name)/'source'), patch.object(m, 'read_library', return_value=([], [])), patch.object(m, 'library_signature', return_value=('mock-source',)), patch.object(m, 'shared_signature', None), patch.object(m, 'publish_export_pair', side_effect=publish):
            worker = threading.Thread(target=lambda: results.append(self.c.post(f'/api/projects/{a}/export', json={'folder': str(folder)}, headers={'X-Operation-ID': token})))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                for kind in ('generate', 'export'):
                    self.assertEqual(self.c.post(f'/api/projects/{b}/{kind}', json={}).status_code, 409)
                self.assertEqual(self.c.post(f'/api/projects/{b}/stop-generation').status_code, 409)
                r = self.c.post(f'/api/projects/{a}/stop-generation', headers={'X-Operation-ID': token})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(m.stop_event.is_set())
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].json()['count'], 1)
        self.assertTrue(results[0].json()['stopped'])
        self.assertIsNone(m.operations.snapshot())

    def test_rejected_request_releases_admission(self):
        pid = self.create('一')
        self.assertEqual(self.c.post(f'/api/projects/{pid}/export', json={}).status_code, 400)
        self.assertIsNone(m.operations.snapshot())
        self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'}).status_code, 200)
        self.wait()

    def test_other_project_can_edit_between_exported_files(self):
        a, b = self.create('一\n二'), self.create('別')
        self.c.post(f'/api/projects/{a}/generate', json={'mode': 'all'})
        self.wait()
        responses = []
        original = m.time.sleep
        def spacing(delay):
            if delay == 1.0:
                responses.append(self.c.post(f'/api/projects/{b}/rows', json={'text': '出力中に追加'}))
                responses.append(self.c.post(f'/api/projects/{a}/rows', json={'text': '拒否'}))
            else:
                original(delay)
        with patch.object(m.time, 'sleep', side_effect=spacing):
            result = self.c.post(f'/api/projects/{a}/export', json={'folder': str(Path(fixtures.temp.name)/uuid.uuid4().hex)})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([r.status_code for r in responses], [200, 409])
