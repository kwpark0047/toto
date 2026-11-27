"""매장 그룹 모듈.

책임: 사업자가 자기 매장을 브랜드·지역·직영/가맹으로 묶고, 그룹 단위로
통합 매출 보기, 메뉴 일괄 복사, 직원 이동, 그룹 기본 설정 적용을 한다.

그룹은 '같은 사업자 계정' 안에서만 만든다(owner_id). 다른 계정의 매장은
그룹에 넣을 수 없고, 그룹 id 를 알아도 조회되지 않는다.
"""
import json

from . import store, stores

KINDS = {"brand": "브랜드", "region": "지역", "direct": "직영", "franchise": "가맹"}
DEFAULT_SETTINGS = {
    "channelMode": "",          # "" 이면 매장별 설정 그대로
    "waiting": None,            # True/False/None(그대로)
    "community": None,
    "note": "",
}


def _clean_kind(value):
    kind = (value or "").strip() or "brand"
    if kind not in KINDS:
        raise ValueError("그룹 종류는 브랜드·지역·직영·가맹 중에서 골라 주세요")
    return kind


def _settings_obj(raw):
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        data = {}
    out = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        out.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return out


def _row(r, store_rows=None):
    return {
        "id": r["id"], "name": r["name"], "kind": r["kind"],
        "kindLabel": KINDS.get(r["kind"], r["kind"]),
        "memo": r["memo"] or "",
        "settings": _settings_obj(r["settings"]),
        "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "stores": store_rows or [],
    }


def owned(group_id):
    """지금 계정의 그룹인지."""
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return False
    aid = stores.account()
    with store.read() as conn:
        r = conn.execute("SELECT owner_id FROM store_groups WHERE id=?", (gid,)).fetchone()
    if not r:
        return False
    return not aid or r["owner_id"] in (0, aid)


def get(group_id):
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        raise ValueError("그룹을 골라 주세요")
    if not owned(gid):
        raise LookupError("매장 그룹을 찾을 수 없습니다")
    with store.read() as conn:
        r = conn.execute("SELECT * FROM store_groups WHERE id=?", (gid,)).fetchone()
        if not r:
            raise LookupError("매장 그룹을 찾을 수 없습니다")
        members = conn.execute(
            "SELECT id, name, active, group_id FROM stores WHERE group_id=? ORDER BY id", (gid,)
        ).fetchall()
    rows = [{"id": m["id"], "name": m["name"], "active": bool(m["active"])} for m in members]
    return _row(r, rows)


def list_groups():
    aid = stores.account()
    sql = "SELECT * FROM store_groups"
    params = []
    if aid:
        sql += " WHERE owner_id=?"
        params.append(aid)
    sql += " ORDER BY id"
    with store.read() as conn:
        groups = conn.execute(sql, params).fetchall()
        members = conn.execute(
            "SELECT id, name, active, group_id FROM stores" +
            (" WHERE owner_id=?" if aid else "") + " ORDER BY id",
            params,
        ).fetchall()
    by_group = {}
    for m in members:
        by_group.setdefault(m["group_id"] or 0, []).append(
            {"id": m["id"], "name": m["name"], "active": bool(m["active"])})
    return {"groups": [_row(g, by_group.get(g["id"], [])) for g in groups],
            "kinds": [{"code": k, "label": v} for k, v in KINDS.items()]}


def create(data):
    data = data or {}
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("그룹 이름을 넣어 주세요 (예: 운양동 직영)")
    if len(name) > 40:
        raise ValueError("그룹 이름은 40자 이내로 넣어 주세요")
    ts = store.now()
    with store.tx() as conn:
        dup = conn.execute("SELECT id FROM store_groups WHERE name=? AND owner_id=?",
                           (name, stores.account())).fetchone()
        if dup:
            raise ValueError(f"'{name}' 이름의 그룹이 이미 있습니다")
        cur = conn.execute(
            "INSERT INTO store_groups(owner_id, name, kind, memo, settings, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (stores.account(), name, _clean_kind(data.get("kind")),
             (data.get("memo") or "").strip()[:200],
             json.dumps(DEFAULT_SETTINGS, ensure_ascii=False), ts, ts),
        )
        gid = cur.lastrowid
        store.bump(conn)
    if data.get("storeIds"):
        assign(gid, data.get("storeIds"))
    return get(gid)


def update(group_id, data):
    gid = get(group_id)["id"]
    data = data or {}
    sets, params = [], []
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("그룹 이름을 넣어 주세요")
        with store.read() as conn:
            dup = conn.execute(
                "SELECT id FROM store_groups WHERE name=? AND id<>? AND owner_id=?",
                (name, gid, stores.account())).fetchone()
        if dup:
            raise ValueError(f"'{name}' 이름의 그룹이 이미 있습니다")
        sets.append("name=?")
        params.append(name[:40])
    if "kind" in data:
        sets.append("kind=?")
        params.append(_clean_kind(data.get("kind")))
    if "memo" in data:
        sets.append("memo=?")
        params.append((data.get("memo") or "").strip()[:200])
    if "settings" in data:
        incoming = data.get("settings") or {}
        if not isinstance(incoming, dict):
            raise ValueError("그룹 설정 형식이 올바르지 않습니다")
        cur = get(gid)["settings"]
        for key in DEFAULT_SETTINGS:
            if key not in incoming:
                continue
            val = incoming.get(key)
            if key == "channelMode" and val not in ("", "offline", "online", "both"):
                raise ValueError("그룹 운영 모드는 오프라인·온라인·통합 또는 '매장별 그대로'입니다")
            if key in ("waiting", "community") and val not in (None, True, False):
                raise ValueError("그룹 설정 값이 올바르지 않습니다")
            cur[key] = val
        sets.append("settings=?")
        params.append(json.dumps(cur, ensure_ascii=False))
    if sets:
        sets.append("updated_at=?")
        params.append(store.now())
        with store.tx() as conn:
            conn.execute(f"UPDATE store_groups SET {','.join(sets)} WHERE id=?", (*params, gid))
            store.bump(conn)
    if "storeIds" in data:
        assign(gid, data.get("storeIds"))
    return get(gid)


def assign(group_id, store_ids):
    """매장을 그룹에 넣는다. 넘긴 목록으로 그룹 소속을 맞춘다(빠진 매장은 그룹에서 나간다)."""
    gid = get(group_id)["id"]
    try:
        ids = [int(x) for x in (store_ids or [])]
    except (TypeError, ValueError):
        raise ValueError("매장을 다시 골라 주세요")
    mine = {s["id"] for s in stores.list_stores()}
    for sid in ids:
        if sid not in mine:
            raise LookupError("매장을 찾을 수 없습니다")
    with store.tx() as conn:
        rows = conn.execute("SELECT id FROM stores WHERE group_id=?", (gid,)).fetchall()
        for r in rows:
            if r["id"] not in ids:
                conn.execute("UPDATE stores SET group_id=0, updated_at=? WHERE id=?",
                             (store.now(), r["id"]))
        for sid in ids:
            conn.execute("UPDATE stores SET group_id=?, updated_at=? WHERE id=?",
                         (gid, store.now(), sid))
        store.bump(conn)
    return get(gid)


def delete(group_id):
    """그룹만 없앤다. 매장·메뉴·주문 데이터는 지우지 않고 그룹에서 빼기만 한다."""
    gid = get(group_id)["id"]
    with store.tx() as conn:
        conn.execute("UPDATE stores SET group_id=0 WHERE group_id=?", (gid,))
        conn.execute("DELETE FROM store_groups WHERE id=?", (gid,))
        store.bump(conn)
    return {"deleted": gid, "storesKept": True}


def summary(group_id, date=None):
    """그룹 통합 매출·주문·직원·테이블. 매장별 값은 stats/summary 를 그대로 쓴다."""
    from . import catalog, staff, stats, tables
    group = get(group_id)
    date = date or store.today()
    month = date[:7]
    rows = []
    for m in group["stores"]:
        with stores.use(m["id"]):
            today = stats.summary(date)
            month_stats = stats.period(month + "-01", date)
            rows.append({
                "id": m["id"], "name": m["name"], "active": m["active"],
                "todayPaid": today["paidAmount"], "todayOrders": today["orderCount"],
                "monthPaid": month_stats["totals"]["paidAmount"],
                "monthOrders": month_stats["totals"]["orderCount"],
                "menuCount": len(catalog.items()),
                "staffCount": len([x for x in staff.list_staff()["staff"] if x["active"]]),
                "tableCount": len([t for t in tables.list_tables() if t["active"]]),
            })
    total_paid = sum(r["todayPaid"] for r in rows)
    total_month = sum(r["monthPaid"] for r in rows)
    for r in rows:
        r["monthShare"] = round(r["monthPaid"] * 100.0 / total_month, 1) if total_month else 0
    return {"group": {"id": group["id"], "name": group["name"], "kind": group["kindLabel"]},
            "date": date, "month": month, "stores": rows,
            "totals": {"storeCount": len(rows), "todayPaid": total_paid,
                       "monthPaid": total_month,
                       "todayOrders": sum(r["todayOrders"] for r in rows)}}


def copy_menu(group_id, from_store, to_stores=None, on_duplicate="skip"):
    """그룹 안 매장의 메뉴를 같은 그룹의 다른 매장들로 복사한다."""
    group = get(group_id)
    member_ids = [m["id"] for m in group["stores"]]
    try:
        src = int(from_store)
    except (TypeError, ValueError):
        raise ValueError("복사할 매장을 골라 주세요")
    if src not in member_ids:
        raise ValueError("그룹에 속한 매장의 메뉴만 복사할 수 있습니다")
    targets = member_ids if not to_stores else [int(x) for x in to_stores]
    targets = [t for t in targets if t != src]
    if not targets:
        raise ValueError("복사할 대상 매장을 골라 주세요")
    for t in targets:
        if t not in member_ids:
            raise ValueError("그룹에 속한 매장으로만 복사할 수 있습니다")
    results = []
    for t in targets:
        results.append(stores.copy_menu(src, t, on_duplicate=on_duplicate))
    return {"group": group["id"], "from": src,
            "created": sum(r["created"] for r in results),
            "updated": sum(r["updated"] for r in results),
            "skipped": sum(r["skipped"] for r in results),
            "stores": results}


def transfer_staff(group_id, staff_id, to_store):
    """그룹 안 매장 사이의 직원 이동만 허용한다."""
    group = get(group_id)
    member_ids = [m["id"] for m in group["stores"]]
    try:
        dst = int(to_store)
        sid = int(staff_id)
    except (TypeError, ValueError):
        raise ValueError("직원과 옮길 매장을 골라 주세요")
    if dst not in member_ids:
        raise ValueError("그룹에 속한 매장으로만 직원을 옮길 수 있습니다")
    with store.read() as conn:
        row = conn.execute("SELECT store_id FROM staff WHERE id=?", (sid,)).fetchone()
    if not row or row["store_id"] not in member_ids:
        raise ValueError("그룹에 속한 매장의 직원만 옮길 수 있습니다")
    return stores.transfer_staff(sid, dst, note=f"그룹({group['name']}) 이동")


def apply_settings(group_id):
    """그룹 기본 설정(운영 모드·웨이팅·커뮤니티)을 그룹 매장에 적용한다."""
    from . import settings
    group = get(group_id)
    conf = group["settings"]
    patch = {}
    if conf.get("channelMode"):
        patch["channel"] = {"mode": conf["channelMode"]}
    if conf.get("waiting") is not None:
        patch["waiting"] = {"enabled": bool(conf["waiting"])}
    if conf.get("community") is not None:
        patch["community"] = {"enabled": bool(conf["community"])}
    if not patch:
        raise ValueError("적용할 그룹 설정이 없습니다. 그룹 설정에서 운영 모드를 골라 주세요")
    applied = []
    for m in group["stores"]:
        with stores.use(m["id"]):
            settings.save(patch)
        applied.append(m["id"])
    return {"group": group["id"], "applied": applied, "patch": patch}
