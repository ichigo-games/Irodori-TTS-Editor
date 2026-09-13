import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_editor as fixtures
m, temp = fixtures.m, fixtures.temp

class ManualSaveTests(unittest.TestCase):
    setUp=fixtures.EditorTests.setUp
    create=fixtures.EditorTests.create
    def test_manual_working_copy(self):
        before=set(p.name for p in (m.DATA/'projects').iterdir())
        pid=self.create('保存テスト')
        self.assertEqual(before,set(p.name for p in (m.DATA/'projects').iterdir()))
        self.assertTrue(self.c.get(f'/api/projects/{pid}').json()['dirty'])
        self.assertEqual(self.c.put(f'/api/projects/{pid}/autosave',json={'enabled':True}).status_code,400)
        target=Path(temp.name)/'manual.irodori'
        with patch.object(m,'choose_path',return_value=str(target)):
            result=self.c.post(f'/api/projects/{pid}/save',json={'name':'manual','native_dialog':True})
        self.assertEqual(result.status_code,200,result.text)
        self.assertFalse(result.json()['project']['dirty'])
        saved=(m.DATA/'projects'/pid/'project.json').read_bytes()
        archive=target.read_bytes()
        row=self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        self.c.put(f'/api/projects/{pid}/rows/1',json={**row,'subtitle_text':'変更'})
        self.assertEqual((m.DATA/'projects'/pid/'project.json').read_bytes(),saved)
        self.assertEqual(target.read_bytes(),archive)
        self.c.post(f'/api/projects/{pid}/close')
        reopened=self.c.get(f'/api/projects/{pid}').json()
        self.assertEqual(reopened['rows'][0]['subtitle_text'],'保存テスト')
        self.assertFalse(reopened['dirty'])
        self.assertFalse(reopened['autosave'])
        for _ in range(2):
            with patch.object(m,'choose_path',return_value=str(target)):
                opened=self.c.post('/api/projects/open-file').json()['project']
            self.assertNotEqual(opened['id'],pid)
            result=self.c.post(f"/api/projects/{opened['id']}/save",json={'name':'manual'})
            self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(list((m.DATA/'projects').glob('*/project.json'))),len(before)+1)
        self.assertTrue(self.c.put(f'/api/projects/{pid}/autosave',json={'enabled':True}).json()['autosave'])

    def test_save_as_and_cancel(self):
        pid=self.create('別名テスト')
        first=Path(temp.name)/'first-manual.irodori'
        with patch.object(m,'choose_path',return_value=str(first)):
            result=self.c.post(f'/api/projects/{pid}/save',json={'name':'first','native_dialog':True})
        original_catalog=result.json()['project']['catalog_id']
        second=Path(temp.name)/'second-manual.irodori'
        with patch.object(m,'choose_path',return_value=str(second)):
            result=self.c.post(f'/api/projects/{pid}/save',json={'name':'second','native_dialog':True})
        self.assertNotEqual(result.json()['project']['catalog_id'],original_catalog)
        opened=self.c.post(f'/api/projects/{original_catalog}/open-saved').json()
        self.assertEqual(opened['name'],'first-manual')
        self.assertFalse(opened['dirty'])
        before=first.read_bytes()
        with patch.object(m,'choose_path',return_value=''):
            result=self.c.post(f'/api/projects/{pid}/save',json={'name':'cancel','native_dialog':True})
        self.assertTrue(result.json()['cancelled'])
        self.assertEqual(first.read_bytes(),before)
