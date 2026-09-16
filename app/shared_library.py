"""Read-only view of another editor's dictionary and master registry."""
import json
from pathlib import Path


PREFIX = 'shared:'


def read_library(root):
    root = Path(root).resolve()
    settings = json.loads((root / 'settings.json').read_text(encoding='utf-8-sig'))
    if not isinstance(settings, dict) or not isinstance(settings.get('masters', []), list):
        raise ValueError('共有マスターの形式が不正です')
    path = root / 'dictionaries/reading.json'
    dictionary = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else []
    masters = []
    for master in settings.get('masters', []):
        if not isinstance(master, dict) or any(not isinstance(master.get(k), str) for k in ('id', 'name', 'reference')):
            raise ValueError('共有マスターの形式が不正です')
        reference = Path(master['reference'])
        if not reference.is_absolute():
            reference = root / reference
        masters.append({**master, 'id': PREFIX + master['id'],
                        'reference': str(reference.resolve()), 'shared': True})
    if not isinstance(dictionary, list) or any(
        not isinstance(e, dict) or not isinstance(e.get('word'), str)
        or not isinstance(e.get('reading'), str) or not isinstance(e.get('enabled', True), bool)
        for e in dictionary
    ):
        raise ValueError('共有辞書の形式が不正です')
    return masters, dictionary
