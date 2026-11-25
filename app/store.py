"""데이터 저장 계층.

- 기본은 SQLite 파일 하나(data/mangjip.db)에 모든 데이터를 저장한다.
- 환경변수 TURSO_DATABASE_URL · TURSO_AUTH_TOKEN 이 모두 있으면(Vercel)
  Turso(libSQL) HTTP v2 pipeline 으로 붙어 영구 저장소로 동작한다.
- 다른 모듈은 이 파일의 connect()/tx() 를 통해서만 DB에 접근한다.
- 'rev' 값은 화면 폴링용 변경 번호다. 데이터가 바뀔 때마다 1씩 올린다.
- 스키마를 바꿀 때는 SCHEMA 에 더하고, 이미 있는 DB 는 _migrate() 가 컬럼을 채워 준다.
"""
import base64
import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo("Asia/Seoul")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  tagline TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL,
  price INTEGER NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  image TEXT NOT NULL DEFAULT '',
  options TEXT NOT NULL DEFAULT '[]',
  soldout INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0,
  featured INTEGER NOT NULL DEFAULT 0,
  featured_sort INTEGER NOT NULL DEFAULT 0,
  featured_note TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT '',
  allergens TEXT NOT NULL DEFAULT '[]',
  spice INTEGER NOT NULL DEFAULT 0,
  i18n TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  birthday TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  consent INTEGER NOT NULL DEFAULT 0,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL,
  table_no INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'NEW',
  payment_status TEXT NOT NULL DEFAULT 'UNPAID',
  payment_method TEXT NOT NULL DEFAULT 'CASH',
  subtotal INTEGER NOT NULL DEFAULT 0,
  points_used INTEGER NOT NULL DEFAULT 0,
  points_earned INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  customer_id INTEGER REFERENCES customers(id),
  customer_name TEXT NOT NULL DEFAULT '',
  customer_phone TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  reserved_for INTEGER,
  receipt_type TEXT NOT NULL DEFAULT 'none',
  receipt_no TEXT NOT NULL DEFAULT '',
  receipt_issued INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  accepted_at TEXT, cooking_at TEXT, done_at TEXT, paid_at TEXT, canceled_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  item_id INTEGER,
  name TEXT NOT NULL,
  price INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  options_text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE TABLE IF NOT EXISTS point_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  order_id INTEGER,
  kind TEXT NOT NULL,
  delta INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_point_events_cust ON point_events(customer_id);
CREATE TABLE IF NOT EXISTS dining_tables (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  seats INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'counter',
  memo TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  password_hash TEXT NOT NULL,
  last_login_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_sessions (
  token TEXT PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  work_date TEXT NOT NULL,
  clock_in TEXT NOT NULL,
  clock_out TEXT,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_open ON attendance(staff_id) WHERE clock_out IS NULL;
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(work_date);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS waiting_tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  party_size INTEGER NOT NULL DEFAULT 1,
  consent INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'WAITING',
  created_at TEXT NOT NULL,
  called_at TEXT, seated_at TEXT, closed_at TEXT,
  table_id INTEGER,
  note TEXT NOT NULL DEFAULT '',
  purged INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_waiting_status ON waiting_tickets(status, created_at);
CREATE TABLE IF NOT EXISTS waiting_counters (
  date TEXT PRIMARY KEY,
  last_no INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifier_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  event TEXT NOT NULL,
  ticket_id INTEGER,
  ticket_no TEXT NOT NULL DEFAULT '',
  recipient TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifier_log_date ON notifier_log(created_at);
CREATE TABLE IF NOT EXISTS service_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_no INTEGER NOT NULL,
  table_label TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'OPEN',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  done_at TEXT,
  staff_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_service_calls ON service_calls(status, created_at);
CREATE TABLE IF NOT EXISTS voice_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  action TEXT NOT NULL DEFAULT '',
  lines_json TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  endpoint TEXT NOT NULL,
  keys_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  name TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT '개',
  stock REAL NOT NULL DEFAULT 0,
  safety REAL NOT NULL DEFAULT 0,
  memo TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  menu_item_id INTEGER NOT NULL,
  ingredient_id INTEGER NOT NULL,
  qty REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(menu_item_id, ingredient_id)
);
CREATE TABLE IF NOT EXISTS ingredient_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  ingredient_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  delta REAL NOT NULL DEFAULT 0,
  stock_after REAL NOT NULL DEFAULT 0,
  order_id INTEGER,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingredient_logs ON ingredient_logs(ingredient_id, id);
CREATE TABLE IF NOT EXISTS reservations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  token TEXT NOT NULL UNIQUE,
  res_date TEXT NOT NULL,
  res_time TEXT NOT NULL,
  party_size INTEGER NOT NULL DEFAULT 2,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  memo TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  table_id INTEGER,
  consent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reservations_date ON reservations(res_date, res_time);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  order_id INTEGER NOT NULL UNIQUE,
  table_no INTEGER,
  rating INTEGER NOT NULL,
  comment TEXT NOT NULL DEFAULT '',
  hidden INTEGER NOT NULL DEFAULT 0,
  reply TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  replied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(created_at);
CREATE TABLE IF NOT EXISTS staff_schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id INTEGER NOT NULL DEFAULT 1,
  staff_id INTEGER NOT NULL,
  work_date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules ON staff_schedules(work_date, staff_id);
CREATE TABLE IF NOT EXISTS oauth_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  subject TEXT NOT NULL,
  staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  email TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  linked_at TEXT NOT NULL,
  last_login_at TEXT,
  UNIQUE(provider, subject)
);
CREATE INDEX IF NOT EXISTS idx_oauth_staff ON oauth_accounts(staff_id);
CREATE TABLE IF NOT EXISTS inquiries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receipt_no TEXT NOT NULL UNIQUE,
  store_name TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '도입 문의',
  message TEXT NOT NULL,
  consent INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'NEW',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inquiries_created ON inquiries(created_at);
CREATE TABLE IF NOT EXISTS board_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL DEFAULT 'notice',
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT '',
  hidden INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_board_created ON board_posts(created_at);
CREATE TABLE IF NOT EXISTS board_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES board_posts(id) ON DELETE CASCADE,
  author TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  hidden INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_board_comments ON board_comments(post_id, id);
CREATE TABLE IF NOT EXISTS staff_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  staff_id INTEGER NOT NULL,
  from_store INTEGER NOT NULL,
  to_store INTEGER NOT NULL,
  actor_id INTEGER,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_transfers ON staff_transfers(staff_id, id);
"""

SEED_CATEGORIES = ["분식", "한식", "사이드", "음료"]

# (카테고리, 이름, 가격, 설명, 이미지, 옵션)
SEED_ITEMS = [
    ("분식", "김밥", 3500, "밥알을 고슬고슬하게 말아 낸 기본 김밥", "kimbap", []),
    ("분식", "떡볶이", 4500, "쌀떡으로 만든 국물 떡볶이 · 삶은 달걀 추가", "tteokbokki",
     [{"name": "맵기", "choices": ["순한맛", "보통", "매운맛"], "default": "보통"}]),
    ("분식", "순대", 5000, "찹쌀 순대와 간, 소금 후추 간장", "sundae", []),
    ("분식", "모둠튀김", 5000, "오징어·김말이·야채 튀김 모둠", "twigim", []),
    ("분식", "라면", 4000, "매운맛 라면 · 사리 추가 가능", "ramyeon",
     [{"name": "사리", "choices": ["기본", "곱빼기", "치즈 추가"], "default": "기본"}]),
    ("한식", "김치찌개", 8000, "돼지고기 김치찌개 · 공기밥은 따로 주문", "kimchi-jjigae",
     [{"name": "맵기", "choices": ["순한맛", "보통", "매운맛"], "default": "보통"}]),
    ("한식", "된장찌개", 8000, "구수한 시골 된장찌개 · 공기밥은 따로 주문", "doenjang-jjigae", []),
    ("한식", "제육볶음", 9500, "매콤한 제육볶음 · 공기밥은 따로 주문", "jeyuk-bokkeum",
     [{"name": "맵기", "choices": ["순한맛", "보통", "매운맛"], "default": "보통"}]),
    ("한식", "비빔밥", 8000, "나물 가득 비빔밥 · 고추장 별도", "bibimbap", []),
    ("한식", "불고기", 11000, "간장 양념 불고기 · 공기밥은 따로 주문", "bulgogi", []),
    ("한식", "잔치국수", 6000, "멸치 육수에 말아 낸 잔치국수", "janchi-guksu", []),
    ("사이드", "계란말이", 7000, "폭신하게 말아 낸 계란말이", "gyeran-mari", []),
    ("사이드", "만두", 5000, "김치 만두 6개", "mandu",
     [{"name": "조리", "choices": ["찐만두", "군만두"], "default": "찐만두"}]),
    ("음료", "콜라", 2000, "시원한 콜라 245ml", "cola", []),
    ("음료", "식혜", 2500, "직접 만든 식혜", "sikye", []),
    ("음료", "아이스아메리카노", 3000, "원두 추출 아이스 아메리카노", "iced-americano", []),
]


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ==========================================================================
# Turso(libSQL) — Vercel serverless 영구 DB (HTTP v2 pipeline)
#
# 외부 패키지 없이 urllib 로 https://<host>/v2/pipeline 을 호출한다.
# - 읽기 결과가 필요할 때까지 문장을 모아 한 번에 보낸다(왕복 비용 절감).
# - 자동 커밋 묶음은 BEGIN … COMMIT 을 한 요청에 넣어 원자적으로 처리한다.
# - `with conn:` / store.tx() 안에서는 baton 으로 스트림을 이어 트랜잭션을 유지한다.
# ==========================================================================
_TURSO_TIMEOUT = 30          # 초
_TURSO_CHUNK = 70            # 한 pipeline 에 넣는 문장 수 상한


def _turso_conf():
    url = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
    token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    return url, token


def using_turso():
    """환경변수가 모두 있을 때만 Turso 모드. 없으면 기존 SQLite 파일."""
    url, token = _turso_conf()
    return bool(url and token)


def backend():
    return "turso" if using_turso() else "sqlite"


def _turso_endpoint():
    url = _turso_conf()[0]
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    url = url.rstrip("/")
    if url.endswith("/v2/pipeline"):
        return url
    return url + "/v2/pipeline"


class TursoError(Exception):
    """Turso/libSQL 이 돌려준 오류."""


def _encode_value(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_value(cell):
    if not isinstance(cell, dict):
        return cell
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        try:
            return int(cell.get("value") or 0)
        except (TypeError, ValueError):
            return 0
    if kind == "float":
        try:
            return float(cell.get("value") or 0)
        except (TypeError, ValueError):
            return 0.0
    if kind == "text":
        return cell.get("value") or ""
    if kind == "blob":
        try:
            return base64.b64decode(cell.get("base64") or "")
        except (ValueError, TypeError):
            return b""
    return cell.get("value")


class TursoRow:
    """sqlite3.Row 처럼 이름(row["id"])과 순서(row[0]) 모두로 읽는 행."""

    __slots__ = ("_cols", "_values", "_index")

    def __init__(self, cols, values):
        self._cols = tuple(cols)
        self._values = tuple(values)
        self._index = {name: i for i, name in enumerate(self._cols)}

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._index[key]]
            except KeyError:
                raise IndexError(f"no such column: {key}")
        if isinstance(key, slice):
            return self._values[key]
        return self._values[key]

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def __contains__(self, key):
        return key in self._index

    def keys(self):
        return list(self._cols)

    def __repr__(self):
        return "TursoRow(" + ", ".join(f"{k}={v!r}" for k, v in zip(self._cols, self._values)) + ")"


def _split_sql(script):
    """executescript 용 문장 분리. 문자열·주석 안의 세미콜론은 나누지 않는다."""
    out, buf = [], []
    quote = None
    i, n = 0, len(script or "")
    while i < n:
        ch = script[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if i + 1 < n and script[i + 1] == quote:
                    buf.append(script[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "-" and script.startswith("--", i):
            j = script.find("\n", i)
            if j < 0:
                break
            i = j + 1
            continue
        if ch == "/" and script.startswith("/*", i):
            j = script.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch == ";":
            text = "".join(buf).strip()
            if text:
                out.append(text)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    text = "".join(buf).strip()
    if text:
        out.append(text)
    return out


class _TursoStmt:
    __slots__ = ("sql", "params", "cols", "rows", "rowcount", "lastrowid")

    def __init__(self, sql, params=()):
        raw = str(sql or "").strip()
        head = raw.upper().replace("\n", " ")
        if head.startswith("PRAGMA JOURNAL_MODE") or head.startswith("PRAGMA FOREIGN_KEYS"):
            # Turso 는 이 PRAGMA 를 허용하지 않는다(서버가 이미 WAL·FK 기본).
            raw = "SELECT 1"
        self.sql = raw
        self.params = tuple(params or ())
        self.cols = []
        self.rows = []
        self.rowcount = -1
        self.lastrowid = None


def _turso_call(requests, baton=None):
    """POST /v2/pipeline → (baton, results)"""
    url, token = _turso_conf()
    if not url or not token:
        raise TursoError("Turso 환경변수가 없습니다")
    payload = {"requests": requests}
    if baton:
        payload["baton"] = baton
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _turso_endpoint(), data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TURSO_TIMEOUT) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        message = body
        try:
            parsed = json.loads(body)
            message = parsed.get("error") or parsed.get("message") or body
        except (ValueError, AttributeError):
            pass
        raise TursoError(f"Turso HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise TursoError(f"Turso 연결 실패: {exc.reason}") from exc
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise TursoError("Turso 응답을 해석하지 못했습니다") from exc
    return parsed.get("baton"), parsed.get("results") or []


def _exec_request(stmt):
    return {
        "type": "execute",
        "stmt": {
            "sql": stmt.sql,
            "args": [_encode_value(p) for p in stmt.params],
            "want_rows": True,
        },
    }


def _apply_result(stmt, result):
    if not isinstance(result, dict):
        raise TursoError("Turso 결과 형식이 올바르지 않습니다")
    if result.get("type") == "error":
        err = result.get("error") or {}
        message = err.get("message") or err.get("code") or "Turso 실행 오류"
        raise TursoError(str(message))
    response = result.get("response") or {}
    payload = response.get("result") or {}
    cols = [c.get("name") for c in (payload.get("cols") or [])]
    stmt.cols = cols
    stmt.rows = [TursoRow(cols, [_decode_value(v) for v in raw])
                 for raw in (payload.get("rows") or [])]
    affected = payload.get("affected_row_count")
    stmt.rowcount = int(affected) if affected is not None else -1
    rowid = payload.get("last_insert_rowid")
    if rowid is not None:
        try:
            stmt.lastrowid = int(rowid)
        except (TypeError, ValueError):
            stmt.lastrowid = None


class TursoCursor:
    def __init__(self, conn, stmt):
        self._conn = conn
        self._stmt = stmt
        self._pos = 0

    def _ready(self):
        self._conn._flush()

    def fetchone(self):
        self._ready()
        rows = self._stmt.rows
        if self._pos < len(rows):
            row = rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        self._ready()
        rows = self._stmt.rows[self._pos:]
        self._pos = len(self._stmt.rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        pass

    @property
    def lastrowid(self):
        self._ready()
        return self._stmt.lastrowid

    @property
    def rowcount(self):
        self._ready()
        return self._stmt.rowcount

    @property
    def description(self):
        self._ready()
        return tuple((name, None, None, None, None, None, None)
                     for name in self._stmt.cols)


class TursoConnection:
    """sqlite3.Connection 의 쓰임새만 흉내 내는 경량 래퍼."""

    def __init__(self):
        self._pending = []
        self._baton = None
        self._tx = False
        self._closed = False
        self.row_factory = TursoRow

    # ---- 문장 모으기 -------------------------------------------------
    def execute(self, sql, params=()):
        if self._closed:
            raise TursoError("닫힌 연결입니다")
        stmt = _TursoStmt(sql, params)
        self._pending.append(stmt)
        return TursoCursor(self, stmt)

    def executemany(self, sql, seq_of_params):
        cur = None
        for params in seq_of_params:
            cur = self.execute(sql, params)
        if cur is None:
            cur = self.execute(sql, ())
        return cur

    def executescript(self, script):
        last = None
        for text in _split_sql(script):
            last = self.execute(text)
        return last

    # ---- 실행 ---------------------------------------------------------
    def _flush(self):
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        if self._tx:
            self._flush_tx(batch)
        else:
            self._flush_auto(batch)

    def _flush_auto(self, batch):
        for start in range(0, len(batch), _TURSO_CHUNK):
            chunk = batch[start:start + _TURSO_CHUNK]
            requests = [{"type": "execute", "stmt": {"sql": "BEGIN"}}]
            requests += [_exec_request(s) for s in chunk]
            requests.append({"type": "execute", "stmt": {"sql": "COMMIT"}})
            requests.append({"type": "close"})
            _, results = _turso_call(requests)
            if results and isinstance(results[0], dict) and results[0].get("type") == "error":
                # BEGIN 이 거부되면(이미 트랜잭션 등) 트랜잭션 없이 한 번만 다시 보낸다.
                requests = [_exec_request(s) for s in chunk] + [{"type": "close"}]
                _, results = _turso_call(requests)
                offset = 0
            else:
                offset = 1
            for i, stmt in enumerate(chunk):
                if offset + i >= len(results):
                    raise TursoError("Turso 응답이 일부만 돌아왔습니다")
                _apply_result(stmt, results[offset + i])

    def _flush_tx(self, batch):
        for start in range(0, len(batch), _TURSO_CHUNK):
            chunk = batch[start:start + _TURSO_CHUNK]
            requests = []
            offset = 0
            if self._baton is None:
                requests.append({"type": "execute", "stmt": {"sql": "BEGIN"}})
                offset = 1
            requests += [_exec_request(s) for s in chunk]
            try:
                baton, results = _turso_call(requests, self._baton)
            except Exception:
                self._end_tx("ROLLBACK", ignore_errors=True)
                raise
            self._baton = baton
            for i, stmt in enumerate(chunk):
                if offset + i >= len(results):
                    self._end_tx("ROLLBACK", ignore_errors=True)
                    raise TursoError("Turso 응답이 일부만 돌아왔습니다")
                try:
                    _apply_result(stmt, results[offset + i])
                except TursoError:
                    self._end_tx("ROLLBACK", ignore_errors=True)
                    raise

    def _end_tx(self, sql, ignore_errors=False):
        if self._baton is None:
            return
        baton, self._baton = self._baton, None
        try:
            _turso_call([{"type": "execute", "stmt": {"sql": sql}},
                         {"type": "close"}], baton)
        except TursoError:
            if not ignore_errors:
                raise

    # ---- 트랜잭션 -----------------------------------------------------
    def commit(self):
        self._flush()
        self._end_tx("COMMIT")

    def rollback(self):
        self._pending = []
        self._end_tx("ROLLBACK", ignore_errors=True)

    def close(self):
        if self._closed:
            return
        try:
            self._flush()
        finally:
            self._end_tx("ROLLBACK", ignore_errors=True)
            self._closed = True

    def __enter__(self):
        self._tx = True
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self._tx = False
        return False


def connect():
    if using_turso():
        return TursoConnection()
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    """쓰기 트랜잭션. 정상 종료 시 커밋, 예외 시 롤백."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@contextmanager
def read():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def bump(conn):
    """화면 갱신용 변경 번호를 1 올린다. 반드시 같은 트랜잭션에서 호출."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('rev','1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
    )


def rev(conn=None):
    close = False
    if conn is None:
        conn, close = connect(), True
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='rev'").fetchone()
        return int(row["value"]) if row else 0
    finally:
        if close:
            conn.close()


# 1단계 DB(로그인·회원·테이블 컬럼이 없던 DB)를 그대로 쓰기 위한 보충
_ADDED_COLUMNS = [
    # 다점포(매장 분리) — 기존 데이터는 모두 기본 매장(1)으로 남는다
    ("categories", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("menu_items", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("orders", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("customers", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("dining_tables", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("staff", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("attendance", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("waiting_tickets", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("service_calls", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    ("notifier_log", "store_id", "INTEGER NOT NULL DEFAULT 1"),
    # 직원 역할·권한·급여
    ("staff", "permissions", "TEXT NOT NULL DEFAULT '{}'"),
    ("staff", "pay_type", "TEXT NOT NULL DEFAULT ''"),
    ("staff", "hourly_wage", "INTEGER NOT NULL DEFAULT 0"),
    ("staff", "monthly_salary", "INTEGER NOT NULL DEFAULT 0"),
    ("staff", "must_change", "INTEGER NOT NULL DEFAULT 0"),
    ("staff_sessions", "active_store", "INTEGER"),
    ("customers", "birthday", "TEXT NOT NULL DEFAULT ''"),
    ("customers", "grade", "TEXT NOT NULL DEFAULT ''"),
    ("orders", "subtotal", "INTEGER NOT NULL DEFAULT 0"),
    ("orders", "points_used", "INTEGER NOT NULL DEFAULT 0"),
    ("orders", "points_earned", "INTEGER NOT NULL DEFAULT 0"),
    ("orders", "reserved_for", "INTEGER"),
    ("orders", "receipt_type", "TEXT NOT NULL DEFAULT 'none'"),
    ("orders", "receipt_no", "TEXT NOT NULL DEFAULT ''"),
    ("orders", "receipt_issued", "INTEGER NOT NULL DEFAULT 0"),
    ("orders", "served_at", "TEXT"),
    ("staff", "last_login_at", "TEXT"),
    ("menu_items", "featured", "INTEGER NOT NULL DEFAULT 0"),
    ("menu_items", "featured_sort", "INTEGER NOT NULL DEFAULT 0"),
    ("menu_items", "featured_note", "TEXT NOT NULL DEFAULT ''"),
    ("menu_items", "i18n", "TEXT NOT NULL DEFAULT '{}'"),
    ("waiting_tickets", "purged", "INTEGER NOT NULL DEFAULT 0"),
]


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_columns(conn, tables):
    """여러 테이블의 컬럼을 한 번에 읽는다(Turso 왕복 절감).

    PRAGMA 를 모아 두었다가 첫 fetch 에서 한 pipeline 으로 보낸다.
    서버가 PRAGMA table_info 를 거부하면 table-valued 함수로 다시 시도한다.
    """
    names = list(dict.fromkeys(tables))
    try:
        cursors = {t: conn.execute(f"PRAGMA table_info({t})") for t in names}
        return {t: {r["name"] for r in cursors[t].fetchall()} for t in names}
    except Exception:
        cursors = {t: conn.execute("SELECT name FROM pragma_table_info(?)", (t,))
                   for t in names}
        return {t: {r["name"] for r in cursors[t].fetchall()} for t in names}


def _migrate(conn):
    tables = [table for table, _col, _ddl in _ADDED_COLUMNS]
    have = _table_columns(conn, tables)
    missing = [(t, c, d) for t, c, d in _ADDED_COLUMNS if c not in have.get(t, set())]
    if missing:
        # 평소에는 한 번에 보낸다. 동시에 콜드 스타트한 다른 인스턴스가 같은 컬럼을
        # 먼저 추가해 실패하면, 실제로 생겼는지 확인하며 하나씩 다시 시도한다.
        try:
            for table, col, ddl in missing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            conn.commit()
        except Exception:
            conn.rollback()
            for table, col, ddl in missing:
                if col in _table_columns(conn, [table]).get(table, set()):
                    continue
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    if col not in _table_columns(conn, [table]).get(table, set()):
                        raise
    # 기존 주문은 할인 전 금액을 몰라 total = subtotal 로 채운다
    conn.execute("UPDATE orders SET subtotal = total WHERE subtotal = 0 AND points_used = 0")
    # 회원 연락처는 이제 매장별로 유일하다(같은 번호가 두 매장에 있어도 된다)
    conn.execute("DROP INDEX IF EXISTS idx_customers_phone")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_store_phone"
        " ON customers(store_id, phone) WHERE phone <> ''")
    _ensure_stores(conn)
    conn.commit()


def _ensure_stores(conn):
    """기본 매장(id=1)이 없으면 만든다. 매장 이름은 설정값이 있으면 그것을 쓴다."""
    row = conn.execute("SELECT id FROM stores ORDER BY id LIMIT 1").fetchone()
    if row:
        return
    name = config.STORE.get("name") or "맛집"
    try:
        setting = conn.execute("SELECT value FROM settings WHERE key='store'").fetchone()
        if setting:
            import json
            name = (json.loads(setting["value"] or "{}").get("storeName") or name)
    except (ValueError, TypeError):
        pass
    ts = now()
    conn.execute(
        "INSERT OR IGNORE INTO stores(id, name, tagline, address, phone, active, created_at, updated_at)"
        " VALUES(1,?,?,?,'',1,?,?)",
        (name, config.STORE.get("tagline") or "", config.STORE.get("address") or "", ts, ts))


def init():
    """스키마 생성 + 비어 있으면 기본 데이터를 넣는다."""
    if not using_turso():
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM menu_items WHERE store_id=1) AS items,"
            " (SELECT COUNT(*) FROM dining_tables WHERE store_id=1) AS tbls,"
            " (SELECT COUNT(*) FROM board_posts) AS posts"
        ).fetchone()
        need_seed = bool(
            not counts
            or int(counts["items"] or 0) == 0
            or int(counts["tbls"] or 0) == 0
            or int(counts["posts"] or 0) == 0
        )
        if need_seed:
            # 동시에 콜드 스타트한 인스턴스가 같은 기본 데이터를 두 번 넣지 않도록 한 번만 잡는다.
            lock = conn.execute(
                "INSERT INTO meta(key, value) VALUES('seed_lock','1')"
                " ON CONFLICT(key) DO NOTHING")
            conn.commit()
            mine = lock.rowcount > 0
            if not mine:
                import time
                for _ in range(3):
                    time.sleep(0.15)
                    again = conn.execute(
                        "SELECT (SELECT COUNT(*) FROM menu_items WHERE store_id=1) AS items,"
                        " (SELECT COUNT(*) FROM dining_tables WHERE store_id=1) AS tbls,"
                        " (SELECT COUNT(*) FROM board_posts) AS posts"
                    ).fetchone()
                    if again and int(again["items"] or 0) > 0 and int(again["tbls"] or 0) > 0:
                        counts = again
                        break
                else:
                    mine = True
            if mine:
                counts = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM menu_items WHERE store_id=1) AS items,"
                    " (SELECT COUNT(*) FROM dining_tables WHERE store_id=1) AS tbls,"
                    " (SELECT COUNT(*) FROM board_posts) AS posts"
                ).fetchone()
                if not counts or int(counts["items"] or 0) == 0:
                    seed(conn)
                if not counts or int(counts["tbls"] or 0) == 0:
                    seed_tables(conn)
                if not counts or int(counts["posts"] or 0) == 0:
                    seed_board(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('rev','1') ON CONFLICT(key) DO NOTHING"
        )
        conn.commit()
    finally:
        conn.close()


def seed_board(conn):
    """공개 게시판 기본 공지. 비어 있을 때만 넣는다."""
    ts = now()
    posts = [
        ("notice", "w-toto QR 메뉴판을 시작합니다",
         "테이블 QR·NFC로 메뉴 보기부터 주문·주방·결제 확인·매출까지 한 화면에서 이어지는 "
         "QR 메뉴판 서비스를 시작합니다.\n\n"
         "· 설치비·월 이용료 없이 기본 기능을 모두 쓸 수 있습니다.\n"
         "· 주문 알림은 사장님 화면과 주방 화면에 바로 표시됩니다.\n"
         "· 매장 정보와 메뉴는 로그인 후 '설정'에서 바꿀 수 있습니다.", "w-toto"),
        ("update", "주방 KDS에 알레르기 경고와 묶음 조리를 더했습니다",
         "주문서에 알레르기 정보가 있으면 주방 카드에 경고가 크게 표시됩니다. "
         "같은 메뉴를 여러 테이블에서 주문하면 '메뉴별 묶음' 보기로 한 번에 조리할 수 있습니다.", "w-toto"),
        ("review", "운양동 파일럿 매장 후기",
         "점심 손님이 QR을 찍고 3분 만에 주문이 들어왔습니다. 주방 화면에서 접수·조리·서빙을 "
         "한 번에 보니 홀 직원이 주문을 받으러 다니지 않아도 됐어요. (파일럿 매장 의견 정리)", "파일럿 매장"),
    ]
    for category, title, body, author in posts:
        conn.execute(
            "INSERT INTO board_posts(category, title, body, author, hidden, created_at)"
            " VALUES(?,?,?,?,0,?)", (category, title, body, author, ts))
    conn.commit()


def seed_tables(conn, store_id=1):
    ts = now()
    for i in range(1, config.STORE["tables"] + 1):
        conn.execute(
            "INSERT INTO dining_tables(store_id, code, label, seats, sort, active, created_at, updated_at)"
            " VALUES(?,?,?,?,?,1,?,?)", (store_id, str(i), f"{i}번", 4, i, ts, ts),
        )
    conn.commit()


def seed(conn, store_id=1):
    ts = now()
    cats = {}
    for i, name in enumerate(SEED_CATEGORIES):
        cur = conn.execute(
            "INSERT INTO categories(store_id, name, sort, created_at) VALUES(?,?,?,?)",
            (store_id, name, i + 1, ts)
        )
        cats[name] = cur.lastrowid
    order = {}
    for cat, name, price, desc, image, options in SEED_ITEMS:
        order[cat] = order.get(cat, 0) + 1
        conn.execute(
            "INSERT INTO menu_items(store_id, category_id, name, price, description, image, options,"
            " soldout, sort, created_at, updated_at) VALUES(?,?,?,?,?,?,?,0,?,?,?)",
            (
                store_id, cats[cat], name, price, desc, f"/images/{image}.jpg",
                __import__("json").dumps(options, ensure_ascii=False), order[cat], ts, ts,
            ),
        )
    conn.commit()
