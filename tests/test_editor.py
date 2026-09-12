import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

temp = tempfile.TemporaryDirectory()
os.environ['EDITOR_DATA'] = temp.name
from fastapi.testclient import TestClient
from app import main as m


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.fail = True

    def generate(self, text, reference, scale, seed, path):
        self.calls.append((text, scale, seed))
        if text == '失敗' and self.fail:
            raise RuntimeError('injected failure')
        Path(path).write_bytes(b'RIFF-test')
        return seed


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(m.app)
        m.engine = FakeEngine()
        m.dictionary.clear()
        reference = Path(temp.name) / 'reference.wav'
        reference.write_bytes(b'test')
        self.c.put('/api/settings', json={'reference': str(reference), 'duration_scale': 1})

    def create(self, text='LR5\n失敗\n\n最後'):
        r = self.c.post('/api/projects', files={'file': ('sample.txt', text.encode('cp932'))})
        self.assertEqual(r.status_code, 200)
        return r.json()['id']

    def wait(self):
        deadline = time.monotonic() + 5
        while m.job['running'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(m.job['running'])

    def test_dialog_locations_are_independent_and_persistent(self):
        import json
        from types import SimpleNamespace
        first = Path(temp.name) / 'scripts'
        second = Path(temp.name) / 'voices-source'
        first.mkdir(exist_ok=True)
        second.mkdir(exist_ok=True)
        def result(path):
            return SimpleNamespace(returncode=0, stdout=json.dumps({'path': str(path)}))
        with patch.object(m.subprocess, 'run', return_value=result(first/'a.csv')):
            m.choose_path('script', 'script-test')
        with patch.object(m.subprocess, 'run', return_value=result(second/'a.wav')):
            m.choose_path('wav', 'voice-test')
        for kind, title, expected in [('script','script-test',first),('wav','voice-test',second)]:
            with patch.object(m.subprocess, 'run', return_value=result('')) as run:
                self.assertEqual(m.choose_path(kind,title), '')
                self.assertEqual(json.loads(run.call_args.kwargs['input'])['initialdir'], str(expected))
            stored = m.read_json(m.DATA/'dialog_locations.json', {})
            self.assertEqual(stored[kind+':'+title], str(expected))

    def test_native_script_selection(self):
        source = Path(temp.name)/'native-script.csv'
        source.write_text('セリフ\n台本テスト', encoding='utf-8')
        with patch.object(m, 'choose_path', return_value=str(source)):
            result = self.c.post('/api/dialog/script')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['rows'][0]['speech_text'], '台本テスト')
        with patch.object(m, 'choose_path', return_value=''):
            self.assertTrue(self.c.post('/api/dialog/script').json()['cancelled'])

    def test_reopen_reuses_master_by_content(self):
        import copy
        from app.project_files import write_project_file
        unique = __import__('uuid').uuid4().hex
        response = self.c.post('/api/masters/upload', data={'name': unique}, files={'file': ('voice.wav', unique.encode())})
        master = response.json()['masters'][-1]
        pid = self.create('テスト')
        p = m.load_project(pid)
        p['rows'][0].update(master_id=master['id'], reference=master['reference'])
        p['masters'] = [copy.deepcopy(master)]
        target = Path(temp.name) / (unique+'.irodori')
        write_project_file(target, p, m.project_path(pid).parent)
        count = len(m.settings['masters'])
        with patch.object(m, 'choose_path', return_value=str(target)):
            for _ in range(3):
                response = self.c.post('/api/projects/open-file')
                self.assertEqual(response.status_code, 200, response.text)
                row = response.json()['project']['rows'][0]
                self.assertEqual(row['master_id'], master['id'])
                self.assertEqual(row['reference'], master['reference'])
                self.assertEqual(len(m.settings['masters']), count)
        # Reusing an ID/name must not reuse different audio.
        Path(master['reference']).write_bytes(b'changed voice')
        with patch.object(m, 'choose_path', return_value=str(target)):
            response = self.c.post('/api/projects/open-file')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()['project']['rows'][0]['master_id'], master['id'])
        self.assertEqual(len(m.settings['masters']), count+1)

    def test_headerless_csv(self):
        for content, expected in [('こんにちは,共通マスター,350\n,共通マスター,350\n次の行,,500', [('こんにちは',350),('次の行',500)]),
                                  ('こんにちは\n次の行', [('こんにちは',0),('次の行',0)]),
                                  ('セリフ,マスター,末尾無音ms\nこんにちは,,350', [('こんにちは',350)])]:
            result = self.c.post('/api/projects', files={'file': ('script.csv', content.encode('utf-8'))})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([(r['speech_text'],r['pause_ms']) for r in result.json()['rows']], expected)

    def test_master_management(self):
        response = self.c.post('/api/masters/upload', data={'name': 'manage-test'}, files={'file': ('original.wav', b'test')})
        master = response.json()['masters'][-1]
        mid = master['id']
        self.assertEqual(master['original_name'], 'original.wav')
        self.assertEqual(self.c.put('/api/masters/'+mid, json={'name': 'renamed'}).status_code, 200)
        pid = self.create('テスト')
        p = m.load_project(pid)
        p['rows'][0]['master_id'] = mid
        m.atomic_json(m.project_path(pid), p)
        usage = next(x for x in self.c.get('/api/masters').json() if x['id'] == mid)
        self.assertEqual(usage['projects'][0]['count'], 1)
        self.assertEqual(self.c.delete('/api/masters/'+mid).status_code, 409)
        p['rows'][0]['master_id'] = None
        m.atomic_json(m.project_path(pid), p)
        self.assertEqual(self.c.delete('/api/masters/'+mid).status_code, 200)
        self.assertTrue(Path(master['reference']).exists())
        self.assertFalse(any(x['id'] == mid for x in self.c.get('/api/masters').json()))

    def test_stop_after_current_and_resume(self):
        pid = self.create('最初\n次')
        entered, release = threading.Event(), threading.Event()
        original = m.engine.generate
        def blocking(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test timeout')
            return original(*args)
        m.engine.generate = blocking
        try:
            self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
            self.assertTrue(entered.wait(2))
            response = self.c.post(f'/api/projects/{pid}/stop-generation')
            self.assertTrue(response.json()['stop_requested'])
            self.assertTrue(m.job['running'])
        finally:
            release.set()
            self.wait()
        rows = self.c.get(f'/api/projects/{pid}').json()['rows']
        self.assertEqual([r['status'] for r in rows], ['generated', 'pending'])
        self.assertEqual(m.job['done'], 1)
        m.engine.generate = original
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'missing'})
        self.wait()
        self.assertFalse(m.job['stop_requested'])
        self.assertEqual(len(m.engine.calls), 2)
        self.assertEqual([r['status'] for r in self.c.get(f'/api/projects/{pid}').json()['rows']], ['generated', 'generated'])

    def test_export_sequential_delay_and_finished_pair(self):
        pid = self.create('最初\n次\n最後')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        p = m.load_project(pid)
        for row in p['rows']:
            row['pause_ms'] = 0
        m.atomic_json(m.project_path(pid), p)
        folder = Path(temp.name) / ('paced-' + __import__('uuid').uuid4().hex)
        events = []
        original_rename = Path.rename
        def rename(source, target):
            self.assertEqual(source.suffix, '.tmp')
            self.assertEqual(source.read_bytes(), b'RIFF-test')
            self.assertTrue(target.with_suffix('.txt').exists())
            self.assertFalse(target.exists())
            events.append(target.name[:3])
            return original_rename(source, target)
        with patch.object(m.time, 'sleep', side_effect=lambda delay: events.append(delay)), patch.object(Path, 'rename', rename):
            response = self.c.post(f'/api/projects/{pid}/export', json={'folder': str(folder)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, ['001', 1.0, '002', 1.0, '003'])
        self.assertEqual(len(list(folder.iterdir())), 6)
        self.assertEqual([p.read_text('utf-8-sig') for p in sorted(folder.glob('*.txt'))], ['最初', '次', '最後'])

    def test_move_rows_preserves_data_and_order(self):
        pid = self.create('一行目\n二行目\n三行目\n四行目\n五行目')
        original = self.c.get(f'/api/projects/{pid}').json()
        for row in original['rows']:
            row.update(pause_ms=row['id'] * 100, seed=row['id'], used_seed=row['id'],
                       wav=f"audio/kept-{row['id']}.wav")
        m.atomic_json(m.project_path(pid), original)
        # Snapshot through the loader, which may mark missing audio as an error.
        original = self.c.get(f'/api/projects/{pid}').json()
        def move(ids, before):
            result = self.c.post(f'/api/projects/{pid}/move-rows', json={'ids': ids, 'before_id': before})
            self.assertEqual(result.status_code, 200)
            return result.json()
        result = move([2, 3], None)
        self.assertEqual(result['selected'], [4, 5])
        for current, old_index in zip(result['project']['rows'], [0, 3, 4, 1, 2]):
            expected = dict(original['rows'][old_index], id=current['id'])
            self.assertEqual(current, expected)
        result = move([4, 5], 1)
        self.assertEqual([r['speech_text'] for r in result['project']['rows']],
                         ['二行目', '三行目', '一行目', '四行目', '五行目'])
        unchanged = move([1, 2], 2)['project']['rows']
        self.assertEqual(unchanged, result['project']['rows'])
        self.assertEqual(move([1], 4)['selected'], [3])
        for ids, before in [([1, 3], None), ([1, 1], None), ([99], None), ([1], 99)]:
            self.assertEqual(self.c.post(f'/api/projects/{pid}/move-rows',
                             json={'ids': ids, 'before_id': before}).status_code, 400)
        m.job['running'] = True
        try:
            self.assertEqual(self.c.post(f'/api/projects/{pid}/move-rows',
                             json={'ids': [1], 'before_id': None}).status_code, 409)
        finally:
            m.job['running'] = False

    def test_masters_mixed_generation_invalidation_and_portable_save(self):
        name = 'master_flat_' + __import__('uuid').uuid4().hex
        response = self.c.post('/api/masters/upload', data={'name': name}, files={'file': ('flat.wav', b'RIFF-flat')})
        self.assertEqual(response.status_code, 200)
        master = response.json()['masters'][-1]
        self.assertEqual(Path(master['reference']).read_bytes(), b'RIFF-flat')
        self.assertEqual(self.c.post('/api/masters', json={'name': name, 'reference': master['reference']}).status_code, 400)
        pid = self.create('通常\n平坦')
        edit = dict(subtitle_text='平坦', speech_text='平坦', duration_scale=1, master_id=master['id'])
        self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/2', json=edit).status_code, 200)
        self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/2', json={**edit, 'master_id': 'unknown'}).status_code, 400)
        refs = []
        original = m.engine.generate
        def capture(text, reference, *args):
            refs.append(reference)
            return original(text, reference, *args)
        m.engine.generate = capture
        default = m.settings['reference']
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        self.assertEqual(refs, [default, master['reference']])
        target = str(Path(temp.name) / 'masters-portable.irodori')
        with patch.object(m, 'choose_path', return_value=target):
            self.assertEqual(self.c.post(f'/api/projects/{pid}/save', json={'name': 'masters', 'native_dialog': True}).status_code, 200)
            result = self.c.post('/api/projects/open-file')
            self.assertEqual(result.status_code, 200)
            restored = result.json()['project']
        restored_rows = self.c.get('/api/projects/' + restored['id']).json()['rows']
        self.assertEqual([r['status'] for r in restored_rows], ['generated', 'generated'])
        self.assertEqual(Path(m.resolve_reference(restored_rows[1])).read_bytes(), b'RIFF-flat')
        self.assertNotEqual(restored_rows[1]['master_id'], master['id'])
        other = Path(temp.name) / 'changed-default.wav'
        other.write_bytes(b'RIFF-other')
        self.c.put('/api/settings', json={'reference': str(other), 'duration_scale': 1})
        rows = self.c.get('/api/projects/' + pid).json()['rows']
        self.assertEqual([r['status'] for r in rows], ['stale', 'generated'])
        # An explicit master works even when the common master is unset.
        self.c.put('/api/settings', json={'reference': '', 'duration_scale': 1})
        self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'selected', 'ids': [2]}).status_code, 200)
        self.wait()
        self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'}).status_code, 400)
        Path(master['reference']).unlink()
        self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'selected', 'ids': [2]}).status_code, 400)
        self.assertEqual(self.c.post('/api/projects/' + restored['id'] + '/generate', json={'mode': 'all'}).status_code, 200)
        self.wait()

    def test_csv_import_master_names_defaults_and_validation(self):
        name = 'csv_flat_' + __import__('uuid').uuid4().hex
        result = self.c.post('/api/masters', json={'name': name, 'reference': m.settings['reference']})
        self.assertEqual(result.status_code, 200)
        mid = result.json()['masters'][-1]['id']
        for encoding in ('utf-8-sig', 'cp932', 'shift_jis'):
            text = f'セリフ,マスター\n通常,\n"カンマ,あり",{name.upper()}\n省略\n"複数\n行",{name}\n'
            response = self.c.post('/api/projects', files={'file': ('script.csv', text.encode(encoding))})
            self.assertEqual(response.status_code, 200, response.text)
            rows = response.json()['rows']
            self.assertEqual([r['master_id'] for r in rows], [None, mid, None, mid])
            self.assertEqual(rows[1]['speech_text'], 'カンマ,あり')
            self.assertEqual(rows[3]['speech_text'], '複数\n行')
            self.assertEqual([r['source_line'] for r in rows], [2, 3, 4, 5])
        pid = response.json()['id']
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        self.assertEqual([r['reference'] for r in m.load_project(pid)['rows']], [m.settings['reference'], m.resolve_reference(rows[1]), m.settings['reference'], m.resolve_reference(rows[3])])
        for text in ('セリフ\n通常', 'text\n通常', 'master,text\n,通常', 'セリフ,マスター\n通常,共通マスター', 'text,master\n通常, 共通マスター '):
            response = self.c.post('/api/projects', files={'file': ('one.csv', text.encode())})
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()['rows'][0]['master_id'])
        before = len(list((m.DATA / 'projects').glob('*/project.json')))
        for text in ('セリフ,マスター\n声,unknown', 'セリフ,マスター\n声,a,b', 'セリフ,マスター\n"閉じていない', 'セリフ,マスター\n,unknown', 'text,text\n声,声', 'text,other\n声,x', 'セリフ,マスター\n'):
            response = self.c.post('/api/projects', files={'file': ('bad.csv', text.encode())})
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(len(list((m.DATA / 'projects').glob('*/project.json'))), before)
        response = self.c.post('/api/projects', files={'file': ('old.txt', b'hello,world')})
        self.assertEqual(response.json()['rows'][0]['speech_text'], 'hello,world')
        self.assertEqual(response.json()['rows'][0]['pause_ms'], 200)

    def test_pause_csv_playback_export_and_archive(self):
        import io
        import wave
        def wav_bytes(frames):
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16000)
                out.writeframes(b'\x01\x00' * frames)
            return buffer.getvalue()
        raw = wav_bytes(1600)
        def generate(text, reference, scale, seed, path):
            Path(path).write_bytes(raw)
            return seed
        m.engine.generate = generate
        response = self.c.post('/api/projects', files={'file': ('pause.csv', 'セリフ,マスター,末尾無音ms\n通常,共通マスター,200\n次,,'.encode())})
        self.assertEqual(response.status_code, 200, response.text)
        pid = response.json()['id']
        self.assertEqual([r['pause_ms'] for r in response.json()['rows']], [200, 0])
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        row = m.load_project(pid)['rows'][0]
        original_path = m.project_path(pid).parent / row['wav']
        def assert_audio(data, pause):
            with wave.open(io.BytesIO(data)) as audio:
                self.assertEqual(audio.getnframes(), 1600 + pause * 16)
                self.assertEqual(audio.readframes(1600), b'\x01\x00' * 1600)
                self.assertEqual(audio.readframes(pause * 16), b'\x00\x00' * pause * 16)
        first = self.c.get(f'/api/projects/{pid}/audio/1').content
        assert_audio(first, 200)
        exported = self.c.post(f'/api/projects/{pid}/export', json={'ids': [1]}).json()
        self.assertEqual((Path(exported['folder']) / exported['files'][0]).read_bytes(), first)
        for pause in (500, 100, 0):
            edited = self.c.put(f'/api/projects/{pid}/rows/1', json={**row, 'pause_ms': pause})
            self.assertEqual(edited.status_code, 200)
            self.assertEqual(edited.json()['status'], 'generated')
            assert_audio(self.c.get(f'/api/projects/{pid}/audio/1').content, pause)
            self.assertEqual(original_path.read_bytes(), raw)
        for value in (-1, 60001, 1.5, True):
            self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/1', json={**row, 'pause_ms': value}).status_code, 422)
        for value in ('-1', '60001', '1.5', 'abc'):
            self.assertEqual(self.c.post('/api/projects', files={'file': ('bad.csv', f'text,pause_ms\nhello,{value}'.encode())}).status_code, 400)
        self.c.put(f'/api/projects/{pid}/rows/1', json={**row, 'pause_ms': 200})
        target = str(Path(temp.name) / 'pause.irodori')
        with patch.object(m, 'choose_path', return_value=target):
            self.c.post(f'/api/projects/{pid}/save', json={'name': 'pause', 'native_dialog': True})
            restored = self.c.post('/api/projects/open-file').json()['project']
        assert_audio(self.c.get('/api/projects/' + restored['id'] + '/audio/1').content, 200)

    def test_decode_and_dictionary(self):
        for encoding in ('utf-8-sig', 'cp932', 'shift_jis'):
            self.assertEqual(m.decode_script('猫\n\n犬'.encode(encoding)), [(1, '猫'), (3, '犬')])
        entries = [dict(word='LR', reading='短', enabled=True), dict(word='LR5', reading='LR', enabled=True)]
        self.assertEqual(m.apply_dictionary('LR5 LR', entries), 'LR 短')

    def test_delete_renumber_generate_and_archive(self):
        pid = self.create('一\n二\n三')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'all'})
        self.wait()
        before = m.load_project(pid)['rows']
        kept_path = m.project_path(pid).parent / before[2]['wav']
        kept_path.write_bytes(b'RIFF-third-row')
        self.assertEqual(self.c.delete(f'/api/projects/{pid}/rows/2').status_code, 200)
        rows = self.c.get(f'/api/projects/{pid}').json()['rows']
        self.assertEqual([(r['id'], r['speech_text']) for r in rows], [(1, '一'), (2, '三')])
        self.assertEqual(self.c.get(f'/api/projects/{pid}/audio/2').content, b'RIFF-third-row')
        self.c.post(f'/api/projects/{pid}/rows', json={'text': '四'})
        self.c.post(f'/api/projects/{pid}/generate', json={'mode': 'missing'})
        self.wait()
        self.assertEqual(kept_path.read_bytes(), b'RIFF-third-row')
        rows = m.load_project(pid)['rows']
        self.assertEqual(len({r['wav'] for r in rows}), 3)
        from app.project_files import write_project_file, read_project_file
        archive = Path(temp.name) / 'deleted.irodori'
        write_project_file(archive, m.load_project(pid), m.project_path(pid).parent)
        reopened = read_project_file(archive, Path(temp.name) / 'reopened-delete', lambda r: None)
        self.assertEqual([r['id'] for r in reopened['rows']], [1, 2, 3])
        m.job['running'] = True
        try:
            self.assertEqual(self.c.delete(f'/api/projects/{pid}/rows/1').status_code, 409)
        finally:
            m.job['running'] = False
        self.assertEqual(self.c.delete(f'/api/projects/{pid}/rows/99').status_code, 404)
        for rid in [3, 2, 1]:
            self.assertEqual(self.c.delete(f'/api/projects/{pid}/rows/{rid}').status_code, 200)
        self.assertEqual(m.load_project(pid)['rows'], [])

    def test_failure_resume_export_and_previous_seed(self):
        pid = self.create()
        self.c.put('/api/dictionary', json=[dict(word='LR5', reading='エルアールご', enabled=True)])
        self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode':'missing'}).status_code, 200)
        self.wait()
        rows = self.c.get(f'/api/projects/{pid}').json()['rows']
        self.assertEqual([r['status'] for r in rows], ['generated','error','generated'])
        self.assertEqual(rows[0]['effective_text'], 'エルアールご')
        self.assertEqual(self.c.post(f'/api/projects/{pid}/export', json={}).status_code, 400)
        m.engine.fail = False
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'missing'})
        self.wait()
        self.assertEqual(len(m.engine.calls), 4)
        result = self.c.post(f'/api/projects/{pid}/export', json={}).json()
        folder = Path(result['folder'])
        self.assertEqual(len(list(folder.iterdir())), 6)
        self.assertEqual({p.stem for p in folder.glob('*.wav')}, {p.stem for p in folder.glob('*.txt')})
        self.assertEqual(sorted(folder.glob('001_*.txt'))[-1].read_text('utf-8-sig'), 'LR5')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'selected','ids':[1], 'seed_mode':'previous'})
        self.wait()
        self.assertEqual(m.engine.calls[-1][2], rows[0]['used_seed'])
        path = m.project_path(pid)
        p = m.load_project(pid)
        p['rows'][1]['status'] = 'generating'
        m.atomic_json(path, p)
        self.assertEqual(self.c.get(f'/api/projects/{pid}').json()['rows'][1]['status'], 'error')

    def test_edits_validation_and_security(self):
        pid = self.create('最初')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'})
        self.wait()
        edit = dict(subtitle_text='表示\n改行',speech_text='最初',duration_scale=1,seed=None)
        self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/1',json=edit).json()['status'], 'generated')
        edit['speech_text']='変更'
        self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/1',json=edit).json()['status'], 'stale')
        edit['duration_scale']=0
        self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/1',json=edit).status_code,422)
        self.assertEqual(self.c.post('/api/projects',files={'file':('empty.txt',b'\n ')}).status_code,400)
        self.assertEqual(self.c.put('/api/dictionary',json=[],headers={'origin':'https://example.com'}).status_code,403)

    def test_busy_lock_and_reference_invalidation(self):
        pid = self.create('最初')
        started, release = threading.Event(), threading.Event()
        original = m.engine.generate

        def blocked(*args):
            started.set()
            release.wait(3)
            return original(*args)

        m.engine.generate = blocked
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'})
        self.assertTrue(started.wait(2))
        try:
            self.assertEqual(self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'}).status_code,409)
            self.assertEqual(self.c.put('/api/dictionary',json=[]).status_code,409)
            self.assertEqual(self.c.put(f'/api/projects/{pid}/rows/1',json=dict(subtitle_text='変更',speech_text='変更',duration_scale=1)).status_code,409)
        finally:
            release.set()
            self.wait()
        other = Path(temp.name) / 'other.wav'
        other.write_bytes(b'other')
        self.c.put('/api/settings',json={'reference':str(other),'duration_scale':1})
        self.assertEqual(self.c.get(f'/api/projects/{pid}').json()['rows'][0]['status'],'stale')

    def test_direct_export_and_named_project_copy(self):
        pid = self.create('保存テスト')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'})
        self.wait()
        folder = Path(temp.name) / 'direct-output'
        result = self.c.post(f'/api/projects/{pid}/export', json={'folder':str(folder)}).json()
        self.assertEqual(Path(result['folder']), folder)
        self.assertEqual(len(list(folder.iterdir())), 2)
        previous = next(folder.glob('*.txt'))
        previous.write_text('old', 'utf-8')
        self.c.post(f'/api/projects/{pid}/export', json={'folder':str(folder)})
        self.assertEqual(previous.read_text('utf-8'), 'old')
        self.assertEqual(len(list(folder.iterdir())), 4)
        saved = self.c.post(f'/api/projects/{pid}/save', json={'name':'作品A','output_folder':str(folder)}).json()
        self.assertEqual(saved['project']['name'], '作品A')
        copied = self.c.post(f'/api/projects/{pid}/save', json={'name':'作品B','output_folder':str(folder),'copy_project':True}).json()['project']
        self.assertNotEqual(copied['id'], pid)
        self.assertTrue((m.project_path(copied['id']).parent / 'audio/001.wav').is_file())
        self.assertEqual(self.c.get(f'/api/projects/{pid}').json()['name'], '作品A')

    def test_native_save_open_and_cancel(self):
        pid = self.create('持ち運ぶ音声')
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'})
        self.wait()
        target = str(Path(temp.name) / '作品.irodori')
        with patch.object(m, 'choose_path', return_value=target):
            saved = self.c.post(f'/api/projects/{pid}/save', json={'name':'作品', 'native_dialog':True}).json()
            self.assertEqual(saved['path'],target)
            opened = self.c.post('/api/projects/open-file').json()['project']
        self.assertNotEqual(opened['id'],pid)
        self.assertEqual(opened['rows'][0]['speech_text'],'持ち運ぶ音声')
        self.assertEqual((m.project_path(opened['id']).parent / 'audio/001.wav').read_bytes(),b'RIFF-test')
        with patch.object(m, 'choose_path', return_value=''):
            self.assertTrue(self.c.post(f'/api/projects/{pid}/save',json={'name':'取消','native_dialog':True}).json()['cancelled'])
        self.assertEqual(self.c.get(f'/api/projects/{pid}').json()['name'],'作品')

    def test_number_preview_generation_export_and_toggle(self):
        source = '3ターンの間、攻撃力が30%増加する'
        pid = self.create(source)
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        expected = 'さんたーんの間、攻撃力がさんじゅっぱーせんと増加する'
        self.assertEqual(row['preview'], expected)
        self.c.post(f'/api/projects/{pid}/generate', json={'mode':'all'})
        self.wait()
        self.assertEqual(m.engine.calls[0][0], expected)
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        for key in ('original_text', 'subtitle_text', 'speech_text'):
            self.assertEqual(row[key], source)
        folder = Path(temp.name) / 'numbers-output'
        self.c.post(f'/api/projects/{pid}/export',json={'folder':str(folder)})
        self.assertEqual(sorted(folder.glob('001_*.txt'))[-1].read_text('utf-8-sig'),source)
        settings = dict(m.settings, normalize_numbers=False)
        self.c.put('/api/settings',json=settings)
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        self.assertEqual(row['preview'],source)
        self.assertEqual(row['status'],'stale')
        edit = dict(subtitle_text=source,speech_text='攻撃力が3136増加する',duration_scale=1)
        self.c.put('/api/settings',json=dict(m.settings,normalize_numbers=True))
        row = self.c.put(f'/api/projects/{pid}/rows/1',json=edit).json()
        self.assertEqual(row['preview'],'攻撃力がさんぜんひゃくさんじゅうろく増加する')

    def test_subtitle_wrapping_export_only(self):
        from app.preprocessing import normalize_for_tts
        from app.subtitle_formatter import format_subtitle
        source = '3ターンの間、攻撃力が30%増加し、さらにクリティカル率も上昇する'
        pid = self.create(source)
        self.c.post(f'/api/projects/{pid}/generate',json={'mode':'all'})
        self.wait()
        self.assertEqual(m.engine.calls[0][0],normalize_for_tts(source))
        self.assertNotIn('\n',m.engine.calls[0][0])
        folder = Path(temp.name) / 'subtitle-output'
        self.c.post(f'/api/projects/{pid}/export',json={'folder':str(folder)})
        exported = sorted(folder.glob('001_*.txt'))[-1].read_text('utf-8-sig')
        self.assertEqual(exported,format_subtitle(source))
        self.assertEqual(exported.count('\n'),1)
        self.assertIn('30%',exported)
        self.c.put('/api/settings',json=dict(m.settings,wrap_subtitles=False))
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        self.assertEqual(row['status'],'generated')
        for key in ('original_text','speech_text','subtitle_text'):
            self.assertEqual(row[key],source)
        self.c.post(f'/api/projects/{pid}/export',json={'folder':str(folder)})
        self.assertEqual(sorted(folder.glob('001_*.txt'))[-1].read_text('utf-8-sig'),source)

    def test_selected_export_keeps_numbers_and_ignores_other_rows(self):
        pid = self.create('最初\n次\n最後')
        self.c.post(f'/api/projects/{pid}/generate',json={'mode':'selected','ids':[1,3]})
        self.wait()
        folder = Path(temp.name) / 'selected-output'
        request = {'folder':str(folder),'ids':[3,1,3]}
        response = self.c.post(f'/api/projects/{pid}/export',json=request)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['count'],2)
        self.assertEqual(sorted(p.name.split('_')[0] for p in folder.iterdir()),['001','001','003','003'])
        for ids in ([],[99],[2]):
            response = self.c.post(f'/api/projects/{pid}/export',json=dict(request,ids=ids))
            self.assertEqual(response.status_code,400)

    def test_new_project_add_row_and_preserve_audio(self):
        p = self.c.post('/api/projects/new').json()
        pid = p['id']
        self.assertEqual(p['rows'],[])
        self.assertEqual(self.c.post(f'/api/projects/{pid}/export',json={}).status_code,400)
        self.assertEqual(self.c.post(f'/api/projects/{pid}/rows',json={'text':'  '}).status_code,400)
        self.c.put('/api/settings',json=dict(m.settings,duration_scale=.85))
        self.assertEqual(self.c.post(f'/api/projects/{pid}/rows',json={'text':'いちごです'}).json()['id'],1)
        row = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        self.assertEqual(row['duration_scale'],.85)
        self.assertEqual(row['speech_text'],row['subtitle_text'])
        self.c.post(f'/api/projects/{pid}/generate',json={'mode':'all'})
        self.wait()
        original = self.c.get(f'/api/projects/{pid}').json()['rows'][0]
        self.c.post(f'/api/projects/{pid}/rows',json={'text':'続きです'})
        rows = self.c.get(f'/api/projects/{pid}').json()['rows']
        self.assertEqual(rows[0],original)
        self.assertEqual(rows[1]['id'],2)
        self.assertEqual(rows[1]['status'],'pending')

    def test_export_timestamp_seed_and_collision(self):
        from datetime import datetime
        pid = self.create('出力テスト')
        self.c.post(f'/api/projects/{pid}/generate',json={'mode':'all'})
        self.wait()
        seed = self.c.get(f'/api/projects/{pid}').json()['rows'][0]['used_seed']
        folder = Path(temp.name) / 'collision-output'
        with patch.object(m, 'datetime') as clock:
            clock.now.return_value = datetime(2026,9,8,12,34,56,990000)
            first = self.c.post(f'/api/projects/{pid}/export',json={'folder':str(folder)}).json()
            original = {p.name:p.read_bytes() for p in folder.iterdir()}
            second = self.c.post(f'/api/projects/{pid}/export',json={'folder':str(folder)}).json()
        self.assertEqual(first['files'],[f'001_20260908_123456_99_seed{seed}.wav'])
        self.assertEqual(second['files'],[f'001_20260908_123457_00_seed{seed}.wav'])
        self.assertEqual(len(list(folder.iterdir())),4)
        for name, data in original.items():
            self.assertEqual((folder/name).read_bytes(),data)


if __name__ == '__main__':
    unittest.main()
