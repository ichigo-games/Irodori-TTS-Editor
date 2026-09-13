import json
import tempfile
import unittest
from pathlib import Path
from app.project_management import migrate_references, move_project, store_voice

class ProjectManagementTests(unittest.TestCase):
    def test_migrate_trash_restore_preserves_shared_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);pid='a'*32;other='b'*32
            source=data/'projects'/pid/'masters'/'0.wav';source.parent.mkdir(parents=True)
            source.write_bytes(b'voice-original')
            settings={'reference':str(source),'masters':[{'id':'master','reference':str(source)}]}
            def write(path,value):path.write_text(json.dumps(value),encoding='utf-8')
            write(data/'settings.json',settings)
            for key in (pid,other):
                directory=data/'projects'/key;directory.mkdir(exist_ok=True)
                write(directory/'project.json',{'id':key,'rows':[{'reference':str(source),'status':'generated','wav':'audio/test.wav'}]})
            migrate_references(data,settings,write)
            shared=Path(settings['reference']);self.assertEqual(shared.read_bytes(),b'voice-original')
            self.assertTrue((data/'voices').resolve() in shared.parents)
            self.assertTrue(source.exists())
            for key in (pid,other):
                path=data/'projects'/key/'project.json';row=json.loads(path.read_text())['rows'][0]
                self.assertEqual(row['reference'],str(shared));self.assertEqual(row['status'],'generated')
                self.assertTrue(path.with_name('project.json.before-voice-migration.bak').exists())
            migrate_references(data,settings,write)
            self.assertEqual(store_voice(data,shared),str(shared))
            move_project(data,pid)
            self.assertFalse((data/'projects'/pid).exists());self.assertTrue(shared.exists())
            move_project(data,pid,restore=True)
            self.assertTrue((data/'projects'/pid/'project.json').exists())
            with self.assertRaises(ValueError):move_project(data,'../voices')
            (data/'trash'/pid).mkdir(parents=True)
            with self.assertRaises(ValueError):move_project(data,pid)

    def test_missing_voice_does_not_rewrite_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);settings={'reference':str(data/'projects'/('a'*32)/'missing.wav')}
            before=dict(settings)
            with self.assertRaises(ValueError):migrate_references(data,settings,lambda *_:None)
            self.assertEqual(settings,before)
