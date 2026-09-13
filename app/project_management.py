"""Project-independent voice storage and reversible project removal."""
import copy
import hashlib
import json
import shutil
import uuid
from pathlib import Path


def store_voice(data, source):
    source = Path(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    folder = data / 'voices' / 'shared'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest + '.wav')
    if not target.exists():
        temporary = folder / (uuid.uuid4().hex + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return str(target.resolve())


def migrate_references(data, settings, write):
    """Copy first, then rewrite references. Original audio and JSON backups remain."""
    roots = [(data / name).resolve() for name in ('projects', 'trash')]
    mapping = {}
    def relocated(value):
        if not value:
            return value
        source = Path(value).resolve()
        if not any(root in source.parents for root in roots):
            return value
        if str(source) not in mapping:
            if not source.is_file():
                raise ValueError(f'参照音声が見つかりません：{source}')
            mapping[str(source)] = store_voice(data, source)
        return mapping[str(source)]
    updated = copy.deepcopy(settings)
    updated['reference'] = relocated(updated.get('reference', ''))
    for master in updated.get('masters', []):
        master['reference'] = relocated(master['reference'])
    changes = []
    for root in roots:
        for path in root.glob('*/project.json'):
            p = json.loads(path.read_text('utf-8'))
            original = copy.deepcopy(p)
            for row in p.get('rows', []):
                if row.get('reference'):
                    row['reference'] = relocated(row['reference'])
            if p != original:
                changes.append((path, p))
    if updated != settings:
        changes.append((data / 'settings.json', updated))
    for path, content in changes:
        if path.exists():
            backup = path.with_name(path.name + '.before-voice-migration.bak')
            if not backup.exists():
                shutil.copyfile(path, backup)
        write(path, content)
    settings.clear()
    settings.update(updated)


def project_directory(data, area, pid):
    if len(pid) != 32 or any(c not in '0123456789abcdef' for c in pid):
        raise ValueError('プロジェクトIDが不正です')
    root = (data / area).resolve()
    path = root / pid
    if path.resolve() != path or not path.is_dir() or not (path / 'project.json').is_file():
        raise ValueError('プロジェクトが見つからないか、保存場所が不正です')
    return path


def move_project(data, pid, restore=False):
    source = project_directory(data, 'trash' if restore else 'projects', pid)
    root = (data / ('projects' if restore else 'trash')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / pid
    if target.exists() or target.resolve() != target:
        raise ValueError('移動先に同じIDのプロジェクトがあります')
    source.rename(target)
