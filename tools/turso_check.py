#!/usr/bin/env python3
"""Turso HTTP v2 pipeline 드라이버 점검 (개발용).

실제 Turso 자격증명 없이도 드라이버를 검증할 수 있도록,
sqlite3 위에 /v2/pipeline 을 흉내 내는 작은 서버를 띄우고
app.store 가 Turso 모드로 스키마 생성·시드·CRUD·트랜잭션을 수행하는지 본다.

실행:
    python3 tools/turso_check.py
"""
import base64
import json
import os
import sqlite3
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WORK = "/workspace/.tmp-test"
FAKE_DB = os.path.join(WORK, "turso-fake.db")
PORT = 8123
TOKEN = "local-test-token"


def enc(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode()}
    return {"type": "text", "value": str(value)}


def dec(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64") or "")
    return cell.get("value")


class FakeTurso:
    """sqlite3 를 Hrana v2 pipeline 처럼 감싼 최소 서버."""

    def __init__(self):
        os.makedirs(WORK, exist_ok=True)
        if os.path.exists(FAKE_DB):
            os.remove(FAKE_DB)
        self.streams = {}
        self.lock = threading.Lock()
        self.calls = 0

    def new_conn(self):
        conn = sqlite3.connect(FAKE_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def pipeline(self, payload):
        with self.lock:
            self.calls += 1
            baton = payload.get("baton")
            if baton:
                stream = self.streams.get(baton)
                if not stream:
                    return {"error": "unknown baton"}, 400
                conn = stream["conn"]
            else:
                conn = self.new_conn()
                baton = uuid.uuid4().hex[:12]
                self.streams[baton] = {"conn": conn}
            results = []
            closed = False
            for request in payload.get("requests") or []:
                if closed:
                    break
                if request.get("type") == "close":
                    results.append({"type": "ok", "response": {"type": "close"}})
                    closed = True
                    break
                stmt = request.get("stmt") or {}
                sql = stmt.get("sql") or ""
                args = [dec(a) for a in (stmt.get("args") or [])]
                try:
                    cur = conn.execute(sql, args)
                    if stmt.get("want_rows"):
                        cols = [{"name": d[0]} for d in (cur.description or [])]
                        rows = [[enc(v) for v in row] for row in cur.fetchall()]
                    else:
                        cols, rows = [], []
                    rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    results.append({"type": "ok", "response": {"type": "execute", "result": {
                        "cols": cols, "rows": rows,
                        "affected_row_count": cur.rowcount,
                        "last_insert_rowid": str(rowid),
                    }}})
                except sqlite3.Error as exc:
                    results.append({"type": "error", "error": {"message": str(exc)}})
                    closed = True
            if closed:
                conn.close()
                self.streams.pop(baton, None)
                return {"baton": None, "results": results}, 200
            return {"baton": baton, "results": results}, 200


FAKE = FakeTurso()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if not self.path.endswith("/v2/pipeline"):
            self.send_response(404)
            self.end_headers()
            return
        if (self.headers.get("Authorization") or "") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode() or "{}")
        body, status = FAKE.pipeline(payload)
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


failures = []


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ❌ ") + name + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    os.environ["TURSO_DATABASE_URL"] = "libsql://w-toto-example.turso.io"
    os.environ["TURSO_AUTH_TOKEN"] = TOKEN
    os.environ.pop("MENU_DB", None)

    from app import store

    print("\n[1] Turso 모드 인식")
    check("환경변수 두 개로 Turso 모드", store.using_turso(), store.backend())
    check("libsql:// → https /v2/pipeline",
          store._turso_endpoint() == "https://w-toto-example.turso.io/v2/pipeline",
          store._turso_endpoint())

    # 실제 요청은 로컬 가짜 서버(http)로 보낸다
    os.environ["TURSO_DATABASE_URL"] = f"http://127.0.0.1:{PORT}"
    check("http URL 은 그대로 사용", store._turso_endpoint() == f"http://127.0.0.1:{PORT}/v2/pipeline",
          store._turso_endpoint())

    print("\n[2] 스키마 생성·시드 (자동 초기화)")
    store.init()
    with store.read() as conn:
        items = conn.execute("SELECT COUNT(*) c FROM menu_items").fetchone()["c"]
        tables = conn.execute("SELECT COUNT(*) c FROM dining_tables").fetchone()["c"]
        posts = conn.execute("SELECT COUNT(*) c FROM board_posts").fetchone()["c"]
        stores = conn.execute("SELECT COUNT(*) c FROM stores").fetchone()["c"]
    check("menu_items 16개 시드", items == 16, items)
    check("dining_tables 8개 시드", tables == 8, tables)
    check("board_posts 3개 시드", posts == 3, posts)
    check("기본 매장 1개", stores == 1, stores)

    print("\n[3] 두 번째 init() — 중복 시드 없음")
    store.init()
    with store.read() as conn:
        items2 = conn.execute("SELECT COUNT(*) c FROM menu_items").fetchone()["c"]
        posts2 = conn.execute("SELECT COUNT(*) c FROM board_posts").fetchone()["c"]
    check("메뉴 중복 없음", items2 == 16, items2)
    check("공지 중복 없음", posts2 == 3, posts2)

    print("\n[4] 행 접근 (이름·인덱스·keys·dict)")
    with store.read() as conn:
        row = conn.execute("SELECT id, name, price FROM menu_items ORDER BY id LIMIT 1").fetchone()
    check("row['name']", row["name"] == "김밥", row["name"])
    check("row[0] == row['id']", row[0] == row["id"])
    check("keys()", row.keys() == ["id", "name", "price"], row.keys())
    check("dict(row)", dict(row)["price"] == 3500, dict(row))

    print("\n[5] INSERT lastrowid · UPDATE rowcount")
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO customers(store_id, name, phone, birthday, grade, consent, memo,"
            " created_at, updated_at) VALUES(1,'시험손님','010-0000-1111','','',0,'',?,?)",
            (store.now(), store.now()))
        new_id = cur.lastrowid
        upd = conn.execute("UPDATE customers SET memo='단골' WHERE id=?", (new_id,))
        check("lastrowid 로 새 행 id", isinstance(new_id, int) and new_id > 0, new_id)
        check("rowcount 1", upd.rowcount == 1, upd.rowcount)
    with store.read() as conn:
        saved = conn.execute("SELECT name, memo FROM customers WHERE id=?", (new_id,)).fetchone()
    check("tx 커밋 후 조회", saved and saved["memo"] == "단골", saved and saved["memo"])

    print("\n[6] tx 롤백 — 예외가 나면 남지 않음")
    try:
        with store.tx() as conn:
            conn.execute(
                "INSERT INTO customers(store_id, name, phone, birthday, grade, consent, memo,"
                " created_at, updated_at) VALUES(1,'롤백손님','010-0000-2222','','',0,'',?,?)",
                (store.now(), store.now()))
            conn.execute("SELECT COUNT(*) FROM customers").fetchone()  # 중간 flush 유도
            raise RuntimeError("일부러 실패")
    except RuntimeError:
        pass
    with store.read() as conn:
        gone = conn.execute("SELECT COUNT(*) c FROM customers WHERE name='롤백손님'").fetchone()["c"]
    check("롤백 후 행 없음", gone == 0, gone)

    print("\n[7] executemany · executescript · 바인딩 형식")
    with store.tx() as conn:
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("t_a", "1"), ("t_b", "2")])
        conn.executescript("UPDATE meta SET value='3' WHERE key='t_a';"
                           "UPDATE meta SET value='4' WHERE key='t_b';")
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)", ("t_c", "  세미콜론; 문자열 "))
    with store.read() as conn:
        meta = {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE 't_%'").fetchall()}
    check("executemany 두 건", meta.get("t_a") == "3" and meta.get("t_b") == "4", meta)
    check("문자열 안 세미콜론 보존", meta.get("t_c") == "  세미콜론; 문자열 ", meta.get("t_c"))

    print("\n[8] bump/rev (ON CONFLICT · CAST)")
    with store.tx() as conn:
        store.bump(conn)
    with store.read() as conn:
        check("rev 증가", store.rev(conn) >= 1, store.rev(conn))

    print("\n[9] 백업 가드")
    import importlib
    from app import backup
    importlib.reload(backup)
    try:
        backup.create("test")
        check("Turso 모드에서 파일 백업 거부", False, "예외 없음")
    except RuntimeError as exc:
        check("Turso 모드에서 파일 백업 거부", "Turso" in str(exc), str(exc))

    server.shutdown()
    print(f"\n  (가짜 서버 pipeline 호출 {FAKE.calls}회)")
    print()
    if failures:
        print("문제:", *failures, sep="\n - ")
        sys.exit(1)
    print("Turso 드라이버 점검 통과")


if __name__ == "__main__":
    main()
