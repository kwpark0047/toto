"""Vercel Python serverless entrypoint."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import store
from server import Handler

_initialized = False


class handler(Handler):
    def _ensure_init(self):
        global _initialized
        if not _initialized:
            store.init()
            _initialized = True

    def _handle(self, method):
        self._ensure_init()
        return super()._handle(method)
