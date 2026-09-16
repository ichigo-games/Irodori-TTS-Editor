import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.tts import resolve_checkpoint


class CheckpointTests(unittest.TestCase):
    def test_local_model_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'model.safetensors'
            model.touch()
            download = Mock()
            with patch.dict(os.environ, {'IRODORI_CHECKPOINT': str(model)}, clear=True):
                self.assertEqual(resolve_checkpoint(download), str(model))
            download.assert_not_called()

    def test_missing_fixed_model_fails_without_fallback(self):
        download = Mock()
        with patch.dict(os.environ, {'IRODORI_CHECKPOINT': 'missing/model.safetensors'}, clear=True):
            with self.assertRaises(FileNotFoundError):
                resolve_checkpoint(download)
        download.assert_not_called()

    def test_trial_model_selection(self):
        download = Mock(return_value='downloaded.safetensors')
        with patch.dict(os.environ, {'IRODORI_HF_CHECKPOINT': 'owner/trial'}, clear=True):
            self.assertEqual(resolve_checkpoint(download), 'downloaded.safetensors')
        download.assert_called_once_with('owner/trial')


class LauncherTests(unittest.TestCase):
    def test_separate_python_data_code_and_port(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            python = home / '.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True)
            python.touch()
            env = {'IRODORI_HOME': str(home), 'EDITOR_DATA': str(home / 'data'),
                   'EDITOR_CODE': str(home / 'editor'), 'EDITOR_PORT': '8766'}
            with patch.dict(os.environ, env, clear=True), patch('sys.argv', ['run.py']), \
                    patch('subprocess.call', return_value=0) as launch:
                with self.assertRaises(SystemExit) as result:
                    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'run.py'), run_name='__main__')
            self.assertEqual(result.exception.code, 0)
            command = launch.call_args.args[0]
            self.assertEqual(command[0], str(python))
            self.assertEqual(command[-1], '8766')
            self.assertEqual(launch.call_args.kwargs['cwd'], home / 'editor')
            self.assertEqual(launch.call_args.kwargs['env']['EDITOR_DATA'], str(home / 'data'))
