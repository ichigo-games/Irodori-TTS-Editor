"""Launch with the existing engine Python; never modify its environment."""
import os
import argparse
import json
import subprocess
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['stable', 'latest'])
    args = parser.parse_args()
    if args.profile:
        profile_path = root / 'environments' / (args.profile + '.json')
        if not profile_path.is_file():
            raise SystemExit(f'環境が未作成です: {profile_path}。docs/ENVIRONMENTS.md を参照してください。')
        profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
        os.environ.update({key: str(value) for key, value in profile.items()})
    python = Path(os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')) / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        raise SystemExit('IrodoriのPythonがありません。IRODORI_HOMEを設定してください。')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    port = int(env.get('EDITOR_PORT', '8765'))
    if not 1024 <= port <= 65535:
        raise SystemExit('EDITOR_PORT は1024〜65535で指定してください。')
    print(f"Irodori: {python.parent.parent.parent}\nData: {env.get('EDITOR_DATA', root)}\nhttp://127.0.0.1:{port}", flush=True)
    code_root = Path(env.get('EDITOR_CODE') or root)
    raise SystemExit(subprocess.call([str(python), '-B', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=code_root, env=env))
