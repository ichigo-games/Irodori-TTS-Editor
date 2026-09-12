"""Launch with the existing engine Python; never modify its environment."""
import os
import subprocess
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    python = Path(os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')) / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        raise SystemExit('IrodoriのPythonがありません。IRODORI_HOMEを設定してください。')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    raise SystemExit(subprocess.call([str(python), '-B', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765'], cwd=root, env=env))
