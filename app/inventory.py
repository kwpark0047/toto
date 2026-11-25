"""재고·재료 모듈.

책임:
- 재료 등록(이름·단위·현재고·안전재고)
- 메뉴별 소모량(레시피) 설정 → 현금 결제 확인 때 자동 차감, 결제 취소·주문 취소 때 되돌리기
- 입고·조정 기록(누가 아니라 '무엇을 얼마나'만 남긴다)
- 안전재고 미만 경고, 재고가 모자란 메뉴의 '품절 제안'

하지 않는 것: 자동 발주, 거래처·외부 전송, 원가 계산(추후). 재고는 참고용 수량이며
실제 창고 수량과 다르면 '조정'으로 맞춘다.

차감·복원은 주문 결제와 같은 트랜잭션(conn) 안에서 처리해 수량이 어긋나지 않게 한다.
"""
from . import stores, store

KINDS = {"IN": "입고", "OUT": "차감", "ADJUST": "조정", "RESTORE": "복원"}
UNITS = ["개", "g", "kg", "ml", "L", "봉", "판", "모", "장", "팩"]


def _num(value, label, allow_zero=True):
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}은(는) 숫자로 넣어 주세요")
    if num < 0 and allow_zero:
        raise ValueError(f"{label}은(는) 0 이상으로 넣어 주세요")
    return round(num, 2)


def _fmt(num):
    num = float(num or 0)
    return int(num) if abs(num - int(num)) < 1e-9 else round(num, 2)


def _row(r):
    stock = float(r["stock"] or 0)
    safety = float(r["safety"] or 0)
    return {
        "id": r["id"], "name": r["name"], "unit": r["unit"],
        "stock": _fmt(stock), "safety": _fmt(safety),
        "low": stock < safety, "out": stock <= 0,
        "memo": r["memo"], "active": bool(r["active"]),
        "updatedAt": r["updated_at"],
    }


def list_ingredients():
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM ingredients WHERE store_id=? AND active=1 ORDER BY name, id",
            (stores.current(),)).fetchall()
    return [_row(r) for r in rows]


def get_ingredient(ingredient_id):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM ingredients WHERE id=? AND store_id=?",
                         (ingredient_id, stores.current())).fetchone()
        if not r:
            raise LookupError("재료를 찾을 수 없습니다")
        return _row(r)


def create_ingredient(data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("재료 이름을 넣어 주세요 (예: 쌀, 계란, 김치)")
    unit = (data.get("unit") or "개").strip()[:6] or "개"
    stock = _num(data.get("stock", 0), "현재고")
    safety = _num(data.get("safety", 0), "안전재고")
    ts = store.now()
    with store.tx() as conn:
        dup = conn.execute("SELECT id FROM ingredients WHERE store_id=? AND name=?",
                           (stores.current(), name)).fetchone()
        if dup:
            raise ValueError(f"'{name}' 재료가 이미 있습니다")
        cur = conn.execute(
            "INSERT INTO ingredients(store_id, name, unit, stock, safety, memo, active, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,1,?,?)",
            (stores.current(), name, unit, stock, safety, (data.get("memo") or "").strip()[:200], ts, ts))
        store.bump(conn)
        new_id = cur.lastrowid
    return get_ingredient(new_id)


def update_ingredient(ingredient_id, data):
    sets, params = [], []
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("재료 이름을 넣어 주세요")
        sets.append("name=?")
        params.append(name[:40])
    if "unit" in data:
        sets.append("unit=?")
        params.append((data.get("unit") or "개").strip()[:6] or "개")
    if "stock" in data:
        sets.append("stock=?")
        params.append(_num(data.get("stock"), "현재고"))
    if "safety" in data:
        sets.append("safety=?")
        params.append(_num(data.get("safety"), "안전재고"))
    if "memo" in data:
        sets.append("memo=?")
        params.append((data.get("memo") or "").strip()[:200])
    if "active" in data:
        sets.append("active=?")
        params.append(1 if data.get("active") else 0)
    if not sets:
        return get_ingredient(ingredient_id)
    sets.append("updated_at=?")
    params.append(store.now())
    with store.tx() as conn:
        cur = conn.execute(
            f"UPDATE ingredients SET {','.join(sets)} WHERE id=? AND store_id=?",
            (*params, ingredient_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("재료를 찾을 수 없습니다")
        store.bump(conn)
    return get_ingredient(ingredient_id)


def delete_ingredient(ingredient_id):
    """레시피에서도 같이 지운다(과거 기록은 남긴다)."""
    with store.tx() as conn:
        cur = conn.execute("DELETE FROM ingredients WHERE id=? AND store_id=?",
                          (ingredient_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("재료를 찾을 수 없습니다")
        conn.execute("DELETE FROM recipes WHERE ingredient_id=? AND store_id=?",
                     (ingredient_id, stores.current()))
        store.bump(conn)
    return True


def _log(conn, ingredient_id, kind, delta, stock_after, order_id=None, memo=""):
    conn.execute(
        "INSERT INTO ingredient_logs(store_id, ingredient_id, kind, delta, stock_after, order_id,"
        " memo, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (stores.current(), ingredient_id, kind, round(delta, 3), round(stock_after, 3), order_id,
         (memo or "")[:200], store.now()))


def stock_in(ingredient_id, qty, memo=""):
    """입고: 수량을 더한다."""
    qty = _num(qty, "입고 수량", allow_zero=False)
    if qty <= 0:
        raise ValueError("입고 수량은 0보다 커야 합니다")
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM ingredients WHERE id=? AND store_id=?",
                         (ingredient_id, stores.current())).fetchone()
        if not r:
            raise LookupError("재료를 찾을 수 없습니다")
        after = float(r["stock"] or 0) + qty
        conn.execute("UPDATE ingredients SET stock=?, updated_at=? WHERE id=?",
                     (after, store.now(), ingredient_id))
        _log(conn, ingredient_id, "IN", qty, after, None, memo or "입고")
        store.bump(conn)
    return get_ingredient(ingredient_id)


def adjust(ingredient_id, new_stock, memo=""):
    """조정: 실제 수량으로 맞춘다(차이를 기록)."""
    new_stock = _num(new_stock, "실제 수량")
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM ingredients WHERE id=? AND store_id=?",
                         (ingredient_id, stores.current())).fetchone()
        if not r:
            raise LookupError("재료를 찾을 수 없습니다")
        before = float(r["stock"] or 0)
        conn.execute("UPDATE ingredients SET stock=?, updated_at=? WHERE id=?",
                     (new_stock, store.now(), ingredient_id))
        _log(conn, ingredient_id, "ADJUST", new_stock - before, new_stock, None, memo or "실사 조정")
        store.bump(conn)
    return get_ingredient(ingredient_id)


def logs(limit=100, ingredient_id=None):
    sql = ("SELECT l.*, i.name AS ing_name, i.unit FROM ingredient_logs l"
           " JOIN ingredients i ON i.id=l.ingredient_id WHERE l.store_id=?")
    params = [stores.current()]
    if ingredient_id:
        sql += " AND l.ingredient_id=?"
        params.append(int(ingredient_id))
    sql += " ORDER BY l.id DESC LIMIT ?"
    params.append(int(limit))
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{
        "id": r["id"], "ingredientId": r["ingredient_id"], "name": r["ing_name"], "unit": r["unit"],
        "kind": r["kind"], "kindLabel": KINDS.get(r["kind"], r["kind"]),
        "delta": _fmt(r["delta"]), "stockAfter": _fmt(r["stock_after"]),
        "orderId": r["order_id"], "memo": r["memo"], "createdAt": r["created_at"],
    } for r in rows]


# ---------------------------------------------------------------- 레시피
def recipes(menu_item_id=None):
    sql = ("SELECT r.*, i.name AS ing_name, i.unit, i.stock, i.safety, m.name AS menu_name"
           " FROM recipes r JOIN ingredients i ON i.id=r.ingredient_id"
           " JOIN menu_items m ON m.id=r.menu_item_id WHERE r.store_id=?")
    params = [stores.current()]
    if menu_item_id:
        sql += " AND r.menu_item_id=?"
        params.append(int(menu_item_id))
    sql += " ORDER BY r.menu_item_id, i.name"
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{
        "id": r["id"], "menuItemId": r["menu_item_id"], "menuName": r["menu_name"],
        "ingredientId": r["ingredient_id"], "ingredientName": r["ing_name"], "unit": r["unit"],
        "qty": _fmt(r["qty"]), "stock": _fmt(r["stock"]),
    } for r in rows]


def set_recipe(menu_item_id, lines):
    """메뉴 한 개의 레시피를 통째로 바꾼다. lines=[{ingredientId, qty}]"""
    try:
        menu_item_id = int(menu_item_id)
    except (TypeError, ValueError):
        raise ValueError("메뉴를 골라 주세요")
    clean = []
    for line in lines or []:
        try:
            ing_id = int(line.get("ingredientId"))
        except (TypeError, ValueError):
            continue
        qty = _num(line.get("qty"), "소모량", allow_zero=False)
        if qty <= 0:
            raise ValueError("소모량은 0보다 커야 합니다")
        clean.append((ing_id, qty))
    with store.tx() as conn:
        if not conn.execute("SELECT 1 FROM menu_items WHERE id=? AND store_id=?",
                            (menu_item_id, stores.current())).fetchone():
            raise LookupError("메뉴를 찾을 수 없습니다")
        for ing_id, _ in clean:
            if not conn.execute("SELECT 1 FROM ingredients WHERE id=? AND store_id=?",
                                (ing_id, stores.current())).fetchone():
                raise ValueError("재료를 찾을 수 없습니다")
        conn.execute("DELETE FROM recipes WHERE menu_item_id=? AND store_id=?",
                     (menu_item_id, stores.current()))
        for ing_id, qty in clean:
            conn.execute(
                "INSERT INTO recipes(store_id, menu_item_id, ingredient_id, qty, created_at)"
                " VALUES(?,?,?,?,?)", (stores.current(), menu_item_id, ing_id, qty, store.now()))
        store.bump(conn)
    return recipes(menu_item_id)


def _recipe_map(conn):
    rows = conn.execute("SELECT menu_item_id, ingredient_id, qty FROM recipes WHERE store_id=?",
                        (stores.current(),)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["menu_item_id"], []).append((r["ingredient_id"], float(r["qty"])))
    return out


def consume_conn(conn, order):
    """현금 결제 확인 때 레시피만큼 재료를 차감한다(같은 주문에 한 번만)."""
    order_id = order["id"] if "id" in order.keys() else order["id"]
    done = conn.execute("SELECT 1 FROM ingredient_logs WHERE order_id=? AND kind='OUT' LIMIT 1",
                        (order_id,)).fetchone()
    if done:
        return 0
    recipes_map = _recipe_map(conn)
    if not recipes_map:
        return 0
    lines = conn.execute("SELECT item_id, name, qty FROM order_items WHERE order_id=?",
                         (order_id,)).fetchall()
    need = {}
    for line in lines:
        for ing_id, qty in recipes_map.get(line["item_id"], []):
            need[ing_id] = need.get(ing_id, 0) + qty * line["qty"]
    touched = 0
    for ing_id, amount in need.items():
        r = conn.execute("SELECT * FROM ingredients WHERE id=? AND store_id=?",
                         (ing_id, stores.current())).fetchone()
        if not r:
            continue
        after = float(r["stock"] or 0) - amount
        conn.execute("UPDATE ingredients SET stock=?, updated_at=? WHERE id=?",
                     (round(after, 3), store.now(), ing_id))
        _log(conn, ing_id, "OUT", -amount, after, order_id, f"주문 {order['order_no']}")
        touched += 1
    return touched


def restore_conn(conn, order_id):
    """결제 취소·주문 취소 때 차감했던 재료를 되돌린다."""
    rows = conn.execute(
        "SELECT ingredient_id, delta FROM ingredient_logs WHERE order_id=? AND kind='OUT'",
        (order_id,)).fetchall()
    if not rows:
        return 0
    for row in rows:
        add_back = -float(row["delta"])
        r = conn.execute("SELECT * FROM ingredients WHERE id=?", (row["ingredient_id"],)).fetchone()
        if not r:
            continue
        after = float(r["stock"] or 0) + add_back
        conn.execute("UPDATE ingredients SET stock=?, updated_at=? WHERE id=?",
                     (round(after, 3), store.now(), row["ingredient_id"]))
        _log(conn, row["ingredient_id"], "RESTORE", add_back, after, order_id, "결제 취소로 복원")
    # 같은 주문을 다시 결제하면 다시 차감되도록 OUT 기록을 지운다
    conn.execute("DELETE FROM ingredient_logs WHERE order_id=? AND kind='OUT'", (order_id,))
    return len(rows)


# ---------------------------------------------------------------- 경고·품절 제안
def warnings():
    items = list_ingredients()
    low = [i for i in items if i["low"]]
    out = [i for i in items if i["out"]]
    return {"low": low, "out": out, "lowCount": len(low), "outCount": len(out)}


def suggestions():
    """재고가 모자란 재료를 쓰는 메뉴 → '품절로 바꾸기' 제안."""
    with store.read() as conn:
        rows = conn.execute(
            "SELECT m.id AS menu_id, m.name AS menu_name, m.soldout, i.id AS ing_id, i.name AS ing_name,"
            " i.unit, i.stock, r.qty FROM recipes r"
            " JOIN menu_items m ON m.id=r.menu_item_id JOIN ingredients i ON i.id=r.ingredient_id"
            " WHERE r.store_id=? AND m.soldout=0 ORDER BY m.name", (stores.current(),)).fetchall()
    grouped = {}
    for r in rows:
        if float(r["stock"] or 0) >= float(r["qty"] or 0):
            continue
        g = grouped.setdefault(r["menu_id"], {
            "menuItemId": r["menu_id"], "menuName": r["menu_name"], "ingredients": []})
        g["ingredients"].append({
            "name": r["ing_name"], "unit": r["unit"],
            "stock": _fmt(r["stock"]), "need": _fmt(r["qty"])})
    return list(grouped.values())


def summary():
    with store.read() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM ingredients WHERE store_id=? AND active=1",
                         (stores.current(),)).fetchone()["c"]
        used = conn.execute("SELECT COUNT(*) c FROM ingredients WHERE store_id=? AND active=1"
                            " AND stock < safety", (stores.current(),)).fetchone()["c"]
        recipes_n = conn.execute("SELECT COUNT(DISTINCT menu_item_id) c FROM recipes WHERE store_id=?",
                                 (stores.current(),)).fetchone()["c"]
    return {"ingredientCount": n, "lowCount": used, "recipeMenuCount": recipes_n,
            "units": UNITS, "kinds": KINDS}
