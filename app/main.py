import copy
import hashlib
import csv
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app import working_sessions
from app.shared_library import read_library, PREFIX as SHARED_PREFIX
from app.project_management import store_voice, migrate_references, move_project
from app.tts import IrodoriEngine
from app.audio_output import output_audio
from app.post_processing import process_audio
from app.preprocessing import apply_dictionary, normalize_for_tts
from app.subtitle_formatter import format_subtitle
from app.project_files import write_project_file, read_project_file

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('EDITOR_DATA', ROOT))
SHARED_DATA = Path(os.environ['EDITOR_SHARED_DATA']).resolve() if os.environ.get('EDITOR_SHARED_DATA') else None
if SHARED_DATA and SHARED_DATA == DATA.resolve():
    raise RuntimeError('共有元と試用版のデータ保存先は分けてください')
for folder in ('projects', 'voices', 'dictionaries', 'outputs'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    return json.loads(path.read_text('utf-8')) if path.exists() else default


def protect_shared_destination(path):
    target = Path(path).resolve()
    local = DATA.resolve()
    if SHARED_DATA and (target == SHARED_DATA or SHARED_DATA in target.parents) and not (
        target == local or local in target.parents
    ):
        raise HTTPException(403, '通常版の共有元には保存できません。試用版の保存先を指定してください。')


def atomic_json(path, data, mark_dirty=True):
    protect_shared_destination(path)
    if SHARED_DATA and path == DATA / 'settings.json':
        data = {**data, 'masters': [m for m in data.get('masters', []) if not m.get('shared')]}
    if mark_dirty and path.name == 'project.json' and working_sessions.ROOT in path.resolve().parents:
        data['dirty'] = True
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    tmp.replace(path)


def decode_script(data):
    for encoding in ('utf-8-sig', 'cp932', 'shift_jis'):
        try:
            return [(i, s.strip()) for i, s in enumerate(data.decode(encoding).splitlines(), 1) if s.strip()]
        except UnicodeDecodeError:
            pass
    raise HTTPException(400, '文字コードを読み取れません。UTF-8 / CP932を使用してください。')


def decode_csv_script(data):
    for encoding in ('utf-8-sig', 'cp932', 'shift_jis'):
        try:
            content = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, '文字コードを読み取れません。UTF-8 / CP932を使用してください。')
    reader = csv.reader(io.StringIO(content, newline=''), strict=True)
    rows = []
    columns = None
    masters = {m['name'].casefold(): m['id'] for m in settings['masters']}
    aliases = {'セリフ': 'text', 'text': 'text', 'マスター': 'master', 'master': 'master', '末尾無音ms': 'pause_ms', 'pause_ms': 'pause_ms'}
    try:
        while True:
            source = reader.line_num + 1
            fields = next(reader, None)
            if fields is None:
                break
            if not fields or all(not f.strip() for f in fields):
                continue
            if columns is None:
                columns = [aliases.get(f.strip().casefold()) for f in fields]
                if all(column is None for column in columns) and 1 <= len(fields) <= 3:
                    # Headerless scripts use the fixed order: text, master, pause_ms.
                    columns = ['text', 'master', 'pause_ms'][:len(fields)]
                elif None in columns or columns.count('text') != 1 or columns.count('master') > 1 or columns.count('pause_ms') > 1:
                    raise HTTPException(400, 'CSVの先頭行は「セリフ,マスター」または「セリフ」にしてください（任意列: 末尾無音ms / 英語列: text,master,pause_ms）')
                else:
                    continue
            if len(fields) > len(columns):
                raise HTTPException(400, f'CSV {source}行目: 列が多すぎます。セリフ中のカンマはダブルクォートで囲んでください')
            values = dict(zip(columns, fields + [''] * (len(columns) - len(fields))))
            text = values['text'].strip()
            name = values.get('master', '').strip()
            if name == '共通マスター':
                name = ''
            if not text:
                continue
            if len(text) > 10000:
                raise HTTPException(400, f'CSV {source}行目: セリフは10000文字以内にしてください')
            if name and name.casefold() not in masters:
                raise HTTPException(400, f'CSV {source}行目: マスター「{name}」は未登録です。設定タブの登録名を指定してください')
            pause = values.get('pause_ms', '').strip()
            if pause and (not re.fullmatch(r'[0-9]+', pause) or len(pause) > 5 or int(pause) > 60000):
                raise HTTPException(400, f'CSV {source}行目: 末尾無音msは0〜60000の整数です')
            rows.append((source, text, masters.get(name.casefold()) if name else None, int(pause) if pause else settings['default_pause_ms']))
    except csv.Error as exc:
        raise HTTPException(400, f'CSV {reader.line_num}行目付近の書式が不正です: {exc}') from exc
    return rows




DEFAULT_POST_PROCESSING = {
    'enabled': False, 'eq_enabled': True, 'eq_preset': 'soften',
    'frequency': 3500.0, 'gain_db': -1.5, 'q': 1.0,
    'peak_enabled': True, 'peak_dbfs': -1.0,
}

lock = threading.RLock()
engine = IrodoriEngine()
settings = read_json(DATA / 'settings.json', {'reference': '', 'duration_scale': 0.85})
settings.setdefault('normalize_numbers', True)
settings.setdefault('wrap_subtitles', True)
settings.setdefault('masters', [])
settings.setdefault('default_pause_ms', 200)
settings.setdefault('post_processing', dict(DEFAULT_POST_PROCESSING))
dictionary = read_json(DATA / 'dictionaries' / 'reading.json', [])
job = {'running': False, 'done': 0, 'total': 0, 'errors': 0, 'current': None, 'project': None}
app = FastAPI(title='Irodori TTS Editor')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


def refresh_shared_library():
    with lock:
        if SHARED_DATA and not job['running']:
            masters, entries = read_library(SHARED_DATA)
            settings['masters'] = [m for m in settings['masters'] if not m.get('shared')] + masters
            dictionary[:] = entries


def require_local_library(mid=None):
    if SHARED_DATA and (mid is None or mid.startswith(SHARED_PREFIX)):
        raise HTTPException(403, '共有辞書・マスターは読み取り専用です。通常版で編集してください。')


@app.middleware('http')
async def shared_library_view(request, call_next):
    try:
        if SHARED_DATA:
            await run_in_threadpool(refresh_shared_library)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': f'通常版の共有データを読み込めません: {exc}'}, status_code=503)
    return await call_next(request)


@app.middleware('http')
async def local_origin(request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': '別のサイトからの操作は許可されません'}, status_code=403)
    return await call_next(request)


def project_path(pid):
    if not re.fullmatch(r'[a-f0-9]{32}', pid):
        raise HTTPException(404, 'プロジェクトがありません')
    try:
        return working_sessions.working_path(DATA, pid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, 'プロジェクトがありません')



def load_project(pid):
    p = read_json(project_path(pid), {})
    changed = False
    for row in p['rows']:
        if row['status'] == 'generated' and (row.get('effective_text') != prepare_text(row['speech_text']) or row.get('reference') != resolve_reference(row)):
            row['status'] = 'stale'
            changed = True
        if (row['status'] == 'generating' and not job['running']) or (
            row['status'] == 'generated' and not (project_path(pid).parent / row['wav']).is_file()
        ):
            row['status'] = 'error'
            row['error'] = '前回の生成が中断されたか、音声が見つかりません。再生成してください。'
            changed = True
    if changed:
        atomic_json(project_path(pid), p)
    return p


def idle():
    if job['running']:
        raise HTTPException(409, '生成中です。完了後に編集してください。')


def prepare_text(text, entries=None):
    return normalize_for_tts(text, dictionary if entries is None else entries,
                             normalize_numeric=settings['normalize_numbers'])


def resolve_reference(row):
    mid = row.get('master_id')
    if not mid:
        return settings['reference']
    return next((m['reference'] for m in settings['masters'] if m['id'] == mid), None)


def invalidate_reference(reference=None):
    for path in working_sessions.ROOT.glob('*/project.json'):
        p = read_json(path, {})
        for row in p['rows']:
            if row['status'] == 'generated' and row.get('reference') != resolve_reference(row):
                row['status'] = 'stale'
        atomic_json(path, p)


class Settings(BaseModel):
    default_pause_ms: int = Field(200, ge=0, le=60000, strict=True)
    wrap_subtitles: bool = True
    normalize_numbers: bool = True
    reference: str
    duration_scale: float = Field(0.85, ge=0.25, le=4)


class PostProcessingSettings(BaseModel):
    """VoiceDesign/captionとは独立した、生成後WAVへの非破壊EQ・Peak補正の設定。"""
    enabled: bool = False
    eq_enabled: bool = True
    eq_preset: str = 'soften'
    frequency: float = Field(3500.0, ge=20, le=20000)
    gain_db: float = Field(-1.5, ge=-12, le=12)
    q: float = Field(1.0, ge=0.1, le=10)
    peak_enabled: bool = True
    peak_dbfs: float = Field(-1.0, ge=-24, le=0)


@app.put('/api/settings/post_processing')
def save_post_processing(value: PostProcessingSettings):
    with lock:
        settings['post_processing'] = value.model_dump()
        atomic_json(DATA / 'settings.json', settings)
        return settings


class Master(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1)


@app.post('/api/masters')
def register_master(value: Master):
    require_local_library()
    with lock:
        idle()
        name = value.name.strip()
        if not name or any(m['name'].casefold() == name.casefold() for m in settings['masters']):
            raise HTTPException(400, 'マスター名が空か、既に登録されています')
        source = Path(value.reference)
        if source.suffix.lower() != '.wav' or not source.is_file():
            raise HTTPException(400, '存在するWAVファイルを指定してください')
        mid = uuid.uuid4().hex
        target = DATA / 'voices' / f'{mid}.wav'
        shutil.copyfile(source, target)
        settings['masters'].append(dict(id=mid, name=name, reference=str(target), original_name=source.name))
        atomic_json(DATA / 'settings.json', settings)
        return settings


@app.post('/api/masters/upload')
def upload_master(file: UploadFile, name: str = Form(...)):
    require_local_library()
    with lock:
        idle()
        if not (file.filename or '').lower().endswith('.wav'):
            raise HTTPException(400, 'WAVファイルを選択してください')
        name = name.strip()
        if not name or len(name) > 100 or any(m['name'].casefold() == name.casefold() for m in settings['masters']):
            raise HTTPException(400, 'マスター名が空・長すぎるか、既に登録されています')
        mid = uuid.uuid4().hex
        target = DATA / 'voices' / f'{mid}.wav'
        with target.open('wb') as output:
            shutil.copyfileobj(file.file, output)
        settings['masters'].append(dict(id=mid, name=name, reference=str(target), original_name=Path(file.filename.replace('\\', '/')).name))
        atomic_json(DATA / 'settings.json', settings)
        return settings


def master_usage(master):
    projects = []
    for path in list((DATA / 'projects').glob('*/project.json')) + list((DATA / 'trash').glob('*/project.json')) + list(working_sessions.ROOT.glob('*/project.json')):
        p = read_json(path, {})
        count = sum(r.get('master_id') == master['id'] for r in p.get('rows', []))
        if count:
            projects.append({'name': p.get('name', path.parent.name), 'count': count})
    return {'projects': projects, 'common': settings.get('reference') == master['reference']}


@app.get('/api/masters')
def list_masters():
    with lock:
        return [{**m, **master_usage(m), 'exists': Path(m['reference']).is_file()} for m in settings['masters']]


class MasterName(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@app.put('/api/masters/{mid}')
def rename_master(mid: str, value: MasterName):
    require_local_library(mid)
    with lock:
        idle()
        master = next((m for m in settings['masters'] if m['id'] == mid), None)
        if not master:
            raise HTTPException(404, 'マスターがありません')
        name = value.name.strip()
        if not name or any(m['id'] != mid and m['name'].casefold() == name.casefold() for m in settings['masters']):
            raise HTTPException(400, 'マスター名が空か、既に登録されています')
        master['name'] = name
        atomic_json(DATA / 'settings.json', settings)
        return settings


@app.delete('/api/masters/{mid}')
def delete_master(mid: str):
    require_local_library(mid)
    with lock:
        idle()
        master = next((m for m in settings['masters'] if m['id'] == mid), None)
        if not master:
            raise HTTPException(404, 'マスターがありません')
        usage = master_usage(master)
        if usage['common'] or usage['projects']:
            raise HTTPException(409, '使用中のマスターです。共通マスター・各プロジェクトの行を別のマスターに変更してから削除してください')
        settings['masters'] = [m for m in settings['masters'] if m['id'] != mid]
        atomic_json(DATA / 'settings.json', settings)
        # Keep the WAV for saved archives and recovery; only remove the registration.
        return settings


class Entry(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    reading: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class RowEdit(BaseModel):
    pause_ms: int = Field(0, ge=0, le=60000, strict=True)
    master_id: str | None = None
    subtitle_text: str = Field(max_length=10000)
    speech_text: str = Field(min_length=1, max_length=10000)
    duration_scale: float = Field(ge=0.25, le=4)
    seed: int | None = Field(None, ge=0, le=4294967295)


class Generate(BaseModel):
    ids: list[int] | None = None
    mode: str = 'missing'
    seed_mode: str = 'configured'
    auto_export: bool = False
    export_folder: str = ''


class Export(BaseModel):
    folder: str = ''
    ids: list[int] | None = None


class ProjectSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    output_folder: str = ''
    copy_project: bool = False
    native_dialog: bool = False


dialog_lock = threading.Lock()



def choose_path(kind, title, initial='', name='project.irodori', *, location_key=None):
    if not dialog_lock.acquire(blocking=False):
        raise HTTPException(409, '開いている保存先ダイアログを先に閉じてください')
    try:
        locations = read_json(DATA / 'dialog_locations.json', {})
        legacy_key = kind + ':' + title
        key = location_key or legacy_key
        remembered = locations.get(key, locations.get(legacy_key, ''))
        if remembered and Path(remembered).is_dir():
            initial = remembered
        # Tk uses Tcl paths; pass an absolute, forward-slash path on Windows too.
        initial = Path(initial).resolve().as_posix() if initial and Path(initial).is_dir() else ROOT.as_posix()
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'app.dialogs'],
                                input=json.dumps(dict(kind=kind, title=title, initialdir=initial, name=name)),
                                capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
        if result.returncode:
            raise HTTPException(400, 'Windowsダイアログを開けません。通常のPowerShellから起動してください。')
        selected = json.loads(result.stdout)['path']
        if selected:
            locations[key] = str(Path(selected) if kind == 'folder' else Path(selected).parent)
            atomic_json(DATA / 'dialog_locations.json', locations)
        return selected
    finally:
        dialog_lock.release()


@app.post('/api/dialog/script')
def choose_script():
    selected = choose_path('script', '台本を選択', location_key='script')
    if not selected:
        return {'cancelled': True}
    with Path(selected).open('rb') as stream:
        return create_project(UploadFile(filename=Path(selected).name, file=stream))


@app.post('/api/dialog/voice')
def choose_voice():
    selected = choose_path('wav', '共通マスターのWAVを選択', location_key='voice')
    if not selected:
        return {'cancelled': True}
    with Path(selected).open('rb') as stream:
        return upload_reference(UploadFile(filename=Path(selected).name, file=stream))


@app.post('/api/dialog/master')
def choose_master():
    return {'path': choose_path('wav', '登録するマスターのWAVを選択', location_key='master')}


@app.post('/api/dialog/output')
def choose_output(value: Export):
    return {'path': choose_path('folder', 'YMM4用の出力先フォルダを選択', value.folder, location_key='output')}


@app.post('/api/projects/open-file')
def open_project_file():
    selected = choose_path('open', 'Irodoriプロジェクトを開く', location_key='project_open')
    if not selected:
        return {'cancelled': True}
    with lock:
        idle()
        pid = uuid.uuid4().hex
        folder = working_sessions.directory(pid)
        try:
            p = read_project_file(selected, folder, lambda row: RowEdit.model_validate(row))
            for master in p.pop('masters', []):
                old_id, old_ref = master['id'], master.pop('original_reference')
                digest = hashlib.sha256(Path(master['reference']).read_bytes()).digest()
                matches = [m for m in settings['masters'] if Path(m['reference']).is_file()
                           and hashlib.sha256(Path(m['reference']).read_bytes()).digest() == digest]
                existing = next((m for m in matches if m['id'] == old_id), None)
                existing = existing or next((m for m in matches if m['name'] == master['name']), None)
                existing = existing or next(iter(matches), None)
                if existing:
                    mid = existing['id']
                    reference = existing['reference']
                else:
                    mid = uuid.uuid4().hex
                    base = master['name']
                    name, n = base, 2
                    while any(m['name'].casefold() == name.casefold() for m in settings['masters']):
                        name = f'{base} ({n})'
                        n += 1
                    reference = store_voice(DATA, master['reference'])
                    settings['masters'].append(dict(id=mid, name=name, reference=reference,
                                                   original_name=master.get('original_name')))
                for row in p['rows']:
                    if row.get('master_id') == old_id:
                        row['master_id'] = mid
                        if row.get('reference') == old_ref:
                            row['reference'] = reference
            atomic_json(DATA / 'settings.json', settings)
            p.update(id=pid, name=Path(selected).stem, project_file=selected, dirty=False, autosave=False)
            atomic_json(folder / 'project.json', p, mark_dirty=False)
        except Exception as exc:
            raise HTTPException(400, f'プロジェクトを開けません：{exc}') from exc
        return {'project': p, 'path': selected}


@app.post('/api/projects/{pid}/save')
def save_project(pid: str, value: ProjectSave):
    selected = None
    if value.native_dialog:
        with lock:
            idle()
            existing = load_project(pid).get('project_file', '')
        selected = choose_path('save', '名前を付けてプロジェクトを保存',
                               str(Path(existing).parent) if existing else '',
                               re.sub(r'[<>:"/\\|?*]', '_', Path(value.name).stem) + '.irodori', location_key='project_save')
        if not selected:
            return {'cancelled': True}
    with lock:
        idle()
        p = load_project(pid)
        if not value.name.strip():
            raise HTTPException(400, 'プロジェクト名を入力してください')
        if value.copy_project:
            old_folder = project_path(pid).parent
            p['id'] = uuid.uuid4().hex
            new_folder = working_sessions.directory(p['id'])
            shutil.copytree(old_folder, new_folder)
        p.update(name=value.name.strip(), output_folder=value.output_folder.strip(),
                 saved_at=datetime.now().isoformat())
        target = selected or (p.get('project_file') if not value.copy_project else None)
        if target:
            target = Path(target).resolve()
            protect_shared_destination(target)
            engine_home = Path(os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')).resolve()
            if engine_home == target or engine_home in target.parents or target.suffix.lower() != '.irodori':
                raise HTTPException(400, 'Irodori本体の外に .irodori ファイルとして保存してください')
            p.update(name=target.stem, project_file=str(target))
            try:
                snapshot = copy.deepcopy(p)
                snapshot['masters'] = []
                used = {}
                for row in snapshot['rows']:
                    ref = resolve_reference(row)
                    if not ref or not Path(ref).is_file():
                        if row.get('master_id'):
                            raise ValueError(f"行{row['id']}のマスター音声が見つかりません")
                        continue
                    mid = row.get('master_id') or 'default'
                    if mid not in used:
                        name = next((m['name'] for m in settings['masters'] if m['id'] == mid), '共通マスター')
                        used[mid] = dict(id=mid, name=name, reference=ref)
                    row['master_id'] = mid
                snapshot['masters'] = list(used.values())
                write_project_file(target, snapshot, project_path(p['id']).parent)
            except (OSError, ValueError) as exc:
                raise HTTPException(400, f'保存できません：{exc}') from exc
        if not target:
            raise HTTPException(400, '名前を付けて .irodori ファイルに保存してください')
        p.update(dirty=False)
        catalog = next((q.parent.name for q in (DATA / 'projects').glob('*/project.json')
                        if Path(read_json(q, {}).get('project_file', '')).resolve() == Path(target).resolve()),
                       uuid.uuid4().hex if (DATA / 'projects' / p['id']).exists() else p['id'])
        p['catalog_id'] = catalog
        source_folder = project_path(p['id']).parent
        destination = DATA / 'projects' / catalog
        shutil.copytree(source_folder, destination, dirs_exist_ok=True)
        snapshot = copy.deepcopy(p)
        snapshot.update(id=catalog, autosave=False)
        atomic_json(destination / 'project.json', snapshot)
        atomic_json(source_folder / 'project.json', p, mark_dirty=False)
        return {'project': p, 'path': str(target)}


class AutosaveOption(BaseModel):
    enabled: bool


@app.put('/api/projects/{pid}/autosave')
def set_autosave(pid: str, value: AutosaveOption):
    with lock:
        idle()
        p = load_project(pid)
        if value.enabled and not p.get('project_file'):
            raise HTTPException(400, '先にプロジェクトを保存してください')
        p['autosave'] = value.enabled
        atomic_json(project_path(pid), p, mark_dirty=False)
        return p


@app.post('/api/projects/{pid}/open-saved')
def open_saved_project(pid: str):
    with lock:
        idle()
        if not re.fullmatch(r'[a-f0-9]{32}', pid):
            raise HTTPException(404, 'プロジェクトがありません')
        source = DATA / 'projects' / pid
        if not (source / 'project.json').is_file():
            raise HTTPException(404, 'プロジェクトがありません')
        new_id = uuid.uuid4().hex
        destination = working_sessions.directory(new_id)
        shutil.copytree(source, destination)
        p = read_json(destination / 'project.json', {})
        p.update(id=new_id, catalog_id=pid, dirty=False, autosave=False)
        atomic_json(destination / 'project.json', p, mark_dirty=False)
        return p


@app.post('/api/projects/{pid}/close')
def close_working_project(pid: str):
    with lock:
        idle()
        working_sessions.discard(pid)
        return {'closed': pid}



@app.on_event('startup')
def migrate_project_voices():
    with lock:
        try:
            migrate_references(DATA, settings, atomic_json)
        except (OSError, ValueError) as exc:
            print(f'マスター移行を完了できませんでした（削除操作時にも再確認します）：{exc}')


@app.get('/api/project-management')
def project_management():
    with lock:
        result = {}
        for area in ('projects', 'trash'):
            items = []
            for path in (DATA / area).glob('*/project.json'):
                p = read_json(path, {})
                items.append({'id': path.parent.name, 'name': p.get('name', path.parent.name),
                              'rows': len(p.get('rows', [])),
                              'updated': datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds'),
                              'project_file': p.get('project_file', '')})
            result[area] = sorted(items, key=lambda p: p['updated'], reverse=True)
        return result


@app.post('/api/projects/{pid}/trash')
def trash_project(pid: str):
    with lock:
        idle()
        try:
            migrate_references(DATA, settings, atomic_json)
            move_project(DATA, pid)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'id': pid}


@app.post('/api/projects/{pid}/restore')
def restore_project(pid: str):
    with lock:
        idle()
        try:
            move_project(DATA, pid, restore=True)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'id': pid}


@app.get('/api/state')
def state():
    with lock:
        projects = [read_json(p, {}) for p in (DATA / 'projects').glob('*/project.json')]
        return {'settings': settings, 'dictionary': dictionary, 'shared_library': bool(SHARED_DATA), 'job': copy.deepcopy(job),
                'projects': [{'id': p['id'], 'name': p['name']} for p in projects]}


@app.put('/api/settings')
def save_settings(value: Settings):
    with lock:
        idle()
        if value.reference and not Path(value.reference).is_file():
            raise HTTPException(400, 'Reference Audioが見つかりません')
        if value.reference != settings.get('reference'):
            settings.pop('reference_original_name', None)
        settings.update(value.model_dump(exclude={'default_pause_ms'} if 'default_pause_ms' not in value.model_fields_set else set()))
        atomic_json(DATA / 'settings.json', settings)
        invalidate_reference(settings['reference'])
        return settings


@app.post('/api/reference')
def upload_reference(file: UploadFile):
    with lock:
        idle()
        if not (file.filename or '').lower().endswith('.wav'):
            raise HTTPException(400, 'WAVファイルを選択してください')
        path = DATA / 'voices' / f'{uuid.uuid4().hex}.wav'
        with path.open('wb') as f:
            shutil.copyfileobj(file.file, f)
        settings['reference'] = str(path)
        settings['reference_original_name'] = Path(file.filename.replace('\\', '/')).name
        atomic_json(DATA / 'settings.json', settings)
        invalidate_reference(settings['reference'])
        return settings


@app.put('/api/dictionary')
def save_dictionary(entries: list[Entry]):
    require_local_library()
    with lock:
        idle()
        if len({e.word for e in entries}) != len(entries):
            raise HTTPException(400, '辞書の表記が重複しています')
        dictionary[:] = [e.model_dump() for e in entries]
        atomic_json(DATA / 'dictionaries' / 'reading.json', dictionary)
        for path in working_sessions.ROOT.glob('*/project.json'):
            p = read_json(path, {})
            for row in p['rows']:
                if row['status'] == 'generated' and row.get('effective_text') != prepare_text(row['speech_text']):
                    row['status'] = 'stale'
            atomic_json(path, p)
        return dictionary


@app.post('/api/projects')
def create_project(file: UploadFile):
    with lock:
        idle()
        data = file.file.read()
        lines = decode_csv_script(data) if (file.filename or '').lower().endswith('.csv') else [(source, text, None, settings['default_pause_ms']) for source, text in decode_script(data)]
        if not lines:
            raise HTTPException(400, '台本にセリフがありません')
        pid = uuid.uuid4().hex
        folder = working_sessions.directory(pid)
        (folder / 'audio').mkdir(parents=True)
        p = {'id': pid, 'name': file.filename, 'created': datetime.now().isoformat(), 'rows': []}
        for n, (source, text, master_id, pause_ms) in enumerate(lines, 1):
            p['rows'].append(dict(id=n, pause_ms=pause_ms, master_id=master_id, source_line=source, original_text=text, subtitle_text=text,
                                  speech_text=text, duration_scale=settings['duration_scale'], seed=None,
                                  used_seed=None, status='pending', wav=None, error='', style=None))
        atomic_json(folder / 'project.json', p)
        return p


@app.post('/api/projects/new')
def new_project():
    with lock:
        idle()
        pid = uuid.uuid4().hex
        folder = working_sessions.directory(pid)
        (folder / 'audio').mkdir(parents=True)
        p = dict(id=pid, name='新規プロジェクト', created=datetime.now().isoformat(), rows=[])
        atomic_json(folder / 'project.json', p)
        return p


class AddRows(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    before_id: int | None = None


@app.post('/api/projects/{pid}/rows')
def add_row(pid: str, value: AddRows):
    with lock:
        idle()
        lines = [line.strip() for line in value.text.splitlines() if line.strip()]
        if not lines:
            raise HTTPException(400, '追加するセリフを入力してください')
        p = load_project(pid)
        rows = p['rows']
        if value.before_id is not None and not any(r['id'] == value.before_id for r in rows):
            raise HTTPException(400, '挿入先の行がありません')
        new_rows = [dict(id=0, pause_ms=settings['default_pause_ms'], source_line=None, original_text=text,
                          subtitle_text=text, speech_text=text,
                          duration_scale=settings['duration_scale'], seed=None,
                          used_seed=None, status='pending', wav=None, error='', style=None)
                    for text in lines]
        start_index = len(rows) if value.before_id is None else next(
            i for i, r in enumerate(rows) if r['id'] == value.before_id)
        p['rows'] = rows[:start_index] + new_rows + rows[start_index:]
        for i, row in enumerate(p['rows'], 1):
            row['id'] = i
        atomic_json(project_path(pid), p)
        return {'ids': list(range(start_index + 1, start_index + 1 + len(new_rows)))}


@app.get('/api/projects/{pid}')
def get_project(pid: str):
    with lock:
        p = load_project(pid)
        for row in p['rows']:
            row['preview'] = prepare_text(row['speech_text'])
        return p


@app.put('/api/projects/{pid}/rows/{rid}')
def edit_row(pid: str, rid: int, value: RowEdit):
    with lock:
        idle()
        p = load_project(pid)
        row = next((r for r in p['rows'] if r['id'] == rid), None)
        if row is None:
            raise HTTPException(404, '行がありません')
        if any(row[k] != getattr(value, k) for k in ('speech_text', 'duration_scale', 'seed')):
            row['status'] = 'stale' if row['wav'] else 'pending'
        if 'master_id' in value.model_fields_set:
            if value.master_id and not any(m['id'] == value.master_id for m in settings['masters']):
                raise HTTPException(400, '指定されたマスターは未登録です')
            if row.get('master_id') != value.master_id:
                row['status'] = 'stale' if row['wav'] else 'pending'
        row.update(value.model_dump(exclude_unset=True))
        atomic_json(project_path(pid), p)
        row['preview'] = prepare_text(row['speech_text'])
        return row


@app.delete('/api/projects/{pid}/rows/{rid}')
def delete_row(pid: str, rid: int):
    with lock:
        idle()
        p = load_project(pid)
        if not any(r['id'] == rid for r in p['rows']):
            raise HTTPException(404, '行がありません')
        p['rows'] = [r for r in p['rows'] if r['id'] != rid]
        for n, row in enumerate(p['rows'], 1):
            row['id'] = n
        # Keep existing audio paths: renumbering must never overwrite another row's WAV.
        atomic_json(project_path(pid), p)
        return {'deleted': rid}


class MoveRows(BaseModel):
    ids: list[int] = Field(min_length=1)
    before_id: int | None = None


@app.post('/api/projects/{pid}/move-rows')
def move_rows(pid: str, value: MoveRows):
    with lock:
        idle()
        p = load_project(pid)
        rows = p['rows']
        ids = set(value.ids)
        positions = [i for i, row in enumerate(rows) if row['id'] in ids]
        if len(ids) != len(value.ids) or len(positions) != len(ids):
            raise HTTPException(400, '移動する行が不正です')
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise HTTPException(400, 'まとめて移動する行は連続して選択してください')
        if value.before_id is not None and not any(r['id'] == value.before_id for r in rows):
            raise HTTPException(400, '移動先の行がありません')
        if value.before_id not in ids:
            moving = [r for r in rows if r['id'] in ids]
            remaining = [r for r in rows if r['id'] not in ids]
            index = next((i for i, r in enumerate(remaining) if r['id'] == value.before_id), len(remaining))
            rows = remaining[:index] + moving + remaining[index:]
        selected = [i for i, row in enumerate(rows, 1) if row['id'] in ids]
        for i, row in enumerate(rows, 1):
            row['id'] = i
            row['preview'] = prepare_text(row['speech_text'])
        p['rows'] = rows
        # Move the complete row; WAV paths and generation metadata stay unchanged.
        atomic_json(project_path(pid), p)
        return {'project': p, 'selected': selected}


def run_job(pid, ids, seed_mode, reference, entries, normalize_numeric=True, export_folder=None):
    last_export_at = None
    try:
        for rid in ids:
            with lock:
                if job.get('stop_requested'):
                    break
                p = load_project(pid)
                row = p['rows'][rid - 1]
                row.update(status='generating', error='')
                job['current'] = rid
                atomic_json(project_path(pid), p)
                snapshot = copy.deepcopy(row)
            actual_text = normalize_for_tts(snapshot['speech_text'], entries, normalize_numeric=normalize_numeric)
            seed = snapshot['seed']
            if seed_mode == 'previous':
                seed = snapshot['used_seed']
            elif seed_mode == 'random':
                seed = None
            if seed is None:
                seed = secrets.randbelow(4294967296)
            relative = snapshot.get('wav') or f'audio/{rid:0{max(3, len(str(len(p["rows"]))))}d}.wav'
            if not snapshot.get('wav') and (project_path(pid).parent / relative).exists():
                relative = f'audio/{rid:03d}_{uuid.uuid4().hex}.wav'
            target = project_path(pid).parent / relative
            tmp = target.with_name(target.stem + '.partial.wav')
            try:
                row_reference = reference[rid] if isinstance(reference, dict) else reference
                used_seed = engine.generate(actual_text, row_reference, snapshot['duration_scale'], seed, tmp)
                tmp.replace(target)
                result = dict(status='generated', wav=relative, used_seed=used_seed, error='',
                              effective_text=actual_text, reference=row_reference, generated_at=datetime.now().isoformat())
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                result = dict(status='error', error=repr(exc), attempted_seed=seed)
                with lock:
                    job['errors'] += 1
            with lock:
                p = load_project(pid)
                p['rows'][rid - 1].update(result)
                atomic_json(project_path(pid), p)
                with (project_path(pid).parent / 'generation.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps({**snapshot, **result, 'effective_text': actual_text, 'attempted_seed': seed}, ensure_ascii=False) + '\n')
                job['done'] += 1
                job.setdefault('completed_ids', []).append(rid)
            if export_folder is not None and result['status'] == 'generated':
                # Same 1 s spacing between published files as a manual multi-row export.
                if last_export_at is not None:
                    time.sleep(max(0.0, 1.0 - (time.monotonic() - last_export_at)))
                try:
                    with lock:
                        p = load_project(pid)
                        if p['rows'][rid - 1]['status'] == 'generated':
                            write_export_files(pid, p, [p['rows'][rid - 1]], export_folder)
                            p.update(output_folder=str(export_folder), last_export=str(export_folder))
                            atomic_json(project_path(pid), p)
                            job['exported'] += 1
                except Exception as exc:
                    with lock:
                        job['export_errors'] += 1
                        job['export_error'] = exc.detail if isinstance(exc, HTTPException) else repr(exc)
                last_export_at = time.monotonic()
    except Exception as exc:
        with lock:
            job['fatal_error'] = repr(exc)
    finally:
        with lock:
            job['running'] = False
            job['current'] = None


@app.post('/api/projects/{pid}/generate')
def generate(pid: str, value: Generate):
    with lock:
        idle()
        p = load_project(pid)
        if value.mode not in ('missing', 'all', 'selected') or value.seed_mode not in ('configured', 'random', 'previous'):
            raise HTTPException(400, '生成モードが不正です')
        ids = [r['id'] for r in p['rows'] if value.mode == 'all' or
               (value.mode == 'missing' and r['status'] != 'generated') or
               (value.mode == 'selected' and r['id'] in (value.ids or []))]
        if not ids:
            raise HTTPException(400, '生成対象がありません')
        references = {r['id']: resolve_reference(r) for r in p['rows'] if r['id'] in ids}
        invalid = [str(rid) for rid, ref in references.items() if not ref or not Path(ref).is_file()]
        if invalid:
            raise HTTPException(400, 'マスター音声が見つかりません。行: ' + ', '.join(invalid))
        export_folder = resolve_export_folder(value.export_folder) if value.auto_export else None
        job.update(running=True, done=0, total=len(ids), errors=0, project=pid, fatal_error=None, stop_requested=False, ids=ids, completed_ids=[],
                   job_id=uuid.uuid4().hex, auto_export=value.auto_export, export_folder=str(export_folder) if export_folder else None,
                   exported=0, export_errors=0, export_error=None)
        threading.Thread(target=run_job, args=(pid, ids, value.seed_mode, references, copy.deepcopy(dictionary), settings['normalize_numbers'], export_folder), daemon=True).start()
        return copy.deepcopy(job)


@app.post('/api/projects/{pid}/stop-generation')
def stop_generation(pid: str):
    with lock:
        if job['running'] and job['project'] == pid:
            job['stop_requested'] = True
        return copy.deepcopy(job)


def resolve_audio_source(pid, row, variant='auto'):
    """Raw WAV, forced Post Processing, or (default) whatever the saved setting implies.

    Used by both the preview endpoint and export(), so "試聴した音" and "最終出力" are
    guaranteed to match whenever variant='auto' is used in both places.
    """
    raw = project_path(pid).parent / row['wav']
    if variant == 'raw':
        return raw
    pp = settings.get('post_processing', DEFAULT_POST_PROCESSING)
    if variant == 'processed' or pp.get('enabled'):
        return process_audio(raw, pp)
    return raw


@app.get('/api/projects/{pid}/audio/{rid}')
def audio(pid: str, rid: int, variant: str = 'auto'):
    with lock:
        if variant not in ('auto', 'raw', 'processed'):
            raise HTTPException(400, '不正なvariantです')
        p = load_project(pid)
        row = next((r for r in p['rows'] if r['id'] == rid), None)
        if not row or not row['wav']:
            raise HTTPException(404, '音声がありません')
        source = resolve_audio_source(pid, row, variant)
        return FileResponse(output_audio(source, row.get('pause_ms', 0)), media_type='audio/wav')


def resolve_export_folder(raw):
    """Validate an output folder the same way for manual export and auto-export."""
    parent = Path(raw).expanduser().resolve() if raw else DATA / 'outputs'
    protect_shared_destination(parent)
    engine_home = Path(os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')).resolve()
    if parent == engine_home or engine_home in parent.parents:
        raise HTTPException(400, 'Irodori-TTS本体のフォルダには出力できません')
    folder = parent
    if folder == DATA.resolve() or any(folder == (DATA / part).resolve() or (DATA / part).resolve() in folder.parents for part in ('projects', 'trash', 'app', 'voices', 'dictionaries')):
        raise HTTPException(400, '作業データの保存場所には出力できません。専用の出力先を指定してください。')
    return folder


def write_export_files(pid, p, rows, folder):
    """Publish a WAV + subtitle pair per row (subtitle first, WAV last). Caller holds `lock`."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        exported_at = datetime.now()
        while True:
            stamp = exported_at.strftime('%Y%m%d_%H%M%S_') + f'{exported_at.microsecond // 10000:02d}'
            stems = [f'{row["id"]:0{max(3, len(str(len(p["rows"]))))}d}_{stamp}_seed{row["used_seed"] if row["used_seed"] is not None else "unknown"}' for row in rows]
            if not any((folder / (stem + ext)).exists() for stem in stems for ext in ('.wav', '.txt')):
                break
            exported_at += timedelta(milliseconds=10)
        for index, (row, stem) in enumerate(zip(rows, stems)):
            if index:
                time.sleep(1.0)
            subtitle = format_subtitle(row['subtitle_text']) if settings['wrap_subtitles'] else row['subtitle_text']
            source = output_audio(resolve_audio_source(pid, row, 'auto'), row.get('pause_ms', 0))
            publish_export_pair(source, folder, stem, subtitle)
    except OSError as exc:
        raise HTTPException(400, f'出力先に書き込めません：{folder}。書き込み権限と空き容量を確認してください。制限付き環境から起動している場合は、通常のPowerShellから start.ps1 で起動してください。途中のファイルがある場合、このフォルダの出力は未完了です。詳細：{exc}') from exc
    return stems


@app.post('/api/projects/{pid}/export')
def export(pid: str, value: Export):
    with lock:
        idle()
        p = load_project(pid)
        rows = p['rows']
        if not rows:
            raise HTTPException(400, '出力するセリフがありません')
        if value.ids is not None:
            if not value.ids or set(value.ids) - {r['id'] for r in rows}:
                raise HTTPException(400, '出力する行を正しく選択してください')
            rows = [r for r in rows if r['id'] in set(value.ids)]
        if any(r['status'] != 'generated' for r in rows):
            raise HTTPException(400, '出力対象の未生成・変更あり・エラー行を生成してから出力してください')
        folder = resolve_export_folder(value.folder)
        stems = write_export_files(pid, p, rows, folder)
        p.update(output_folder=str(folder), last_export=str(folder))
        atomic_json(project_path(pid), p)
        return {'folder': str(folder), 'count': len(rows), 'files': [stem + '.wav' for stem in stems]}


def publish_export_pair(source, folder, stem, subtitle):
    """Expose the finished WAV only after its subtitle exists (Windows rename is exclusive)."""
    temporary = folder / ('.' + uuid.uuid4().hex + '.tmp')
    try:
        with source.open('rb') as audio, temporary.open('xb') as target:
            shutil.copyfileobj(audio, target)
        with (folder / (stem + '.txt')).open('x', encoding='utf-8-sig') as target:
            target.write(subtitle)
        destination = folder / (stem + '.wav')
        if destination.exists():
            raise FileExistsError(str(destination))
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)


app.mount('/', StaticFiles(directory=ROOT / 'app' / 'static', html=True), name='static')
