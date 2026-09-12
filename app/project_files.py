"""Portable project archives, without trusting archive paths on import."""
import copy
import json
import os
import uuid
import zipfile
from pathlib import Path


def write_project_file(path, project, project_folder):
    path = Path(path)
    snapshot = copy.deepcopy(project)
    snapshot.pop('project_file', None)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for n, master in enumerate(snapshot.get('masters', [])):
                member = f'masters/{n}.wav'
                archive.write(master['reference'], member)
                master['archive_path'] = member
            for row in snapshot['rows']:
                if row.get('wav'):
                    source = (project_folder / row['wav']).resolve()
                    if project_folder.resolve() not in source.parents:
                        raise ValueError('音声パスが不正です')
                    row['wav'] = f'audio/{row["id"]:03d}.wav'
                    archive.write(source, row['wav'])
            archive.writestr('project.json', json.dumps(snapshot, ensure_ascii=False))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_project_file(path, destination, validate_row):
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 20 * 1024**3:
            raise ValueError('プロジェクトが大きすぎます（20GB上限）')
        if archive.getinfo('project.json').file_size > 50 * 1024**2:
            raise ValueError('プロジェクト情報が大きすぎます')
        p = json.loads(archive.read('project.json'))
        if not isinstance(p.get('rows'), list):
            raise ValueError('セリフ情報が不正です')
        for n, row in enumerate(p['rows'], 1):
            validate_row(row)
            if row['id'] != n or row['status'] not in ('pending', 'generated', 'stale', 'error', 'generating'):
                raise ValueError('行情報が不正です')
        masters = p.get('masters', [])
        if not isinstance(masters, list) or any(not isinstance(m, dict) or not all(isinstance(m.get(k), str) and m[k] for k in ('id', 'name', 'reference', 'archive_path')) for m in masters):
            raise ValueError('マスター情報が不正です')
        if len({m['id'] for m in masters}) != len(masters):
            raise ValueError('マスターIDが重複しています')
        (destination / 'audio').mkdir(parents=True)
        for n, master in enumerate(masters):
            target = destination / 'masters' / f'{n}.wav'
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(archive.read(master.pop('archive_path')))
            master['original_reference'] = master['reference']
            master['reference'] = str(target)

        for row in p['rows']:
            if row.get('wav'):
                # Read by archive name; never extract to archive-provided paths.
                data = archive.read(row['wav'])
                row['wav'] = f'audio/{row["id"]:03d}.wav'
                (destination / row['wav']).write_bytes(data)
        return p
