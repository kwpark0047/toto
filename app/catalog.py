"""메뉴 카탈로그 모듈.

책임: 카테고리와 메뉴 항목의 조회·추가·수정·삭제, 품절, 노출 순서, 사진, 기본 옵션.
다른 모듈(주문/주방 등)은 이 모듈의 함수만 호출하고 menu_items 테이블을 직접 만지지 않는다.
"""
import json

from . import stores, store


def _row_to_item(r):
    options = []
    try:
        options = json.loads(r["options"] or "[]")
    except ValueError:
        options = []
    return {
        "id": r["id"],
        "categoryId": r["category_id"],
        "category": r["category_name"] if "category_name" in r.keys() else None,
        "name": r["name"],
        "price": r["price"],
        "description": r["description"],
        "image": r["image"],
        "options": options,
        "soldout": bool(r["soldout"]),
        "sort": r["sort"],
        "featured": bool(r["featured"]) if "featured" in r.keys() else False,
        "featuredSort": r["featured_sort"] if "featured_sort" in r.keys() else 0,
        "featuredNote": (r["featured_note"] if "featured_note" in r.keys() else "") or "",
        "origin": (r["origin"] if "origin" in r.keys() else "") or "",
        "allergens": _allergens(r["allergens"]) if "allergens" in r.keys() else [],
        "spice": (r["spice"] if "spice" in r.keys() else 0) or 0,
        "i18n": _i18n(r["i18n"]) if "i18n" in r.keys() else {},
    }


LANGS = ("en", "zh", "ja")


def _i18n(raw):
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for lang in LANGS:
        entry = data.get(lang) or {}
        if isinstance(entry, dict):
            name = (entry.get("name") or "").strip()
            desc = (entry.get("description") or "").strip()
            if name or desc:
                out[lang] = {"name": name[:60], "description": desc[:200]}
    return out


ALLERGENS = ["난류", "우유", "메밀", "땅콩", "대두", "밀", "고등어", "게", "새우", "돼지고기",
             "복숭아", "토마토", "아황산류", "호두", "닭고기", "소고기", "오징어", "조개류"]


def _allergens(raw):
    try:
        data = json.loads(raw or "[]")
        return [a for a in data if a in ALLERGENS]
    except (TypeError, ValueError):
        return []


def categories(conn=None, include_empty=True):
    close = False
    if conn is None:
        conn, close = store.connect(), True
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, c.sort,"
            " (SELECT COUNT(*) FROM menu_items m WHERE m.category_id=c.id AND m.store_id=c.store_id)"
            " AS item_count"
            " FROM categories c WHERE c.store_id=? ORDER BY c.sort, c.id",
            (stores.current(),)
        ).fetchall()
        out = [
            {"id": r["id"], "name": r["name"], "sort": r["sort"], "itemCount": r["item_count"]}
            for r in rows
        ]
        return out if include_empty else [c for c in out if c["itemCount"] > 0]
    finally:
        if close:
            conn.close()


def items(conn=None):
    close = False
    if conn is None:
        conn, close = store.connect(), True
    try:
        rows = conn.execute(
            "SELECT m.*, c.name AS category_name FROM menu_items m"
            " JOIN categories c ON c.id = m.category_id"
            " WHERE m.store_id=? ORDER BY c.sort, c.id, m.sort, m.id",
            (stores.current(),)
        ).fetchall()
        return [_row_to_item(r) for r in rows]
    finally:
        if close:
            conn.close()


def get_item(item_id, conn=None):
    close = False
    if conn is None:
        conn, close = store.connect(), True
    try:
        r = conn.execute(
            "SELECT m.*, c.name AS category_name FROM menu_items m"
            " JOIN categories c ON c.id = m.category_id WHERE m.id=? AND m.store_id=?",
            (item_id, stores.current())
        ).fetchone()
        if not r:
            raise LookupError("메뉴를 찾을 수 없습니다")
        return _row_to_item(r)
    finally:
        if close:
            conn.close()


def featured(limit=8, conn=None):
    """추천 메뉴. 지정된 추천이 없으면 결제 확인된 판매량 상위 메뉴를 대신 보여 준다."""
    close = False
    if conn is None:
        conn, close = store.connect(), True
    try:
        rows = conn.execute(
            "SELECT m.*, c.name AS category_name FROM menu_items m"
            " JOIN categories c ON c.id = m.category_id"
            " WHERE m.featured=1 AND m.store_id=? ORDER BY m.featured_sort, m.sort, m.id LIMIT ?",
            (stores.current(), limit)
        ).fetchall()
        out = [_row_to_item(r) for r in rows]
        if out:
            return {"items": out, "auto": False}
        rows = conn.execute(
            "SELECT m.*, c.name AS category_name, COALESCE(SUM(oi.qty),0) sold"
            " FROM menu_items m JOIN categories c ON c.id = m.category_id"
            " LEFT JOIN order_items oi ON oi.item_id = m.id"
            " LEFT JOIN orders o ON o.id = oi.order_id AND o.payment_status='PAID' AND o.status<>'CANCELED'"
            " WHERE m.store_id=? GROUP BY m.id ORDER BY sold DESC, m.sort, m.id LIMIT ?",
            (stores.current(), limit)
        ).fetchall()
        items = [_row_to_item(r) for r in rows if r["sold"]]
        return {"items": items, "auto": True}
    finally:
        if close:
            conn.close()


def set_featured(item_id, featured=True, note=None, sort=None):
    """메뉴를 추천으로 지정/해제하고 추천 문구·순서를 저장한다."""
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM menu_items WHERE id=? AND store_id=?",
                         (item_id, stores.current())).fetchone()
        if not r:
            raise LookupError("메뉴를 찾을 수 없습니다")
        sets, params = [], []
        sets.append("featured=?")
        params.append(1 if featured else 0)
        if note is not None:
            sets.append("featured_note=?")
            params.append((note or "").strip()[:60])
        if sort is not None:
            try:
                sets.append("featured_sort=?")
                params.append(int(sort))
            except (TypeError, ValueError):
                raise ValueError("추천 순서는 숫자로 넣어 주세요")
        sets.append("updated_at=?")
        params.append(store.now())
        conn.execute(f"UPDATE menu_items SET {','.join(sets)} WHERE id=?", (*params, item_id))
        store.bump(conn)
        return get_item(item_id)


def move_featured(item_id, direction="up"):
    with store.tx() as conn:
        rows = conn.execute(
            "SELECT id FROM menu_items WHERE featured=1 AND store_id=? ORDER BY featured_sort, sort, id",
            (stores.current(),)).fetchall()
        ids = [r["id"] for r in rows]
        if item_id not in ids:
            raise ValueError("추천 메뉴가 아닙니다. 먼저 추천으로 지정해 주세요")
        i = ids.index(item_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, mid in enumerate(ids, start=1):
                conn.execute("UPDATE menu_items SET featured_sort=? WHERE id=?", (pos, mid))
            store.bump(conn)
        return featured()


def customer_menu():
    """고객 화면용 메뉴: 카테고리별로 묶어서 돌려준다."""
    cats = [c for c in categories() if c["itemCount"] > 0]
    rows = [i for i in items() if i["categoryId"] in {c["id"] for c in cats}]
    return {"categories": cats, "items": rows}


def _clean(data, item_id=None):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("메뉴 이름을 입력해 주세요")
    try:
        price = int(data.get("price", 0))
    except (TypeError, ValueError):
        raise ValueError("가격은 숫자로 입력해 주세요")
    if price < 0:
        raise ValueError("가격은 0원 이상이어야 합니다")
    options = data.get("options") or []
    if not isinstance(options, list):
        raise ValueError("옵션 형식이 올바르지 않습니다")
    clean_opts = []
    for g in options:
        if not isinstance(g, dict):
            continue
        gname = (g.get("name") or "").strip()
        choices = [str(c).strip() for c in (g.get("choices") or []) if str(c).strip()]
        if not gname or not choices:
            continue
        default = (g.get("default") or choices[0]).strip()
        if default not in choices:
            default = choices[0]
        clean_opts.append({"name": gname, "choices": choices, "default": default})
    return {
        "name": name,
        "price": price,
        "description": (data.get("description") or "").strip(),
        "image": (data.get("image") or "").strip(),
        "soldout": 1 if data.get("soldout") else 0,
        "options": json.dumps(clean_opts, ensure_ascii=False),
        "category_id": int(data.get("categoryId") or 0),
        "origin": (data.get("origin") or "").strip()[:120],
        "allergens": json.dumps([a for a in (data.get("allergens") or []) if a in ALLERGENS],
                                ensure_ascii=False),
        "spice": max(0, min(3, int(data.get("spice") or 0))) if str(data.get("spice") or 0).isdigit() else 0,
        "i18n": json.dumps(_i18n(json.dumps(data.get("i18n") or {}, ensure_ascii=False)),
                           ensure_ascii=False),
    }


def create_item(data):
    d = _clean(data)
    ts = store.now()
    with store.tx() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE id=? AND store_id=?",
                            (d["category_id"], stores.current())).fetchone():
            raise ValueError("카테고리를 선택해 주세요")
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort),0)+1 s FROM menu_items WHERE category_id=? AND store_id=?",
            (d["category_id"], stores.current())
        ).fetchone()["s"]
        cur = conn.execute(
            "INSERT INTO menu_items(store_id, category_id, name, price, description, image, options,"
            " soldout, sort, origin, allergens, spice, i18n, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (stores.current(), d["category_id"], d["name"], d["price"], d["description"], d["image"],
             d["options"], d["soldout"], nxt, d["origin"], d["allergens"], d["spice"], d["i18n"], ts, ts),
        )
        new_id = cur.lastrowid
        store.bump(conn)
    return get_item(new_id)


def update_item(item_id, data):
    # 일부 항목만 보낸 경우(추천·원산지 등) 기존 값을 지우지 않도록 채워 넣는다
    current = get_item(item_id)
    merged = dict(data)
    for key, src in (("image", "image"), ("description", "description"), ("name", "name"),
                     ("price", "price"), ("options", "options"), ("categoryId", "categoryId"),
                     ("soldout", "soldout"), ("origin", "origin"), ("allergens", "allergens"),
                     ("spice", "spice"), ("i18n", "i18n")):
        if key not in merged and src in current:
            merged[key] = current[src]
    d = _clean(merged, item_id)
    ts = store.now()
    with store.tx() as conn:
        cur = conn.execute(
            "UPDATE menu_items SET name=?, price=?, description=?, image=?, options=?,"
            " soldout=?, category_id=?, origin=?, allergens=?, spice=?, i18n=?, updated_at=?"
            " WHERE id=? AND store_id=?",
            (d["name"], d["price"], d["description"], d["image"], d["options"],
             d["soldout"], d["category_id"], d["origin"], d["allergens"], d["spice"],
             d["i18n"], ts, item_id, stores.current()),
        )
        if cur.rowcount == 0:
            raise LookupError("메뉴를 찾을 수 없습니다")
        store.bump(conn)
    return get_item(item_id)


def delete_item(item_id):
    with store.tx() as conn:
        cur = conn.execute("DELETE FROM menu_items WHERE id=? AND store_id=?",
                           (item_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("메뉴를 찾을 수 없습니다")
        store.bump(conn)


def set_soldout(item_id, soldout):
    with store.tx() as conn:
        cur = conn.execute(
            "UPDATE menu_items SET soldout=?, updated_at=? WHERE id=? AND store_id=?",
            (1 if soldout else 0, store.now(), item_id, stores.current()),
        )
        if cur.rowcount == 0:
            raise LookupError("메뉴를 찾을 수 없습니다")
        store.bump(conn)
    return get_item(item_id)


def set_image(item_id, image_path):
    with store.tx() as conn:
        cur = conn.execute(
            "UPDATE menu_items SET image=?, updated_at=? WHERE id=? AND store_id=?",
            (image_path, store.now(), item_id, stores.current()),
        )
        if cur.rowcount == 0:
            raise LookupError("메뉴를 찾을 수 없습니다")
        store.bump(conn)
    return get_item(item_id)


def move_item(item_id, direction):
    """같은 카테고리 안에서 노출 순서를 한 칸 올리거나 내린다."""
    step = -1 if direction == "up" else 1
    with store.tx() as conn:
        row = conn.execute("SELECT id, category_id, sort FROM menu_items WHERE id=? AND store_id=?",
                           (item_id, stores.current())).fetchone()
        if not row:
            raise LookupError("메뉴를 찾을 수 없습니다")
        rows = conn.execute(
            "SELECT id, sort FROM menu_items WHERE category_id=? AND store_id=? ORDER BY sort, id",
            (row["category_id"], stores.current()),
        ).fetchall()
        idx = [r["id"] for r in rows].index(item_id)
        target = idx + step
        if 0 <= target < len(rows):
            a, b = rows[idx], rows[target]
            conn.execute("UPDATE menu_items SET sort=? WHERE id=?", (b["sort"], a["id"]))
            conn.execute("UPDATE menu_items SET sort=? WHERE id=?", (a["sort"], b["id"]))
            store.bump(conn)
        # 순서 값이 겹쳐 있어도 정렬이 유지되도록 전체를 1..n 으로 다시 매긴다
        rows = conn.execute(
            "SELECT id FROM menu_items WHERE category_id=? AND store_id=? ORDER BY sort, id",
            (row["category_id"], stores.current())
        ).fetchall()
        for i, r in enumerate(rows):
            conn.execute("UPDATE menu_items SET sort=? WHERE id=?", (i + 1, r["id"]))
    return items()


def create_category(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("카테고리 이름을 입력해 주세요")
    ts = store.now()
    with store.tx() as conn:
        nxt = conn.execute("SELECT COALESCE(MAX(sort),0)+1 s FROM categories WHERE store_id=?",
                           (stores.current(),)).fetchone()["s"]
        cur = conn.execute(
            "INSERT INTO categories(store_id, name, sort, created_at) VALUES(?,?,?,?)",
            (stores.current(), name, nxt, ts)
        )
        store.bump(conn)
        return {"id": cur.lastrowid, "name": name, "sort": nxt, "itemCount": 0}


def rename_category(cat_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("카테고리 이름을 입력해 주세요")
    with store.tx() as conn:
        cur = conn.execute("UPDATE categories SET name=? WHERE id=? AND store_id=?",
                           (name, cat_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("카테고리를 찾을 수 없습니다")
        store.bump(conn)
    return categories()


def delete_category(cat_id):
    with store.tx() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM menu_items WHERE category_id=? AND store_id=?",
                         (cat_id, stores.current())).fetchone()["c"]
        if n:
            raise ValueError(f"메뉴 {n}개가 들어 있어 지울 수 없습니다. 메뉴를 옮기거나 지운 뒤 다시 시도해 주세요")
        cur = conn.execute("DELETE FROM categories WHERE id=? AND store_id=?", (cat_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("카테고리를 찾을 수 없습니다")
        store.bump(conn)


def move_category(cat_id, direction):
    step = -1 if direction == "up" else 1
    with store.tx() as conn:
        rows = conn.execute("SELECT id FROM categories WHERE store_id=? ORDER BY sort, id",
                            (stores.current(),)).fetchall()
        ids = [r["id"] for r in rows]
        if cat_id not in ids:
            raise LookupError("카테고리를 찾을 수 없습니다")
        idx = ids.index(cat_id)
        target = idx + step
        if 0 <= target < len(ids):
            ids[idx], ids[target] = ids[target], ids[idx]
        for i, cid in enumerate(ids):
            conn.execute("UPDATE categories SET sort=? WHERE id=?", (i + 1, cid))
        store.bump(conn)
    return categories()
