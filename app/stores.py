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


# ============================================================================
# 다수 매장 통합 운영 — 메뉴 복사 · 직원 이동 · 전 매장 합계
# ============================================================================

def copy_menu(from_store, to_store, item_ids=None, on_duplicate="skip"):
    """한 매장의 메뉴를 다른 매장으로 복사한다.

    item_ids 를 주면 그 메뉴만, 없으면 전체. 같은 이름의 메뉴가 대상 매장에 있으면
    on_duplicate="skip"(건너뛰기) 또는 "overwrite"(가격·설명·옵션·사진·추천까지 덮어쓰기).
    """
    try:
        src = _clean_sid(from_store)
        dst = _clean_sid(to_store)
    except (TypeError, ValueError):
        raise ValueError("매장을 골라 주세요")
    if src == dst:
        raise ValueError("같은 매장으로는 복사할 수 없습니다")
    for sid in (src, dst):
        if not exists(sid):
            raise LookupError("매장을 찾을 수 없습니다")
    on_duplicate = (on_duplicate or "skip").strip().lower()
    if on_duplicate not in ("skip", "overwrite"):
        raise ValueError("중복 메뉴 처리는 skip(건너뛰기) 또는 overwrite(덮어쓰기)로 정해 주세요")

    wanted = None
    if item_ids:
        try:
            wanted = {int(x) for x in item_ids}
        except (TypeError, ValueError):
            raise ValueError("복사할 메뉴를 다시 골라 주세요")

    with store.read() as conn:
        cats = conn.execute(
            "SELECT * FROM categories WHERE store_id=? ORDER BY sort, id", (src,)).fetchall()
        items = conn.execute(
            "SELECT * FROM menu_items WHERE store_id=? ORDER BY sort, id", (src,)).fetchall()
        dst_cats = {r["name"].strip(): r["id"] for r in conn.execute(
            "SELECT id, name FROM categories WHERE store_id=?", (dst,)).fetchall()}
        dst_items = {r["name"].strip(): r for r in conn.execute(
            "SELECT id, name FROM menu_items WHERE store_id=?", (dst,)).fetchall()}
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort), 0) s FROM menu_items WHERE store_id=?", (dst,)
        ).fetchone()["s"]
        max_cat_sort = conn.execute(
            "SELECT COALESCE(MAX(sort), 0) s FROM categories WHERE store_id=?", (dst,)
        ).fetchone()["s"]

    chosen = [i for i in items if wanted is None or i["id"] in wanted]
    if wanted is not None and not chosen:
        raise ValueError("복사할 메뉴가 없습니다")

    used_cat_ids = {i["category_id"] for i in chosen}
    cat_map = {}
    created_cats = 0
    created = updated = skipped = 0
    ts = store.now()
    with store.tx() as conn:
        for c in cats:
            if c["id"] not in used_cat_ids:
                continue
            name = c["name"].strip()
            if name in dst_cats:
                cat_map[c["id"]] = dst_cats[name]
                continue
            max_cat_sort += 1
            cur = conn.execute(
                "INSERT INTO categories(store_id, name, sort, created_at) VALUES(?,?,?,?)",
                (dst, name, max_cat_sort, ts))
            cat_map[c["id"]] = cur.lastrowid
            dst_cats[name] = cur.lastrowid
            created_cats += 1

        for i in chosen:
            name = i["name"].strip()
            cat_id = cat_map.get(i["category_id"]) or dst_cats.get(
                next((c["name"].strip() for c in cats if c["id"] == i["category_id"]), ""), 0)
            fields = (cat_id, i["price"], i["description"], i["image"], i["options"],
                      i["soldout"], i["featured"], i["featured_note"], i["origin"],
                      i["allergens"], i["spice"], i["i18n"], ts)
            if name in dst_items:
                if on_duplicate == "skip":
                    skipped += 1
                    continue
                conn.execute(
                    "UPDATE menu_items SET category_id=?, price=?, description=?, image=?,"
                    " options=?, soldout=?, featured=?, featured_note=?, origin=?, allergens=?,"
                    " spice=?, i18n=?, updated_at=? WHERE store_id=? AND name=?",
                    (*fields, dst, name))
                updated += 1
                continue
            max_sort += 1
            cur = conn.execute(
                "INSERT INTO menu_items(store_id, category_id, name, price, description, image,"
                " options, soldout, sort, featured, featured_sort, featured_note, origin,"
                " allergens, spice, i18n, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (dst, cat_id, name, i["price"], i["description"], i["image"], i["options"],
                 i["soldout"], max_sort, i["featured"], i["featured_sort"], i["featured_note"],
                 i["origin"], i["allergens"], i["spice"], i["i18n"], ts, ts))
            dst_items[name] = {"id": cur.lastrowid, "name": name}
            created += 1
        store.bump(conn)
    return {"fromStore": src, "toStore": dst, "onDuplicate": on_duplicate,
            "selected": len(chosen), "created": created, "updated": updated,
            "skipped": skipped, "categoriesCreated": created_cats}


def transfer_staff(staff_id, to_store, actor=None, note=""):
    """직원을 다른 매장으로 발령한다. 세션의 매장도 함께 옮기고 이력을 남긴다."""
    try:
        staff_id = int(staff_id)
        dst = _clean_sid(to_store)
    except (TypeError, ValueError):
        raise ValueError("직원과 옮길 매장을 골라 주세요")
    if not exists(dst):
        raise LookupError("매장을 찾을 수 없습니다")
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
        target = conn.execute("SELECT id, name, active FROM stores WHERE id=?", (dst,)).fetchone()
    if not row:
        raise LookupError("직원을 찾을 수 없습니다")
    if not target or not target["active"]:
        raise ValueError("사용하지 않는 매장으로는 옮길 수 없습니다")
    src = row["store_id"] if "store_id" in row.keys() else 1
    if src == dst:
        raise ValueError("이미 그 매장에서 일하고 있습니다")
    ts = store.now()
    with store.tx() as conn:
        conn.execute("UPDATE staff SET store_id=?, updated_at=? WHERE id=?", (dst, ts, staff_id))
        # 로그인 중인 기기도 새 매장을 보게 한다(권한·역할은 그대로).
        conn.execute("UPDATE staff_sessions SET active_store=? WHERE staff_id=?", (dst, staff_id))
        conn.execute(
            "INSERT INTO staff_transfers(staff_id, from_store, to_store, actor_id, note, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (staff_id, src, dst, (actor or {}).get("id"), (note or "").strip()[:200], ts))
        store.bump(conn)
    return {"staff": {"id": staff_id, "name": row["name"], "username": row["username"],
                      "role": row["role"]},
            "fromStore": {"id": src}, "toStore": {"id": dst, "name": target["name"]},
            "movedAt": ts}


def transfers(staff_id=None, limit=50):
    sql = ("SELECT t.*, s.name AS staff_name, a.name AS from_name, b.name AS to_name"
           " FROM staff_transfers t LEFT JOIN staff s ON s.id=t.staff_id"
           " LEFT JOIN stores a ON a.id=t.from_store LEFT JOIN stores b ON b.id=t.to_store")
    params = []
    if staff_id:
        sql += " WHERE t.staff_id=?"
        params.append(int(staff_id))
    sql += " ORDER BY t.id DESC LIMIT ?"
    params.append(int(limit))
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"transfers": [{
        "id": r["id"], "staffId": r["staff_id"], "staffName": r["staff_name"] or "",
        "fromStore": r["from_store"], "fromName": r["from_name"] or "",
        "toStore": r["to_store"], "toName": r["to_name"] or "",
        "note": r["note"], "createdAt": r["created_at"],
    } for r in rows]}


def all_staff():
    """모든 매장의 직원 목록(이동 화면용). 로그인 없이 노출되지 않도록 API에서 권한 검사."""
    with store.read() as conn:
        rows = conn.execute(
            "SELECT s.id, s.username, s.name, s.role, s.active, s.store_id, st.name AS store_name"
            " FROM staff s LEFT JOIN stores st ON st.id=s.store_id ORDER BY st.name, s.name, s.id"
        ).fetchall()
    return {"staff": [{
        "id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"],
        "active": bool(r["active"]), "storeId": r["store_id"] or 1,
        "storeName": r["store_name"] or "",
    } for r in rows]}


def store_menu(store_id):
    """다른 매장의 메뉴 목록(복사 화면용). 이름·가격·카테고리만."""
    from . import catalog
    sid = _clean_sid(store_id)
    if not exists(sid):
        raise LookupError("매장을 찾을 수 없습니다")
    with use(sid):
        cats = catalog.categories()
        items = catalog.items()
    return {"storeId": sid,
            "categories": [{"id": c["id"], "name": c["name"]} for c in cats],
            "items": [{"id": i["id"], "name": i["name"], "price": i["price"],
                       "categoryId": i["categoryId"], "categoryName": i.get("category") or ""}
                      for i in items]}


def summary(date=None):
    """소유·운영 중인 모든 매장의 매출 합계·주문 건수·비중."""
    from . import stats
    date = date or store.today()
    month_start = date[:7] + "-01"
    rows = []
    for s in list_stores(include_inactive=False):
        with use(s["id"]):
            today = stats.summary(date)
            month = stats.period(month_start, date)
            with store.read() as conn:
                alltime = conn.execute(
                    "SELECT COALESCE(SUM(total),0) paid, COUNT(*) c FROM orders"
                    " WHERE store_id=? AND payment_status='PAID'", (s["id"],)).fetchone()
        rows.append({
            "id": s["id"], "name": s["name"], "isCurrent": s["id"] == current(),
            "todayPaid": today["paidAmount"], "todayOrders": today["orderCount"],
            "monthPaid": month["totals"]["paidAmount"], "monthOrders": month["totals"]["orderCount"],
            "totalPaid": alltime["paid"], "totalOrders": alltime["c"],
        })
    today_total = sum(r["todayPaid"] for r in rows)
    month_total = sum(r["monthPaid"] for r in rows)
    total_all = sum(r["totalPaid"] for r in rows)
    for r in rows:
        r["todayShare"] = round((r["todayPaid"] / today_total * 100), 1) if today_total else 0.0
        r["monthShare"] = round((r["monthPaid"] / month_total * 100), 1) if month_total else 0.0
    return {
        "date": date, "month": date[:7], "stores": rows,
        "totals": {
            "todayPaid": today_total, "todayOrders": sum(r["todayOrders"] for r in rows),
            "monthPaid": month_total, "monthOrders": sum(r["monthOrders"] for r in rows),
            "totalPaid": total_all, "totalOrders": sum(r["totalOrders"] for r in rows),
            "storeCount": len(rows),
        },
    }
