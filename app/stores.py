"""매장(다점포) 모듈.

책임:
- 매장 목록·추가·수정(상호·간단 정보)
- '지금 어느 매장으로 일하고 있는지'를 요청 단위로 들고 있는 것 (contextvars)

다른 모듈은 `stores.current()` 로 매장 id 를 읽어 자기 테이블의 `store_id` 조건에 쓴다.
매장 id 1 은 이전 버전의 기본 매장이며, 기존 데이터는 모두 store_id=1 로 남아 그대로 유지된다.

주의: 매장을 바꾸는 것은 화면(세션) 단위다. 같은 서버에서 두 사람이 동시에 다른 매장을 봐도
서로 섞이지 않도록 contextvar 를 쓴다(스레드마다 독립).
"""
import contextvars

from . import store

_current = contextvars.ContextVar("menu_store_id", default=1)


def _clean_sid(sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return 1
    return sid if sid > 0 else 1


def current():
    try:
        return int(_current.get() or 1)
    except (TypeError, ValueError):
        return 1


class use:
    """with stores.use(sid): … 블록 안에서만 매장을 바꾼다."""

    def __init__(self, sid):
        self.sid = _clean_sid(sid)
        self.token = None

    def __enter__(self):
        self.token = _current.set(self.sid)
        return self.sid

    def __exit__(self, *a):
        _current.reset(self.token)
        return False


def _row(r):
    return {
        "id": r["id"], "name": r["name"], "tagline": r["tagline"] or "",
        "address": r["address"] or "", "phone": r["phone"] or "",
        "active": bool(r["active"]), "createdAt": r["created_at"],
        "isCurrent": r["id"] == current(),
    }


def list_stores(include_inactive=True):
    sql = "SELECT * FROM stores"
    if not include_inactive:
        sql += " WHERE active=1"
    sql += " ORDER BY id"
    with store.read() as conn:
        return [_row(r) for r in conn.execute(sql).fetchall()]


def get(store_id=None):
    sid = _clean_sid(store_id if store_id is not None else current())
    with store.read() as conn:
        r = conn.execute("SELECT * FROM stores WHERE id=?", (sid,)).fetchone()
        if not r:
            raise LookupError("매장을 찾을 수 없습니다")
        return _row(r)


def exists(store_id):
    try:
        sid = int(store_id)
    except (TypeError, ValueError):
        return False
    with store.read() as conn:
        return bool(conn.execute("SELECT 1 FROM stores WHERE id=?", (sid,)).fetchone())


def default_store_id():
    with store.read() as conn:
        r = conn.execute("SELECT id FROM stores WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        return r["id"] if r else 1


def _copy_menu(conn, from_sid, to_sid):
    """다른 매장의 메뉴를 그대로 복사한다(사진 경로·옵션·번역 포함)."""
    cats = conn.execute("SELECT * FROM categories WHERE store_id=? ORDER BY sort, id",
                        (from_sid,)).fetchall()
    mapping = {}
    for c in cats:
        cur = conn.execute(
            "INSERT INTO categories(store_id, name, sort, created_at) VALUES(?,?,?,?)",
            (to_sid, c["name"], c["sort"], store.now()))
        mapping[c["id"]] = cur.lastrowid
    for m in conn.execute("SELECT * FROM menu_items WHERE store_id=? ORDER BY id", (from_sid,)).fetchall():
        conn.execute(
            "INSERT INTO menu_items(store_id, category_id, name, price, description, image, options,"
            " soldout, sort, featured, featured_sort, featured_note, origin, allergens, spice, i18n,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (to_sid, mapping.get(m["category_id"], 0), m["name"], m["price"], m["description"],
             m["image"], m["options"], m["soldout"], m["sort"], m["featured"], m["featured_sort"],
             m["featured_note"], m["origin"], m["allergens"], m["spice"], m["i18n"],
             store.now(), store.now()))
    return {"categories": len(mapping)}


def create(name, table_count=8, copy_from=None):
    """매장을 추가한다. 메뉴는 기본 메뉴를 새로 깔거나(기본), 다른 매장 메뉴를 복사한다."""
    from . import settings, tables
    name = (name or "").strip()
    if not name:
        raise ValueError("매장 이름을 넣어 주세요")
    if len(name) > 40:
        raise ValueError("매장 이름은 40자 이내로 넣어 주세요")
    try:
        table_count = int(table_count or 0)
    except (TypeError, ValueError):
        table_count = 0
    ts = store.now()
    with store.tx() as conn:
        dup = conn.execute("SELECT id FROM stores WHERE name=?", (name,)).fetchone()
        if dup:
            raise ValueError(f"'{name}' 이름의 매장이 이미 있습니다")
        cur = conn.execute(
            "INSERT INTO stores(name, tagline, address, phone, active, created_at, updated_at)"
            " VALUES(?,'','','',1,?,?)", (name, ts, ts))
        sid = cur.lastrowid
        if copy_from:
            _copy_menu(conn, _clean_sid(copy_from), sid)
        else:
            store.seed(conn, store_id=sid)
        store.bump(conn)
    with use(sid):
        settings.save({"storeName": name})
        if table_count:
            tables.ensure_count(table_count)
    return get(sid)


def update(store_id, data):
    sid = _clean_sid(store_id)
    sets, params = [], []
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("매장 이름을 넣어 주세요")
        with store.read() as conn:
            dup = conn.execute("SELECT id FROM stores WHERE name=? AND id<>?", (name, sid)).fetchone()
        if dup:
            raise ValueError(f"'{name}' 이름의 매장이 이미 있습니다")
        sets.append("name=?")
        params.append(name[:40])
    for key in ("tagline", "address", "phone"):
        if key in data:
            sets.append(f"{key}=?")
            params.append((data.get(key) or "").strip()[:120])
    if "active" in data:
        if not data.get("active") and sid == current():
            raise ValueError("지금 보고 있는 매장은 '사용 안 함'으로 바꿀 수 없습니다."
                             " 다른 매장으로 전환한 뒤 바꿔 주세요")
        sets.append("active=?")
        params.append(1 if data.get("active") else 0)
    if not sets:
        return get(sid)
    sets.append("updated_at=?")
    params.append(store.now())
    with store.tx() as conn:
        cur = conn.execute(f"UPDATE stores SET {','.join(sets)} WHERE id=?", (*params, sid))
        if cur.rowcount == 0:
            raise LookupError("매장을 찾을 수 없습니다")
        store.bump(conn)
    if "name" in data:
        from . import settings
        with use(sid):
            settings.save({"storeName": (data.get("name") or "").strip()[:40]})
    return get(sid)


def comparison(date=None):
    """매장별 요약 비교(오늘 매출·이번 달 매출·주문·메뉴·직원·테이블)."""
    from . import catalog, staff, stats, tables
    date = date or store.today()
    month = date[:7]
    rows = []
    for s in list_stores():
        with use(s["id"]):
            today = stats.summary(date)
            month_stats = stats.period(month + "-01", date)
            rows.append({
                **s,
                "todayPaid": today["paidAmount"],
                "todayOrders": today["orderCount"],
                "todayUnpaid": today["unpaidAmount"],
                "monthPaid": month_stats["totals"]["paidAmount"],
                "monthOrders": month_stats["totals"]["orderCount"],
                "menuCount": len(catalog.items()),
                "activeMenuCount": len([i for i in catalog.items() if not i["soldout"]]),
                "staffCount": len([x for x in staff.list_staff()["staff"] if x["active"]]),
                "tableCount": len([t for t in tables.list_tables() if t["active"]]),
            })
    return {"date": date, "month": month, "stores": rows,
            "totalPaid": sum(r["todayPaid"] for r in rows),
            "totalMonthPaid": sum(r["monthPaid"] for r in rows)}
