#!/usr/bin/env python3
"""옛 DB(다점포·권한 컬럼이 없던 버전)를 그대로 열 수 있는지 확인하는 개발용 점검.

실행:
    python3 tools/migration_check.py

임시 DB를 만들어 데이터를 넣고, 새 컬럼·새 테이블만 걷어내 '옛 DB'로 만든 뒤
store.init() 이 다시 컬럼을 채우고 기존 데이터를 그대로 쓰는지 본다.
"""
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = "/workspace/.tmp-test"
DB = os.path.join(WORK, "migrate.db")
OLD = os.path.join(WORK, "migrate-old.db")

DROP_COLUMNS = [
    ("categories", "store_id"), ("menu_items", "store_id"), ("orders", "store_id"),
    ("customers", "store_id"), ("dining_tables", "store_id"), ("staff", "store_id"),
    ("attendance", "store_id"), ("waiting_tickets", "store_id"), ("service_calls", "store_id"),
    ("notifier_log", "store_id"),
    ("staff", "permissions"), ("staff", "pay_type"), ("staff", "hourly_wage"),
    ("staff", "monthly_salary"), ("staff", "must_change"),
    ("staff_sessions", "active_store"), ("orders", "served_at"),
]
DROP_TABLES = ["stores", "ingredients", "recipes", "ingredient_logs", "reservations",
               "reviews", "staff_schedules"]

failures = []


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ❌ ") + name + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main():
    os.makedirs(WORK, exist_ok=True)
    for path in (DB, OLD):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
    os.environ["MENU_DB"] = DB
    from app import catalog, customers, orders, staff, store, tables
    store.init()
    staff.signup("맛집", "owner", "mangjip1234", 8)
    item = catalog.items()[0]
    order = orders.create(1, [{"itemId": item["id"], "qty": 2}],
                          {"name": "옛손님", "phone": "010-1234-5678", "consent": True})
    staff.create({"name": "옛직원", "username": "oldstaff", "password": "oldpw1234", "role": "counter"})
    before = {
        "items": len(catalog.items()),
        "orders": len(orders.list_orders()),
        "customers": len(customers.list_customers()),
        "staff": len(staff.list_staff()["staff"]),
        "tables": len(tables.list_tables()),
        "name": catalog.items()[0]["name"],
    }

    # 옛 DB 흉내: 새 컬럼·새 테이블 걷어내기
    shutil.copy(DB, OLD)
    conn = sqlite3.connect(OLD)
    for table in DROP_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    for table, column in DROP_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    conn.execute("DROP INDEX IF EXISTS idx_customers_store_phone")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)"
                 " WHERE phone <> ''")
    conn.commit()
    conn.close()

    os.environ["MENU_DB"] = OLD
    # 모듈이 config.DB_PATH 를 이미 읽었으므로 다시 불러온다
    import importlib
    from app import config
    importlib.reload(config)
    for mod in (store, catalog, customers, orders, staff, tables):
        importlib.reload(mod)
    store.init()

    after = {
        "items": len(catalog.items()),
        "orders": len(orders.list_orders()),
        "customers": len(customers.list_customers()),
        "staff": len(staff.list_staff()["staff"]),
        "tables": len(tables.list_tables()),
    }
    check("옛 DB를 새 코드로 열 수 있음", True)
    for key, value in after.items():
        check(f"기존 데이터 유지: {key} {value}", value == before[key], (value, before[key]))
    check("기본 매장(1)이 만들어짐", bool(tables.list_tables()) and orders.list_orders())
    conn = sqlite3.connect(OLD)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
    check("store_id·served_at 컬럼이 다시 채워짐", {"store_id", "served_at"} <= cols, cols)
    row = conn.execute("SELECT store_id, served_at FROM orders LIMIT 1").fetchone()
    check("기존 주문은 기본 매장(1)으로 남음", row[0] == 1, row)
    name = conn.execute("SELECT name FROM stores WHERE id=1").fetchone()
    check("매장 이름이 설정값에서 복원됨", bool(name) and name[0] == "맛집", name)
    idx = [r[1] for r in conn.execute("PRAGMA index_list(customers)")]
    check("매장별 연락처 유일 인덱스", "idx_customers_store_phone" in idx, idx)
    dup = 0
    try:
        conn.execute("INSERT INTO customers(store_id, name, phone, birthday, grade, consent, memo,"
                     " created_at, updated_at) VALUES(1,'중복','010-1234-5678','','',0,'','x','x')")
        conn.commit()
    except sqlite3.IntegrityError:
        dup = 1
    check("같은 매장 같은 번호는 중복 저장 차단", dup == 1)
    owner_id = conn.execute("SELECT owner_id FROM stores WHERE id=1").fetchone()[0]
    account_id = conn.execute(
        "SELECT account_id FROM staff WHERE role='admin' ORDER BY id LIMIT 1").fetchone()[0]
    listed = conn.execute("SELECT listed FROM stores WHERE id=1").fetchone()[0]
    mixed = conn.execute("SELECT COUNT(*) FROM staff WHERE account_id<>?", (account_id,)).fetchone()[0]
    conn.close()
    check("기존 매장이 첫 사장님 계정 소유로 이관", owner_id == account_id and owner_id > 0,
          (owner_id, account_id))
    check("기존 직원이 같은 사업자 계정으로 묶임", mixed == 0, mixed)
    check("기존 매장은 공개 목록 유지(호환)", listed == 1, listed)
    # 새 계정은 옛 매장을 보지 못해야 한다
    from app import stores as stores_mod
    u2, _t2, _e2, _s2 = staff.signup("새 가게", "newbie29", "newpass1234", 2)
    with stores_mod.account_scope(u2["accountId"]):
        seen = [s["id"] for s in stores_mod.list_stores()]
    check("새 계정은 기존 매장을 보지 못함(계정 격리)", seen == [u2["storeId"]], seen)
    print()
    if failures:
        print("문제:", *failures, sep="\n - ")
        sys.exit(1)
    print("옛 DB 마이그레이션 점검 통과")


if __name__ == "__main__":
    main()
