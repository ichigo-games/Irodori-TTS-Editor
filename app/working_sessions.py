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


def copy_snapshot(source, destination, project):
    """Copy referenced raw audio only, preserving timestamps for subsequent saves."""
    source, destination = Path(source).resolve(), Path(destination)
    (destination / 'audio').mkdir(parents=True, exist_ok=True)
    for name in {row['wav'] for row in project['rows'] if row.get('wav')}:
        audio = (source / name).resolve()
        if source not in audio.parents:
            raise ValueError('音声パスが不正です')
        target = destination / audio.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        current = audio.stat()
        if target.is_file():
            previous = target.stat()
            if (current.st_size, current.st_mtime_ns) == (previous.st_size, previous.st_mtime_ns):
                continue
        shutil.copy2(audio, target)
