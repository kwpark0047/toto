"""백업·복원 모듈.

책임:
- 지금 DB 를 파일로 내려받기(내보내기)
- 서버가 켜질 때 하루 1회 자동 백업, 최근 N 개만 보관
- 백업 파일에서 복원(되돌리기 어려운 작업이라 호출 전에 반드시 확인 문구를 받는다)

SQLite 의 backup API 를 써서 실행 중에도 안전하게 복사한다. 외부 전송은 하지 않는다.
"""
import os
import re
import shutil
import sqlite3
from datetime import datetime

from . import config, store

KEEP = 7
FMT = "%Y%m%d-%H%M%S"


TURSO_NOTICE = ("Turso(영구 DB) 연결에서는 파일 백업을 쓸 수 없습니다. "
                "Turso 콘솔의 백업 기능을 사용해 주세요.")


def _guard():
    if store.using_turso():
        raise RuntimeError(TURSO_NOTICE)


def backup_dir():
    path = os.path.join(os.path.dirname(config.DB_PATH), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def create(tag="manual"):
    """지금 DB 를 data/backups/backup-<태그>-<시각>.db 로 복사하고 오래된 파일을 정리한다."""
    _guard()
    ts = datetime.now(store.TZ).strftime(FMT)
    name = f"backup-{tag}-{ts}.db"
    path = os.path.join(backup_dir(), name)
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    size = os.path.getsize(path)
    prune(keep=max(KEEP, 1), protect=name)
    return {"name": name, "size": size, "path": path}


def list_backups():
    out = []
    for name in sorted(os.listdir(backup_dir()), reverse=True):
        if not re.match(r"^backup-[\w-]+\.db$", name):
            continue
        path = os.path.join(backup_dir(), name)
        st = os.stat(path)
        out.append({"name": name, "size": st.st_size,
                    "createdAt": datetime.fromtimestamp(st.st_mtime, store.TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "auto": "-daily-" in name})
    return out


def prune(keep=KEEP, protect=None):
    """오래된 백업을 지운다. 파일 이름이 아니라 '만든 시각' 기준(방금 만든 것은 보호)."""
    names = [f for f in os.listdir(backup_dir()) if re.match(r"^backup-[\w-]+\.db$", f)]
    files = sorted(names, key=lambda n: os.path.getmtime(os.path.join(backup_dir(), n)),
                   reverse=True)
    removed = []
    for name in files[keep:]:
        if name == protect:
            continue
        try:
            os.remove(os.path.join(backup_dir(), name))
            removed.append(name)
        except OSError:
            pass
    return removed


def daily():
    """하루 1회 자동 백업. Turso 모드에서는 파일이 없으므로 건너뛴다."""
    if store.using_turso():
        return None
    today = store.today().replace("-", "")
    for name in os.listdir(backup_dir()):
        if name.startswith(f"backup-daily-{today}"):
            return None
    return create("daily")


def restore(name, confirm=None):
    """백업 파일로 되돌린다. confirm 이 '복원'이 아니면 거부한다."""
    _guard()
    if confirm != "복원":
        raise ValueError("복원하려면 확인 문구에 '복원'이라고 입력해 주세요")
    path = os.path.join(backup_dir(), os.path.basename(name))
    if not os.path.isfile(path):
        raise LookupError("백업 파일을 찾을 수 없습니다")
    # 복원 전에 현재 상태도 한 번 더 백업해 둔다
    create("before-restore")
    src = sqlite3.connect(path)
    dst = sqlite3.connect(config.DB_PATH)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(config.DB_PATH + suffix)
        except OSError:
            pass
    store.init()
    return {"restored": True, "name": os.path.basename(name)}


def export_bytes():
    """내려받기용 현재 DB 바이트(일관된 스냅숏)."""
    _guard()
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    with open(tmp, "rb") as f:
        data = f.read()
    os.remove(tmp)
    return data
