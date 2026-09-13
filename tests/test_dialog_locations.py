import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests import test_editor as fixtures

m = fixtures.m


class DialogLocationsTests(unittest.TestCase):
    def test_persistent_button_history_legacy_cancel_and_missing_folder(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'DATA', Path(folder)):
            data = Path(folder)
            scripts = data / '台本'; scripts.mkdir()
            projects = data / 'プロジェクト'; projects.mkdir()
            history = data / 'dialog_locations.json'
            history.write_text(json.dumps({'script:台本を選択': str(scripts)}), encoding='utf-8')

            def choose(kind, title, key, selected='', initial=''):
                result = SimpleNamespace(returncode=0, stdout=json.dumps({'path': str(selected)}))
                with patch.object(m.subprocess, 'run', return_value=result) as run:
                    m.choose_path(kind, title, initial, location_key=key)
                    return json.loads(run.call_args.kwargs['input'])['initialdir']

            self.assertEqual(choose('script', '台本を選択', 'script', scripts/'a.csv'), scripts.as_posix())
            choose('open', 'プロジェクトを開く', 'project_open', projects/'a.irodori')
            before = history.read_bytes()
            self.assertEqual(choose('script', '変更後のタイトル', 'script', initial=str(projects)), scripts.as_posix())
            self.assertEqual(choose('open', '変更後のタイトル', 'project_open'), projects.as_posix())
            self.assertEqual(history.read_bytes(), before)
            scripts.rmdir()
            self.assertEqual(choose('script', '台本を選択', 'script', initial=str(projects)), projects.as_posix())
            self.assertEqual(choose('script', '台本を選択', 'script'), m.ROOT.as_posix())
