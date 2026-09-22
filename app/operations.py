"""Admission and cancellation, independent of the project/data lock."""
import threading
import uuid
from collections import OrderedDict
from fastapi import HTTPException


class Operations:
    def __init__(self, stop_event):
        self.lock = threading.Lock()
        self.stop_event = stop_event
        self.active = None
        self.seen = OrderedDict()

    def begin(self, pid, kind, request_id=None):
        with self.lock:
            if self.active:
                raise HTTPException(409, '別の生成・出力が実行中です。完了後に実行してください。')
            if request_id and request_id in self.seen:
                raise HTTPException(409, 'この生成・出力要求は受付済みです。')
            token = request_id or uuid.uuid4().hex
            if len(token) > 128:
                raise HTTPException(400, '実行IDが長すぎます')
            self.seen[token] = True
            if len(self.seen) > 4096:
                self.seen.popitem(last=False)
            self.stop_event.clear()
            self.active = dict(id=token, project=pid, kind=kind, stop_requested=False, handed_off=False)
            return self.active

    def finish(self, token):
        with self.lock:
            if self.active and self.active['id'] == token:
                self.active = None

    def snapshot(self):
        with self.lock:
            return dict(self.active) if self.active else None

    def stop(self, pid, token=None):
        with self.lock:
            if not token or not self.active or self.active['project'] != pid or token != self.active['id']:
                raise HTTPException(409, '対象の生成・出力は実行中ではありません。')
            self.active['stop_requested'] = True
            self.stop_event.set()
            return dict(self.active)
