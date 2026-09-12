import copy
import csv
import io
import json
import os
import re
import secrets
import shutil
import threading
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

from app.tts import IrodoriEngine
from app.audio_output import output_audio
from app.preprocessing import apply_dictionary, normalize_for_tts
from app.subtitle_formatter import format_subtitle
from app.project_files import write_project_file, read_project_file

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('EDITOR_DATA', ROOT))
for folder in ('projects', 'voices', 'dictionaries', 'outputs'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    return json.loads(path.read_text('utf-8')) if path.exists() else default


def atomic_json(path, data):
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
                if None in columns or columns.count('text') != 1 or columns.count('master') > 1 or columns.count('pause_ms') > 1:
                    raise HTTPException(400, 'CSVの先頭行は「セリフ,マスター」または「セリフ」にしてください（任意列: 末尾無音ms / 英語列: text,master,pause_ms）')
                continue
            if len(fields) > len(columns):
                raise HTTPException(400, f'CSV {source}行目: 列が多すぎます。セリフ中のカンマはダブルクォートで囲んでください')
            values = dict(zip(columns, fields + [''] * (len(columns) - len(fields))))
            text = values['text'].strip()
            name = values.get('master', '').strip()
            if name == '共通マスター':
                name = ''
            if not text:
                raise HTTPException(400, f'CSV {source}行目: セリフが空です')
            if len(text) > 10000:
                raise HTTPException(400, f'CSV {source}行目: セリフは10000文字以内にしてください')
            if name and name.casefold() not in masters:
                raise HTTPException(400, f'CSV {source}行目: マスター「{name}」は未登録です。設定タブの登録名を指定してください')
            pause = values.get('pause_ms', '').strip()
            if pause and (not re.fullmatch(r'[0-9]+', pause) or len(pause) > 5 or int(pause) > 60000):
                raise HTTPException(400, f'CSV {source}行目: 末尾無音msは0〜60000の整数です')
            rows.append((source, text, masters.get(name.casefold()) if name else None, int(pause) if pause else 0))
    except csv.Error as exc:
        raise HTTPException(400, f'CSV {reader.line_num}行目付近の書式が不正です: {exc}') from exc
    return rows




lock = threading.RLock()
engine = IrodoriEngine()
settings = read_json(DATA / 'settings.json', {'reference': '', 'duration_scale': 0.85})
settings.setdefault('normalize_numbers', True)
settings.setdefault('wrap_subtitles', True)
settings.setdefault('masters', [])
dictionary = read_json(DATA / 'dictionaries' / 'reading.json', [])
job = {'running': False, 'done': 0, 'total': 0, 'errors': 0, 'current': None, 'project': None}
app = FastAPI(title='Irodori TTS Editor')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


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
    path = DATA / 'projects' / pid / 'project.json'
    if not path.exists():
        raise HTTPException(404, 'プロジェクトがありません')
    return path


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
    for path in (DATA / 'projects').glob('*/project.json'):
        p = read_json(path, {})
        for row in p['rows']:
            if row['status'] == 'generated' and row.get('reference') != resolve_reference(row):
                row['status'] = 'stale'
        atomic_json(path, p)


class Settings(BaseModel):
    wrap_subtitles: bool = True
    normalize_numbers: bool = True
    reference: str
    duration_scale: float = Field(0.85, ge=0.25, le=4)


class Master(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1)


@app.post('/api/masters')
def register_master(value: Master):
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
        settings['masters'].append(dict(id=mid, name=name, reference=str(target)))
        atomic_json(DATA / 'settings.json', settings)
        return settings


@app.post('/api/masters/upload')
def upload_master(file: UploadFile, name: str = Form(...)):
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
        settings['masters'].append(dict(id=mid, name=name, reference=str(target)))
        atomic_json(DATA / 'settings.json', settings)
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


class Export(BaseModel):
    folder: str = ''
    ids: list[int] | None = None


class ProjectSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    output_folder: str = ''
    copy_project: bool = False
    native_dialog: bool = False


dialog_lock = threading.Lock()


def choose_path(kind, title, initial='', name='project.irodori'):
    if not dialog_lock.acquire(blocking=False):
        raise HTTPException(409, '開いている保存先ダイアログを先に閉じてください')
    try:
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'app.dialogs'],
                                input=json.dumps(dict(kind=kind, title=title, initialdir=initial, name=name)),
                                capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
        if result.returncode:
            raise HTTPException(400, 'Windowsダイアログを開けません。通常のPowerShellから起動してください。')
        return json.loads(result.stdout)['path']
    finally:
        dialog_lock.release()


@app.post('/api/dialog/output')
def choose_output(value: Export):
    return {'path': choose_path('folder', 'YMM4用の出力先フォルダを選択', value.folder)}


@app.post('/api/projects/open-file')
def open_project_file():
    selected = choose_path('open', 'Irodoriプロジェクトを開く')
    if not selected:
        return {'cancelled': True}
    with lock:
        idle()
        pid = uuid.uuid4().hex
        folder = DATA / 'projects' / pid
        try:
            p = read_project_file(selected, folder, lambda row: RowEdit.model_validate(row))
            for master in p.pop('masters', []):
                old_id, old_ref = master['id'], master.pop('original_reference')
                mid = uuid.uuid4().hex
                base = master['name']
                name, n = base, 2
                while any(m['name'].casefold() == name.casefold() for m in settings['masters']):
                    name = f'{base} ({n})'
                    n += 1
                settings['masters'].append(dict(id=mid, name=name, reference=master['reference']))
                for row in p['rows']:
                    if row.get('master_id') == old_id:
                        row['master_id'] = mid
                        if row.get('reference') == old_ref:
                            row['reference'] = master['reference']
            atomic_json(DATA / 'settings.json', settings)
            p.update(id=pid, name=Path(selected).stem, project_file=selected)
            atomic_json(folder / 'project.json', p)
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
                               re.sub(r'[<>:"/\\|?*]', '_', Path(value.name).stem) + '.irodori')
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
            new_folder = DATA / 'projects' / p['id']
            shutil.copytree(old_folder, new_folder)
        p.update(name=value.name.strip(), output_folder=value.output_folder.strip(),
                 saved_at=datetime.now().isoformat())
        target = selected or (p.get('project_file') if not value.copy_project else None)
        if target:
            target = Path(target).resolve()
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
                write_project_file(target, snapshot, DATA / 'projects' / p['id'])
            except (OSError, ValueError) as exc:
                raise HTTPException(400, f'保存できません：{exc}') from exc
        path = DATA / 'projects' / p['id'] / 'project.json'
        atomic_json(path, p)
        return {'project': p, 'path': str(target or path)}


@app.get('/api/state')
def state():
    with lock:
        projects = [read_json(p, {}) for p in (DATA / 'projects').glob('*/project.json')]
        return {'settings': settings, 'dictionary': dictionary, 'job': copy.deepcopy(job),
                'projects': [{'id': p['id'], 'name': p['name']} for p in projects]}


@app.put('/api/settings')
def save_settings(value: Settings):
    with lock:
        idle()
        if value.reference and not Path(value.reference).is_file():
            raise HTTPException(400, 'Reference Audioが見つかりません')
        settings.update(value.model_dump())
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
        atomic_json(DATA / 'settings.json', settings)
        invalidate_reference(settings['reference'])
        return settings


@app.put('/api/dictionary')
def save_dictionary(entries: list[Entry]):
    with lock:
        idle()
        if len({e.word for e in entries}) != len(entries):
            raise HTTPException(400, '辞書の表記が重複しています')
        dictionary[:] = [e.model_dump() for e in entries]
        atomic_json(DATA / 'dictionaries' / 'reading.json', dictionary)
        for path in (DATA / 'projects').glob('*/project.json'):
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
        lines = decode_csv_script(data) if (file.filename or '').lower().endswith('.csv') else [(source, text, None, 200) for source, text in decode_script(data)]
        if not lines:
            raise HTTPException(400, '台本にセリフがありません')
        pid = uuid.uuid4().hex
        folder = DATA / 'projects' / pid
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
        folder = DATA / 'projects' / pid
        (folder / 'audio').mkdir(parents=True)
        p = dict(id=pid, name='新規プロジェクト', created=datetime.now().isoformat(), rows=[])
        atomic_json(folder / 'project.json', p)
        return p


class AddRow(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@app.post('/api/projects/{pid}/rows')
def add_row(pid: str, value: AddRow):
    with lock:
        idle()
        text = value.text.strip()
        if not text:
            raise HTTPException(400, '追加するセリフを入力してください')
        p = load_project(pid)
        n = len(p['rows']) + 1
        p['rows'].append(dict(id=n, pause_ms=0, source_line=None, original_text=text,
                             subtitle_text=text, speech_text=text,
                             duration_scale=settings['duration_scale'], seed=None,
                             used_seed=None, status='pending', wav=None, error='', style=None))
        atomic_json(project_path(pid), p)
        return {'id': n}


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


def run_job(pid, ids, seed_mode, reference, entries, normalize_numeric=True):
    try:
        for rid in ids:
            with lock:
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
        job.update(running=True, done=0, total=len(ids), errors=0, project=pid, fatal_error=None)
        threading.Thread(target=run_job, args=(pid, ids, value.seed_mode, references, copy.deepcopy(dictionary), settings['normalize_numbers']), daemon=True).start()
        return copy.deepcopy(job)


@app.get('/api/projects/{pid}/audio/{rid}')
def audio(pid: str, rid: int):
    with lock:
        p = load_project(pid)
        row = next((r for r in p['rows'] if r['id'] == rid), None)
        if not row or not row['wav']:
            raise HTTPException(404, '音声がありません')
        return FileResponse(output_audio(project_path(pid).parent / row['wav'], row.get('pause_ms', 0)), media_type='audio/wav')


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
        parent = Path(value.folder).expanduser().resolve() if value.folder else DATA / 'outputs'
        engine_home = Path(os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')).resolve()
        if parent == engine_home or engine_home in parent.parents:
            raise HTTPException(400, 'Irodori-TTS本体のフォルダには出力できません')
        folder = parent
        if folder == DATA.resolve() or any(folder == (DATA / part).resolve() or (DATA / part).resolve() in folder.parents for part in ('projects', 'app', 'voices', 'dictionaries')):
            raise HTTPException(400, '作業データの保存場所には出力できません。専用の出力先を指定してください。')
        try:
            folder.mkdir(parents=True, exist_ok=True)
            exported_at = datetime.now()
            while True:
                stamp = exported_at.strftime('%Y%m%d_%H%M%S_') + f'{exported_at.microsecond // 10000:02d}'
                stems = [f'{row["id"]:0{max(3, len(str(len(p["rows"]))))}d}_{stamp}_seed{row["used_seed"] if row["used_seed"] is not None else "unknown"}' for row in rows]
                if not any((folder / (stem + ext)).exists() for stem in stems for ext in ('.wav', '.txt')):
                    break
                exported_at += timedelta(milliseconds=10)
            for row, stem in zip(rows, stems):
                with output_audio(project_path(pid).parent / row['wav'], row.get('pause_ms', 0)).open('rb') as source, (folder / (stem + '.wav')).open('xb') as target:
                    shutil.copyfileobj(source, target)
                subtitle = format_subtitle(row['subtitle_text']) if settings['wrap_subtitles'] else row['subtitle_text']
                with (folder / (stem + '.txt')).open('x', encoding='utf-8-sig') as target:
                    target.write(subtitle)
        except OSError as exc:
            raise HTTPException(400, f'出力先に書き込めません：{folder}。書き込み権限と空き容量を確認してください。制限付き環境から起動している場合は、通常のPowerShellから start.ps1 で起動してください。途中のファイルがある場合、このフォルダの出力は未完了です。詳細：{exc}') from exc
        p.update(output_folder=str(folder), last_export=str(folder))
        atomic_json(project_path(pid), p)
        return {'folder': str(folder), 'count': len(rows), 'files': [stem + '.wav' for stem in stems]}


app.mount('/', StaticFiles(directory=ROOT / 'app' / 'static', html=True), name='static')
