"""Vercel Python serverless entrypoint."""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import store
from server import Handler

_initialized = False
_init_lock = threading.Lock()


class handler(Handler):
    def _ensure_init(self):
        global _initialized
        if _initialized:
            return
        # 같은 인스턴스로 동시에 들어온 첫 요청이 준비를 두 번 하지 않게 한 번만 잡는다.
        with _init_lock:
            if not _initialized:
                store.init()
                _initialized = True

    def _handle(self, method):
        self._ensure_init()
        return super()._handle(method)
