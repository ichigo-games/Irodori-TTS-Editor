"""Create isolated environments without updating the existing engine."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'environments'
ENGINE = Path(r'E:\Irodori-TTS')


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def stable(cache):
    destination = BASE / 'stable'
    if destination.exists() or (BASE / 'stable.json').exists():
        raise SystemExit('固定版の保存先が既にあります。上書きしません。')
    repo = cache / 'models--Aratako--Irodori-TTS-v4.1-Small'
    revision = (repo / 'refs' / 'main').read_text().strip()
    model = repo / 'snapshots' / revision / 'model.safetensors'
    if not model.is_file():
        raise SystemExit('現在のモデルキャッシュが見つかりません。')
    destination.mkdir(parents=True)
    # Preserve local source modifications and untracked scripts; the running venv stays in place.
    shutil.copytree(ENGINE, destination / 'engine-source',
                    ignore=shutil.ignore_patterns('.venv', '__pycache__', 'gradio_outputs*', 'my_work', 'ichigo_voice'))
    python = ENGINE / '.venv/Scripts/python.exe'
    with (destination / 'pip-freeze.txt').open('w', encoding='utf-8') as output:
        run([str(python), '-B', '-c', 'import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"] + "==" + d.version for d in m.distributions())))'], stdout=output)
    # Dereference HF cache links to make an independent copy, including codec assets.
    shutil.copytree(cache, destination / 'hf' / 'hub', ignore=shutil.ignore_patterns('.locks'))
    checkpoint = destination / 'hf/hub' / repo.name / 'snapshots' / revision / 'model.safetensors'
    write_json(BASE / 'stable.json', {
        'IRODORI_HOME': str(ENGINE), 'EDITOR_DATA': str(ROOT), 'EDITOR_PORT': '8765', 'EDITOR_CODE': str(ROOT), 'EDITOR_SHARED_DATA': '',
        'IRODORI_CHECKPOINT': str(checkpoint), 'IRODORI_HF_CHECKPOINT': '',
        'HF_HOME': str(destination / 'hf'), 'HF_HUB_CACHE': str(destination / 'hf/hub'),
        'HUGGINGFACE_HUB_CACHE': str(destination / 'hf/hub'),
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
    })
    print('固定版を作成しました。既存のTTSコードとPython環境は更新していません。')


def latest():
    destination = BASE / 'latest'
    if (BASE / 'latest.json').exists():
        raise SystemExit('試用版の保存先が既にあります。上書きしません。')
    uv = shutil.which('uv')
    if not uv:
        raise SystemExit('uv が必要です。公式手順に従ってインストールしてください。')
    engine = destination / 'Irodori-TTS'
    destination.mkdir(parents=True, exist_ok=True)
    if not engine.exists():
        run(['git', 'clone', 'https://github.com/Aratako/Irodori-TTS.git', str(engine)])
    else:
        origin = subprocess.check_output(['git', '-C', str(engine), 'remote', 'get-url', 'origin'], text=True).strip()
        if origin != 'https://github.com/Aratako/Irodori-TTS.git':
            raise SystemExit('試用版のoriginが公式リポジトリと一致しません。')
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(engine / '.venv'),
               UV_CACHE_DIR=str(destination / 'uv-cache'))
    env.pop('VIRTUAL_ENV', None)
    run([uv, 'sync', '--extra', 'cu128'], cwd=engine, env=env)
    python = engine / '.venv/Scripts/python.exe'
    # Editor-only additions are installed exclusively into the trial environment.
    run([uv, 'pip', 'install', '--python', str(python), 'fastapi', 'uvicorn',
         'python-multipart'], cwd=engine, env=env)
    run([str(python), '-B', '-c',
         'from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, SamplingRequest, download_hf_checkpoint, save_wav; import fastapi, uvicorn, multipart'], cwd=engine, env=env)
    shutil.copytree(ROOT / 'app', destination / 'editor/app', ignore=shutil.ignore_patterns('__pycache__'))
    write_json(BASE / 'latest.json', {
        'IRODORI_HOME': str(engine), 'EDITOR_DATA': str(destination / 'data'),
        'EDITOR_CODE': str(destination / 'editor'),
        'EDITOR_SHARED_DATA': str(ROOT),
        'EDITOR_PORT': '8766', 'IRODORI_CHECKPOINT': '',
        'IRODORI_HF_CHECKPOINT': 'Aratako/Irodori-TTS-v4.1-Small',
        'HF_HOME': str(destination / 'hf'), 'HF_HUB_CACHE': str(destination / 'hf/hub'),
        'HUGGINGFACE_HUB_CACHE': str(destination / 'hf/hub'),
        'HF_HUB_OFFLINE': '0', 'TRANSFORMERS_OFFLINE': '0',
    })
    print('試用版を作成しました。初回生成時にモデルを取得します。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=['stable', 'latest'])
    parser.add_argument('--cache', type=Path, default=Path(r'C:\Users\kuren\.cache\huggingface\hub'))
    args = parser.parse_args()
    BASE.mkdir(exist_ok=True)
    if args.profile == 'stable':
        stable(args.cache)
    else:
        latest()
