"""Disposable working copies. Only explicit Save writes to the project library."""
import json
import shutil
import tempfile
from pathlib import Path

_workspace = tempfile.TemporaryDirectory(prefix='irodori-session-')
ROOT = Path(_workspace.name).resolve()


def directory(pid):
    if len(pid) != 32 or any(c not in '0123456789abcdef' for c in pid):
        raise ValueError('プロジェクトIDが不正です')
    return ROOT / pid


def working_path(data, pid):
    folder = directory(pid)
    path = folder / 'project.json'
    if not path.exists():
        source = data / 'projects' / pid
        if not (source / 'project.json').exists():
            raise FileNotFoundError(pid)
        shutil.copytree(source, folder)
        p = json.loads(path.read_text('utf-8'))
        p.update(dirty=False, catalog_id=pid, autosave=False)
        path.write_text(json.dumps(p, ensure_ascii=False), encoding='utf-8')
    return path


def discard(pid):
    folder = directory(pid)
    if folder.resolve().parent != ROOT or folder.is_symlink():
        raise ValueError('作業領域が不正です')
    if folder.exists():
        shutil.rmtree(folder)
