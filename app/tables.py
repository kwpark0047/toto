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
    keys = r.keys()
    return {
        "id": r["id"], "storeId": r["store_id"] if "store_id" in keys else 1,
        "code": r["code"], "label": r["label"], "seats": r["seats"],
        "sort": r["sort"], "active": bool(r["active"]), "url": f"/t/{r['code']}",
        "zoneId": (r["zone_id"] if "zone_id" in keys else 0) or 0,
        "zone": (r["zone_name"] if "zone_name" in keys else "") or "",
    }


def list_tables(include_inactive=True):
    sql = ("SELECT t.*, z.name AS zone_name FROM dining_tables t"
           " LEFT JOIN table_zones z ON z.id=t.zone_id AND z.store_id=t.store_id"
           " WHERE t.store_id=?")
    if not include_inactive:
        sql += " AND t.active=1"
    sql += " ORDER BY t.sort, t.id"
    with store.read() as conn:
        return [_row(r) for r in conn.execute(sql, (stores.current(),)).fetchall()]


# ---------------------------------------------------------------- 구역

def zones(include_inactive=False):
    sql = "SELECT * FROM table_zones WHERE store_id=?"
    if not include_inactive:
        sql += " AND active=1"
    sql += " ORDER BY sort, id"
    with store.read() as conn:
        rows = conn.execute(sql, (stores.current(),)).fetchall()
        counts = {r["zone_id"]: r for r in conn.execute(
            "SELECT zone_id, COUNT(*) c, SUM(active) a FROM dining_tables WHERE store_id=?"
            " GROUP BY zone_id", (stores.current(),)).fetchall()}
    out = []
    for r in rows:
        c = counts.get(r["id"]) or {"c": 0, "a": 0}
        out.append({"id": r["id"], "name": r["name"], "sort": r["sort"],
                    "active": bool(r["active"]), "tableCount": c["c"] or 0,
                    "activeTableCount": c["a"] or 0})
    return out


def _zone_name(conn, name, exclude_id=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("구역 이름을 넣어 주세요 (예: 홀, 창가, 테라스)")
    if len(name) > 20:
        raise ValueError("구역 이름은 20자 이내로 넣어 주세요")
    sql = "SELECT id FROM table_zones WHERE name=? COLLATE NOCASE AND store_id=?"
    params = [name, stores.current()]
    if exclude_id:
        sql += " AND id<>?"
        params.append(exclude_id)
    if conn.execute(sql, params).fetchone():
        raise ValueError(f"'{name}' 구역이 이미 있습니다")
    return name


def create_zone(name):
    with store.tx() as conn:
        clean = _zone_name(conn, name)
        nxt = (conn.execute("SELECT COALESCE(MAX(sort),0) m FROM table_zones WHERE store_id=?",
                            (stores.current(),)).fetchone()["m"]) + 1
        cur = conn.execute(
            "INSERT INTO table_zones(store_id, name, sort, active, created_at) VALUES(?,?,?,1,?)",
            (stores.current(), clean, nxt, store.now()))
        store.bump(conn)
        zid = cur.lastrowid
    return next(z for z in zones(include_inactive=True) if z["id"] == zid)


def update_zone(zone_id, data):
    data = data or {}
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM table_zones WHERE id=? AND store_id=?",
                         (zone_id, stores.current())).fetchone()
        if not r:
            raise LookupError("구역을 찾을 수 없습니다")
        sets, params = [], []
        if "name" in data:
            sets.append("name=?")
            params.append(_zone_name(conn, data.get("name"), exclude_id=zone_id))
        if "active" in data:
            sets.append("active=?")
            params.append(1 if data.get("active") else 0)
        if sets:
            conn.execute(f"UPDATE table_zones SET {','.join(sets)} WHERE id=?", (*params, zone_id))
            store.bump(conn)
    return next(z for z in zones(include_inactive=True) if z["id"] == zone_id)


def delete_zone(zone_id):
    """빈 구역만 지운다. 테이블이 있으면 다른 구역으로 옮긴 뒤 지운다."""
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM table_zones WHERE id=? AND store_id=?",
                         (zone_id, stores.current())).fetchone()
        if not r:
            raise LookupError("구역을 찾을 수 없습니다")
        used = conn.execute("SELECT COUNT(*) c FROM dining_tables WHERE zone_id=? AND store_id=?",
                            (zone_id, stores.current())).fetchone()["c"]
        if used:
            other = conn.execute("SELECT id FROM table_zones WHERE store_id=? AND id<>?"
                                  " ORDER BY sort, id LIMIT 1", (stores.current(), zone_id)).fetchone()
            if not other:
                raise ValueError("테이블이 있는 마지막 구역은 지울 수 없습니다. 테이블을 먼저 옮겨 주세요")
            conn.execute("UPDATE dining_tables SET zone_id=? WHERE zone_id=? AND store_id=?",
                         (other["id"], zone_id, stores.current()))
        conn.execute("DELETE FROM table_zones WHERE id=?", (zone_id,))
        store.bump(conn)
    return {"deleted": zone_id, "movedTables": used}


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


def create(label, seats=0, active=True, zone_id=None):
    try:
        seats = max(0, min(50, int(seats or 0)))
    except (TypeError, ValueError):
        raise ValueError("좌석 수는 숫자로 넣어 주세요")
    ts = store.now()
    sid = stores.current()
    with store.tx() as conn:
        if zone_id is None:
            zone_id = 0
        try:
            zone_id = int(zone_id or 0)
        except (TypeError, ValueError):
            zone_id = 0
        if zone_id:
            if not conn.execute("SELECT 1 FROM table_zones WHERE id=? AND store_id=?",
                                (zone_id, sid)).fetchone():
                raise LookupError("구역을 찾을 수 없습니다")
        else:
            z = conn.execute("SELECT id FROM table_zones WHERE store_id=? ORDER BY sort, id LIMIT 1",
                             (sid,)).fetchone()
            if z:
                zone_id = z["id"]
            else:
                zone_id = conn.execute(
                    "INSERT INTO table_zones(store_id, name, sort, active, created_at)"
                    " VALUES(?,?,1,1,?)", (sid, "홀", ts)).lastrowid
        clean = _check_label(conn, label)
        nxt = (conn.execute("SELECT COALESCE(MAX(sort),0) m FROM dining_tables WHERE store_id=?",
                            (sid,)).fetchone()["m"]) + 1
        cur = conn.execute(
            "INSERT INTO dining_tables(store_id, code, label, seats, sort, active, zone_id, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, f"tmp-{ts}-{sid}", clean, seats, nxt, 1 if active else 0, zone_id, ts, ts),
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
        if "zoneId" in data:
            try:
                zid = int(data.get("zoneId") or 0)
            except (TypeError, ValueError):
                raise ValueError("구역을 다시 골라 주세요")
            if not conn.execute("SELECT 1 FROM table_zones WHERE id=? AND store_id=?",
                                (zid, stores.current())).fetchone():
                raise LookupError("구역을 찾을 수 없습니다")
            sets.append("zone_id=?")
            params.append(zid)
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
        "zones": zones(include_inactive=True),
        "activeCount": len([t for t in tables if t["active"]]),
        "inactiveCount": len([t for t in tables if not t["active"]]),
        "seatsTotal": sum(t["seats"] for t in tables if t["active"]),
    }


def bulk_create(zone_id, prefix="테이블", count=1, seats=DEFAULT_SEATS, start=1):
    """구역에 테이블을 여러 개 한 번에 만든다(예: 창가1~창가6)."""
    try:
        count = int(count or 0)
        start = max(1, int(start or 1))
    except (TypeError, ValueError):
        raise ValueError("만들 테이블 수를 숫자로 넣어 주세요")
    if not (1 <= count <= 50):
        raise ValueError("한 번에 1~50개까지 만들 수 있습니다")
    prefix = (prefix or "테이블").strip()[:12]
    made = []
    for i in range(start, start + count):
        made.append(create(f"{prefix}{i}", seats, True, zone_id))
    return {"created": len(made), "tables": made}


def nfc_guide(base):
    """NFC 태그(NDEF URI)에 넣을 주소와 쓰기 안내. 태그에 적는 것은 URL 하나뿐이다."""
    from . import qrs
    out = []
    for t in list_tables(include_inactive=False):
        out.append({
            "tableId": t["id"], "label": t["label"], "code": t["code"],
            "url": qrs.nfc_table_url(base, t["code"]),
            "ndef": "URI 레코드(https) · MIME 없음 · 읽기 전용 권장",
        })
    return {
        "items": out,
        "guide": [
            "1. NFC Tools 같은 앱에서 'URI/URL 기록'을 고릅니다.",
            "2. 위 주소를 그대로 붙여 넣고 NTAG213 이상 태그에 씁니다.",
            "3. 태그를 테이블 스탠드 뒤쪽에 붙이고 손님 휴대폰으로 한 번 확인합니다.",
            "4. 주소에는 ?via=nfc 가 붙어 있어 QR과 NFC 유입을 따로 셀 수 있습니다.",
        ],
        "note": "아이폰은 화면을 켠 채 태그를 대면 열립니다. 태그가 잠겨 있으면 다시 쓸 수 없으니 읽기 전용으로 마무리하세요.",
    }
