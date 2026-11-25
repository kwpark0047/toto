"""데이터 저장 계층.

- SQLite 파일 하나(data/mangjip.db)에 모든 데이터를 저장한다.
- 다른 모듈은 이 파일의 connect()/tx() 를 통해서만 DB에 접근한다.
- 'rev' 값은 화면 폴링용 변경 번호다. 데이터가 바뀔 때마다 1씩 올린다.
- 스키마를 바꿀 때는 SCHEMA 에 더하고, 이미 있는 DB 는 _migrate() 가 컬럼을 채워 준다.
"""
import os
import sqlite3
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


def connect():
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


def _migrate(conn):
    for table, col, ddl in _ADDED_COLUMNS:
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
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
        "INSERT INTO stores(id, name, tagline, address, phone, active, created_at, updated_at)"
        " VALUES(1,?,?,?,'',1,?,?)",
        (name, config.STORE.get("tagline") or "", config.STORE.get("address") or "", ts, ts))


def init():
    """스키마 생성 + 비어 있으면 기본 데이터를 넣는다."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        if conn.execute("SELECT COUNT(*) c FROM menu_items WHERE store_id=1").fetchone()["c"] == 0:
            seed(conn)
        if conn.execute("SELECT COUNT(*) c FROM dining_tables WHERE store_id=1").fetchone()["c"] == 0:
            seed_tables(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('rev','1') ON CONFLICT(key) DO NOTHING"
        )
        conn.commit()
    finally:
        conn.close()


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
