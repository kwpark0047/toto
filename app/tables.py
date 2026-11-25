"""테이블 모듈.

책임: 매장의 테이블(번호·이름·좌석·순서·사용 여부)을 등록·수정하고,
고객 접속 주소에 쓰는 고유 코드와 QR 주소를 만든다.

주소 규칙: 코드는 테이블을 만들 때 자동으로 붙는 문자열(`/t/<코드>`).
처음 깔리는 1~8번 테이블은 코드가 "1"~"8" 이므로 기존 `/t/1`~`/t/8` 주소가 그대로 동작한다.
주문의 table_no 에는 테이블 id 가 들어간다(기본 테이블은 id 와 코드가 1~8로 같다).

다점포: 테이블은 매장별로 나뉜다(store_id). 목록·수정은 지금 매장(stores.current()) 안에서만 일어나고,
고객 주소(/t/<코드>)는 코드로 매장을 찾아야 하므로 by_code() 만 전체에서 찾는다.
"""
from . import stores, store

DEFAULT_SEATS = 4


def _row(r):
    return {
        "id": r["id"], "storeId": r["store_id"] if "store_id" in r.keys() else 1,
        "code": r["code"], "label": r["label"], "seats": r["seats"],
        "sort": r["sort"], "active": bool(r["active"]), "url": f"/t/{r['code']}",
    }


def list_tables(include_inactive=True):
    sql = "SELECT * FROM dining_tables WHERE store_id=?"
    if not include_inactive:
        sql += " AND active=1"
    sql += " ORDER BY sort, id"
    with store.read() as conn:
        return [_row(r) for r in conn.execute(sql, (stores.current(),)).fetchall()]


def active_tables():
    return list_tables(include_inactive=False)


def get(table_id):
    """지금 매장의 테이블. 다른 매장 테이블이면 찾을 수 없음."""
    with store.read() as conn:
        r = conn.execute("SELECT * FROM dining_tables WHERE id=? AND store_id=?",
                         (table_id, stores.current())).fetchone()
        if not r:
            raise LookupError("테이블을 찾을 수 없습니다")
        return _row(r)


def get_any(table_id):
    """매장을 가리지 않고 테이블을 찾는다(공개 주문이 코드/번호로 매장을 알아낼 때)."""
    with store.read() as conn:
        r = conn.execute("SELECT * FROM dining_tables WHERE id=?", (table_id,)).fetchone()
        if not r:
            raise LookupError("테이블을 찾을 수 없습니다")
        return _row(r)


def by_code(code):
    """고객 주소 /t/<코드> → 테이블.

    기본 테이블 코드는 매장마다 1,2,3… 으로 같을 수 있으므로, 지금 매장(?store= 또는 세션)
    안에서 먼저 찾는다. 그 매장에 없고 전체에서 하나뿐일 때만 다른 매장 테이블로 인정한다.
    """
    with store.read() as conn:
        r = conn.execute(
            "SELECT * FROM dining_tables WHERE code=? AND store_id=? ORDER BY id LIMIT 1",
            (str(code), stores.current())).fetchone()
        if not r:
            rows = conn.execute("SELECT * FROM dining_tables WHERE code=?", (str(code),)).fetchall()
            if len(rows) == 1:
                r = rows[0]
        return _row(r) if r else None


def label_map():
    """테이블 id → 이름. 주문 id 는 전역이라 매장을 가리지 않고 찾는다(이름은 민감하지 않다)."""
    with store.read() as conn:
        return {r["id"]: r["label"] for r in conn.execute(
            "SELECT id, label FROM dining_tables").fetchall()}


def _check_label(conn, label, exclude_id=None):
    label = (label or "").strip()
    if not label:
        raise ValueError("테이블 이름을 넣어 주세요 (예: 1번, 창가, 룸1)")
    if len(label) > 20:
        raise ValueError("테이블 이름은 20자 이내로 넣어 주세요")
    sql = "SELECT id FROM dining_tables WHERE label=? COLLATE NOCASE AND store_id=?"
    params = [label, stores.current()]
    if exclude_id:
        sql += " AND id<>?"
        params.append(exclude_id)
    if conn.execute(sql, params).fetchone():
        raise ValueError(f"'{label}' 이름의 테이블이 이미 있습니다")
    return label


def create(label, seats=0, active=True):
    try:
        seats = max(0, min(50, int(seats or 0)))
    except (TypeError, ValueError):
        raise ValueError("좌석 수는 숫자로 넣어 주세요")
    ts = store.now()
    sid = stores.current()
    with store.tx() as conn:
        clean = _check_label(conn, label)
        nxt = (conn.execute("SELECT COALESCE(MAX(sort),0) m FROM dining_tables WHERE store_id=?",
                            (sid,)).fetchone()["m"]) + 1
        cur = conn.execute(
            "INSERT INTO dining_tables(store_id, code, label, seats, sort, active, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (sid, f"tmp-{ts}-{sid}", clean, seats, nxt, 1 if active else 0, ts, ts),
        )
        table_id = cur.lastrowid
        conn.execute("UPDATE dining_tables SET code=? WHERE id=?", (str(table_id), table_id))
        store.bump(conn)
    return get(table_id)


def update(table_id, data):
    ts = store.now()
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM dining_tables WHERE id=? AND store_id=?",
                         (table_id, stores.current())).fetchone()
        if not r:
            raise LookupError("테이블을 찾을 수 없습니다")
        sets, params = [], []
        if "label" in data:
            sets.append("label=?")
            params.append(_check_label(conn, data.get("label"), exclude_id=table_id))
        if "seats" in data:
            try:
                seats = max(0, min(50, int(data.get("seats") or 0)))
            except (TypeError, ValueError):
                raise ValueError("좌석 수는 숫자로 넣어 주세요")
            sets.append("seats=?")
            params.append(seats)
        if "active" in data:
            sets.append("active=?")
            params.append(1 if data.get("active") else 0)
        if not sets:
            return get(table_id)
        sets.append("updated_at=?")
        params.append(ts)
        conn.execute(f"UPDATE dining_tables SET {','.join(sets)} WHERE id=?", (*params, table_id))
        store.bump(conn)
    return get(table_id)


def move(table_id, direction="up"):
    with store.tx() as conn:
        rows = conn.execute("SELECT * FROM dining_tables WHERE store_id=? ORDER BY sort, id",
                            (stores.current(),)).fetchall()
        ids = [r["id"] for r in rows]
        if table_id not in ids:
            raise LookupError("테이블을 찾을 수 없습니다")
        i = ids.index(table_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, tid in enumerate(ids, start=1):
                conn.execute("UPDATE dining_tables SET sort=? WHERE id=?", (pos, tid))
            store.bump(conn)
    return list_tables()


def delete(table_id):
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM dining_tables WHERE id=? AND store_id=?",
                         (table_id, stores.current())).fetchone()
        if not r:
            raise LookupError("테이블을 찾을 수 없습니다")
        used = conn.execute("SELECT COUNT(*) c FROM orders WHERE table_no=?", (table_id,)).fetchone()["c"]
        if used:
            raise ValueError(
                f"이 테이블에는 주문 이력이 {used}건 있어 삭제할 수 없습니다. 대신 '비활성'으로 바꿔 주세요")
        conn.execute("DELETE FROM dining_tables WHERE id=?", (table_id,))
        store.bump(conn)
    return True


def ensure_count(count):
    """가입 직후 '테이블 몇 개'에 맞춰 테이블 수를 맞춘다(부족하면 만들고, 남으면 비활성)."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return list_tables()
    count = max(1, min(50, count))
    rows = list_tables()
    if len(rows) < count:
        for i in range(len(rows) + 1, count + 1):
            create(f"{i}번", DEFAULT_SEATS)
    elif len(rows) > count:
        for t in reversed(rows[count:]):
            with store.read() as conn:
                used = conn.execute("SELECT COUNT(*) c FROM orders WHERE table_no=?", (t["id"],)).fetchone()["c"]
            if not used:
                update(t["id"], {"active": False})
    return list_tables()


def stats_for_admin():
    """설정 화면·목록에 보여 줄 요약(지금 매장)."""
    tables = list_tables()
    with store.read() as conn:
        used = {r["table_no"]: r["c"] for r in conn.execute(
            "SELECT table_no, COUNT(*) c FROM orders WHERE store_id=? GROUP BY table_no",
            (stores.current(),)).fetchall()}
    for t in tables:
        t["orderCount"] = used.get(t["id"], 0)
    return {
        "tables": tables,
        "activeCount": len([t for t in tables if t["active"]]),
        "inactiveCount": len([t for t in tables if not t["active"]]),
        "seatsTotal": sum(t["seats"] for t in tables if t["active"]),
    }
