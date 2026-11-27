"""회원(단골 고객)·포인트 모듈.

책임:
- 주문서에서 이름·연락처를 남긴 손님을 회원으로 만들고(같은 연락처는 한 명으로 합침),
  사장님이 직접 회원을 등록·수정·합치기
- 방문 횟수·누적 결제액으로 등급(신규/단골/VIP)을 자동 산정하고, 사장님이 수동으로 바꿀 수 있음
- 포인트 적립(현금 결제 확인 시 결제 금액의 설정 비율)·사용(주문서)·이력
- 방문 이력, 즐겨 찾는 메뉴, 이번 달 생일 목록, CSV 내보내기

문자 발송은 하지 않는다(대상 선택까지만 — 2단계 예정).
포인트·주문·등급 계산은 모두 같은 트랜잭션에서 처리해 잔액이 어긋나지 않게 한다.
"""
import csv
import io
import re
from datetime import datetime

from . import config, settings, stores, store

FMT = "%Y-%m-%d %H:%M:%S"


def _parse(ts):
    try:
        return datetime.strptime(ts[:19], FMT)
    except (TypeError, ValueError):
        return None


def _norm_phone(phone):
    return "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "-").strip()


def _norm_birthday(value):
    """'1990-03-15' 또는 '03-15' → 저장 형식. 비우면 빈 값."""
    v = (value or "").strip()
    if not v:
        return ""
    digits = re.sub(r"[^0-9]", "", v)
    if len(digits) == 8:
        y, m, d = digits[:4], digits[4:6], digits[6:]
    elif len(digits) == 4:
        y, m, d = "", digits[:2], digits[2:]
    else:
        raise ValueError("생일은 1990-03-15 또는 03-15 형식으로 넣어 주세요")
    try:
        mi, di = int(m), int(d)
    except ValueError:
        raise ValueError("생일을 알아볼 수 없습니다")
    if not (1 <= mi <= 12 and 1 <= di <= 31):
        raise ValueError("생일 월·일이 올바르지 않습니다")
    return f"{y}-{m}-{d}" if y else f"{m}-{d}"


def birthday_parts(value):
    """저장된 생일 → (월, 일). 없으면 (None, None)."""
    v = (value or "").strip()
    if len(v) == 10 and v[4] == "-":
        v = v[5:]
    if len(v) == 5 and v[2] == "-":
        try:
            return int(v[:2]), int(v[3:])
        except ValueError:
            return None, None
    return None, None


def birthday_label(value):
    m, d = birthday_parts(value)
    return f"{m}월 {d}일" if m else ""


def _month_of(value):
    m, _ = birthday_parts(value)
    return m


# ---------------------------------------------------------------- 등급

def grade_table():
    grades = settings.grades()
    base = settings.base_grade()
    return {"grades": grades, "base": base}


def calc_grade(visits, spend, manual=""):
    manual = (manual or "").strip().upper()
    codes = {g["code"] for g in settings.grades()}
    if manual and manual in codes:
        for g in settings.grades():
            if g["code"] == manual:
                return {"code": g["code"], "label": g["label"], "auto": False,
                        "tone": {"VIP": "brand", "REGULAR": "amber"}.get(g["code"], "")}
    for g in settings.grades():
        if visits >= g["minVisits"] and spend >= g["minSpend"]:
            return {"code": g["code"], "label": g["label"], "auto": True,
                    "tone": {"VIP": "brand", "REGULAR": "amber"}.get(g["code"], "")}
    base = settings.base_grade()
    return {"code": base["code"], "label": base["label"], "auto": True, "tone": ""}


def grade_criteria_text():
    parts = []
    for g in settings.grades():
        parts.append(f"{g['label']} 방문 {g['minVisits']}회 이상·누적 {g['minSpend']:,}원 이상")
    return " / ".join(parts)


# ---------------------------------------------------------------- 포인트

def balance(conn, customer_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(delta),0) b FROM point_events WHERE customer_id=?", (customer_id,)
    ).fetchone()
    return int(row["b"] or 0)


def _add_event(conn, customer_id, order_id, kind, delta, memo=""):
    bal = balance(conn, customer_id) + int(delta)
    if bal < 0:
        raise ValueError("포인트가 부족합니다")
    conn.execute(
        "INSERT INTO point_events(customer_id, order_id, kind, delta, balance_after, memo, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (customer_id, order_id, kind, int(delta), bal, memo, store.now()),
    )
    return bal


def use_points(conn, customer_id, order_id, points, subtotal):
    """주문서에서 포인트 사용. 같은 트랜잭션에서 잔액을 확인하고 차감한다."""
    points = int(points or 0)
    if points <= 0:
        return 0
    if not customer_id:
        raise ValueError("포인트를 쓰려면 연락처를 남겨 주세요")
    have = balance(conn, customer_id)
    if points > have:
        raise ValueError(f"보유 포인트({have:,}P)보다 많이 쓸 수 없습니다")
    limit = int(subtotal * config.POINTS_MAX_USE_RATIO)
    if points > limit:
        raise ValueError(f"한 주문에서는 결제 금액의 {int(config.POINTS_MAX_USE_RATIO * 100)}%"
                         f"({limit:,}원)까지만 포인트를 쓸 수 있습니다")
    _add_event(conn, customer_id, order_id, "use", -points, "주문서 사용")
    return points


def earn_on_payment(conn, order):
    """현금 결제 확인 시 결제 금액의 설정 비율만큼 적립."""
    cid = order["customer_id"]
    if not cid:
        return 0
    rate = settings.points_rate()
    points = int(order["total"] * rate / 100)
    if points <= 0:
        return 0
    _add_event(conn, cid, order["id"], "earn", points, f"결제 적립 {rate:g}%")
    conn.execute("UPDATE orders SET points_earned=? WHERE id=?", (points, order["id"]))
    return points


def cancel_earn(conn, order_id):
    row = conn.execute(
        "SELECT customer_id, COALESCE(SUM(delta),0) d FROM point_events"
        " WHERE order_id=? AND kind IN ('earn','earn_cancel') GROUP BY customer_id", (order_id,)
    ).fetchone()
    if row and row["d"]:
        _add_event(conn, row["customer_id"], order_id, "earn_cancel", -row["d"], "결제 취소로 적립 회수")
    conn.execute("UPDATE orders SET points_earned=0 WHERE id=?", (order_id,))


def refund_use(conn, order_id):
    """주문 취소 시 사용한 포인트를 돌려준다."""
    row = conn.execute(
        "SELECT customer_id, COALESCE(SUM(delta),0) d FROM point_events"
        " WHERE order_id=? AND kind IN ('use','use_refund') GROUP BY customer_id", (order_id,)
    ).fetchone()
    if row and row["d"] < 0:
        _add_event(conn, row["customer_id"], order_id, "use_refund", -row["d"], "주문 취소로 포인트 반환")
        conn.execute("UPDATE orders SET points_used=0 WHERE id=?", (order_id,))


def add_points(conn, customer_id, order_id, kind, delta, memo=""):
    """다른 모듈(이벤트)이 같은 트랜잭션에서 포인트를 지급할 때 쓰는 공개 함수."""
    return _add_event(conn, customer_id, order_id, kind, delta, memo)


def birthday_of(conn, customer_id):
    """이벤트 판단용 생일 월(1~12). 없으면 None."""
    row = conn.execute("SELECT birthday FROM customers WHERE id=?", (int(customer_id),)).fetchone()
    return _month_of(row["birthday"]) if row else None


def visit_info(conn, customer_id, exclude_order=None):
    """결제 완료 기준 방문 횟수와 마지막 방문일(첫 방문·재방문 이벤트 판단용)."""
    sql = ("SELECT COUNT(*) c, MAX(substr(created_at,1,10)) last FROM orders"
           " WHERE customer_id=? AND payment_status='PAID' AND status<>'CANCELED' AND store_id=?")
    params = [customer_id, stores.current()]
    if exclude_order:
        sql += " AND id<>?"
        params.append(int(exclude_order))
    row = conn.execute(sql, params).fetchone()
    return {"paidVisits": int(row["c"] or 0) if row else 0,
            "lastVisit": (row["last"] if row else "") or ""}


def history(customer_id, limit=50):
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM point_events WHERE customer_id=? ORDER BY id DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
    return [{
        "id": r["id"], "orderId": r["order_id"], "kind": r["kind"], "delta": r["delta"],
        "balanceAfter": r["balance_after"], "memo": r["memo"], "createdAt": r["created_at"],
    } for r in rows]


# ---------------------------------------------------------------- 회원

def upsert(conn, name, phone, consent):
    """주문 시 회원 정보를 저장한다. 연락처가 있으면 연락처로, 없으면 이름으로 같은 사람을 찾는다."""
    name = (name or "").strip()
    phone = _norm_phone(phone)
    if not name and not phone:
        return None
    ts = store.now()
    row = None
    sid = stores.current()
    if phone:
        row = conn.execute("SELECT * FROM customers WHERE phone=? AND store_id=?",
                           (phone, sid)).fetchone()
    if row is None and name:
        row = conn.execute(
            "SELECT * FROM customers WHERE name=? AND phone='' AND store_id=? ORDER BY id DESC LIMIT 1",
            (name, sid)
        ).fetchone()
    if row:
        conn.execute(
            "UPDATE customers SET name=COALESCE(NULLIF(?,''), name),"
            " phone=COALESCE(NULLIF(?,''), phone), consent=MAX(consent, ?), updated_at=?"
            " WHERE id=?",
            (name, phone, 1 if consent else 0, ts, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO customers(store_id, name, phone, birthday, grade, consent, memo, created_at, updated_at)"
        " VALUES(?,?,?,'','',?,'',?,?)",
        (sid, name, phone, 1 if consent else 0, ts, ts),
    )
    return cur.lastrowid


def by_phone(phone):
    phone = _norm_phone(phone)
    if not phone:
        return None
    with store.read() as conn:
        r = conn.execute("SELECT * FROM customers WHERE phone=? AND store_id=?",
                         (phone, stores.current())).fetchone()
        if not r:
            return None
        return {"id": r["id"], "name": r["name"], "phone": r["phone"], "points": balance(conn, r["id"])}


def lookup(phone):
    """주문서에서 '보유 포인트'만 확인하는 공개 조회(이름·이력은 돌려주지 않는다)."""
    m = by_phone(phone)
    if not m:
        return {"member": False, "points": 0, "gradeLabel": ""}
    return {"member": True, "points": m["points"], "gradeLabel": ""}


def _agg(conn):
    return {r["customer_id"]: r for r in conn.execute(
        "SELECT customer_id, COUNT(*) visits,"
        " SUM(CASE WHEN payment_status='PAID' THEN total ELSE 0 END) paid_total,"
        " SUM(CASE WHEN payment_status='UNPAID' THEN total ELSE 0 END) unpaid_total,"
        " MIN(created_at) first_visit, MAX(created_at) last_visit,"
        " MAX(CASE WHEN payment_status='PAID' THEN created_at END) last_paid"
        " FROM orders WHERE customer_id IS NOT NULL AND status <> 'CANCELED' AND store_id=?"
        " GROUP BY customer_id", (stores.current(),)).fetchall()}


def _favorites(conn, customer_id, limit=5):
    rows = conn.execute(
        "SELECT oi.name, SUM(oi.qty) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id"
        " WHERE o.customer_id=? AND o.status<>'CANCELED' AND o.store_id=?"
        " GROUP BY oi.name ORDER BY qty DESC LIMIT ?",
        (customer_id, stores.current(), limit)).fetchall()
    return [{"name": r["name"], "qty": r["qty"]} for r in rows]


def _member(row, agg_row, points, favorites, month=None):
    today = datetime.strptime(store.today(), "%Y-%m-%d")
    visits = agg_row["visits"] if agg_row else 0
    paid_total = agg_row["paid_total"] if agg_row else 0
    unpaid_total = agg_row["unpaid_total"] if agg_row else 0
    last_visit = agg_row["last_visit"] if agg_row else None
    first_visit = agg_row["first_visit"] if agg_row else None
    cycle = None
    if visits >= 2 and first_visit and last_visit:
        d1, d2 = _parse(first_visit), _parse(last_visit)
        if d1 and d2 and (d2 - d1).days > 0:
            cycle = round((d2 - d1).days / (visits - 1))
    days_since = None
    if last_visit:
        lv = _parse(last_visit)
        if lv:
            days_since = (today - lv.replace(hour=0, minute=0, second=0)).days
    grade = calc_grade(visits, paid_total, row["grade"])
    bm, bd = birthday_parts(row["birthday"])
    return {
        "id": row["id"], "name": row["name"] or "(이름 없음)", "phone": row["phone"],
        "birthday": row["birthday"], "birthdayLabel": birthday_label(row["birthday"]),
        "birthdayMonth": bm, "birthdayDay": bd,
        "birthdayThisMonth": bm is not None and bm == int(store.today()[5:7]),
        "grade": grade["code"], "gradeLabel": grade["label"], "gradeTone": grade["tone"],
        "gradeAuto": grade["auto"], "gradeManual": (row["grade"] or ""),
        "points": points, "consent": bool(row["consent"]), "memo": row["memo"],
        "visits": visits, "paidTotal": paid_total, "unpaidTotal": unpaid_total,
        "lastVisit": last_visit, "firstVisit": first_visit, "daysSince": days_since,
        "cycleDays": cycle, "regular": grade["code"] != "신규" and grade["code"] != settings.base_grade()["code"],
        "favoriteMenus": favorites, "hasOrders": visits > 0,
    }


def list_customers(q="", sort="recent", grade_filter=""):
    with store.read() as conn:
        rows = conn.execute("SELECT * FROM customers WHERE store_id=?",
                            (stores.current(),)).fetchall()
        agg = _agg(conn)
        points = {r["customer_id"]: r["amount"] for r in conn.execute(
            "SELECT customer_id, COALESCE(SUM(delta),0) amount FROM point_events GROUP BY customer_id")}
        fav = {}
        for r in conn.execute(
            "SELECT o.customer_id, oi.name, SUM(oi.qty) qty FROM order_items oi"
            " JOIN orders o ON o.id=oi.order_id WHERE o.customer_id IS NOT NULL AND o.status<>'CANCELED'"
            " AND o.store_id=? GROUP BY o.customer_id, oi.name ORDER BY qty DESC",
            (stores.current(),)).fetchall():
            fav.setdefault(r["customer_id"], [])
            if len(fav[r["customer_id"]]) < 3:
                fav[r["customer_id"]].append({"name": r["name"], "qty": r["qty"]})
    out = [_member(r, agg.get(r["id"]), points.get(r["id"], 0), fav.get(r["id"], [])) for r in rows]

    if q:
        ql = q.lower().replace(" ", "")
        out = [c for c in out
               if ql in c["name"].lower().replace(" ", "") or ql in c["phone"].replace("-", "")
               or ql in (c["memo"] or "").lower()]
    if grade_filter:
        out = [c for c in out if c["grade"] == grade_filter.upper()]

    keys = {
        "recent": lambda c: (c["lastVisit"] or ""),
        "visits": lambda c: c["visits"],
        "spend": lambda c: c["paidTotal"],
        "points": lambda c: c["points"],
        "name": lambda c: c["name"],
        "unpaid": lambda c: c["unpaidTotal"],
        "birthday": lambda c: ((c["birthdayMonth"] or 13), (c["birthdayDay"] or 32)),
    }
    order = {"VIP": 0, "REGULAR": 1}
    if sort == "grade":
        out.sort(key=lambda c: (order.get(c["grade"], 2), -c["paidTotal"]))
    else:
        out.sort(key=keys.get(sort, keys["recent"]), reverse=sort not in ("name", "birthday"))
    return out


def counts(rows):
    """등급별 인원·생일 요약."""
    base = settings.base_grade()["code"]
    by = {base: 0}
    for g in settings.grades():
        by[g["code"]] = 0
    for c in rows:
        by[c["grade"]] = by.get(c["grade"], 0) + 1
    this_month = int(store.today()[5:7])
    bdays = [c for c in rows if c["birthdayMonth"] == this_month]
    bdays.sort(key=lambda c: c["birthdayDay"] or 99)
    return {
        "total": len(rows),
        "byGrade": by,
        "birthdays": bdays,
        "pointsTotal": sum(c["points"] for c in rows),
        "criteriaText": grade_criteria_text(),
        "pointsRate": settings.points_rate(),
        "grades": settings.grades(),
        "baseGrade": settings.base_grade(),
    }


def get_member(customer_id):
    with store.read() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id=? AND store_id=?",
                           (customer_id, stores.current())).fetchone()
        if not row:
            raise LookupError("회원을 찾을 수 없습니다")
        agg = _agg(conn).get(customer_id)
        pts = balance(conn, customer_id)
        fav = _favorites(conn, customer_id)
        orders = conn.execute(
            "SELECT * FROM orders WHERE customer_id=? AND store_id=? ORDER BY id DESC LIMIT 20",
            (customer_id, stores.current())
        ).fetchall()
        items = conn.execute(
            "SELECT oi.order_id, oi.name, oi.qty FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " WHERE o.customer_id=? ORDER BY oi.id", (customer_id,)).fetchall()
    by_order = {}
    for it in items:
        by_order.setdefault(it["order_id"], []).append(f"{it['name']}×{it['qty']}")
    member = _member(row, agg, pts, fav)
    member["orders"] = [{
        "id": o["id"], "orderNo": o["order_no"], "table": o["table_no"],
        "createdAt": o["created_at"], "total": o["total"], "status": o["status"],
        "paymentStatus": o["payment_status"],
        "pointsUsed": o["points_used"], "pointsEarned": o["points_earned"],
        "menu": ", ".join(by_order.get(o["id"], []))[:120],
    } for o in orders]
    member["pointHistory"] = history(customer_id, 50)
    return member


def create_member(data):
    """사장님이 직접 회원 등록. 같은 연락처가 있으면 그 회원에 합친다."""
    name = (data.get("name") or "").strip()
    phone = _norm_phone(data.get("phone"))
    if not name and not phone:
        raise ValueError("이름이나 연락처 중 하나는 넣어 주세요")
    birthday = _norm_birthday(data.get("birthday"))
    ts = store.now()
    with store.tx() as conn:
        if phone:
            row = conn.execute("SELECT * FROM customers WHERE phone=? AND store_id=?",
                               (phone, stores.current())).fetchone()
            if row:
                conn.execute(
                    "UPDATE customers SET name=COALESCE(NULLIF(?,''),name),"
                    " birthday=COALESCE(NULLIF(?,''),birthday), consent=MAX(consent,?),"
                    " memo=CASE WHEN memo='' THEN ? ELSE memo END, updated_at=? WHERE id=?",
                    (name, birthday, 1 if data.get("consent") else 0,
                     (data.get("memo") or "").strip()[:1000], ts, row["id"]))
                store.bump(conn)
                merged_id = row["id"]
                store.bump(conn)
                return {"id": merged_id, "merged": True, "member": None}
        cur = conn.execute(
            "INSERT INTO customers(store_id, name, phone, birthday, grade, consent, memo,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (stores.current(), name, phone, birthday, "", 1 if data.get("consent") else 0,
             (data.get("memo") or "").strip()[:1000], ts, ts),
        )
        cid = cur.lastrowid
        if data.get("grade"):
            _set_grade(conn, cid, data.get("grade"))
        store.bump(conn)
    return {"id": cid, "merged": False, "member": get_member(cid)}


def _set_grade(conn, customer_id, grade):
    grade = (grade or "").strip().upper()
    if grade and grade not in settings.grade_codes():
        raise ValueError("등급은 신규·단골·VIP 중에서 고르거나 '자동'으로 두세요")
    conn.execute("UPDATE customers SET grade=?, updated_at=? WHERE id=?",
                 (grade, store.now(), customer_id))


def set_grade(customer_id, grade):
    with store.tx() as conn:
        if not conn.execute("SELECT 1 FROM customers WHERE id=? AND store_id=?",
                            (customer_id, stores.current())).fetchone():
            raise LookupError("회원을 찾을 수 없습니다")
        _set_grade(conn, customer_id, grade)
        store.bump(conn)
    return get_member(customer_id)


def update(cust_id, data):
    sets, params = [], []
    if "memo" in data:
        sets.append("memo=?")
        params.append((data.get("memo") or "")[:1000])
    if "name" in data:
        sets.append("name=?")
        params.append((data.get("name") or "").strip())
    if "phone" in data:
        phone = _norm_phone(data.get("phone"))
        if phone:
            with store.read() as conn:
                dup = conn.execute("SELECT id FROM customers WHERE phone=? AND store_id=? AND id<>?",
                                   (phone, stores.current(), cust_id)).fetchone()
            if dup:
                raise ValueError("같은 연락처의 회원이 이미 있습니다. '합치기'로 하나로 만들어 주세요")
        sets.append("phone=?")
        params.append(phone)
    if "consent" in data:
        sets.append("consent=?")
        params.append(1 if data.get("consent") else 0)
    if "birthday" in data:
        sets.append("birthday=?")
        params.append(_norm_birthday(data.get("birthday")))
    if "grade" in data:
        sets.append("grade=?")
        grade = (data.get("grade") or "").strip().upper()
        if grade and grade not in settings.grade_codes():
            raise ValueError("등급은 신규·단골·VIP 중에서 고르거나 '자동'으로 두세요")
        params.append(grade)
    if not sets:
        return get_member(cust_id)
    sets.append("updated_at=?")
    params.append(store.now())
    with store.tx() as conn:
        cur = conn.execute(f"UPDATE customers SET {','.join(sets)} WHERE id=? AND store_id=?",
                           (*params, cust_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("회원을 찾을 수 없습니다")
        store.bump(conn)
    return get_member(cust_id)


def merge(keep_id, merge_ids):
    """중복 회원을 하나로 합친다. 주문·포인트 이력을 남는 회원 쪽으로 옮긴다."""
    ids = [int(i) for i in (merge_ids or []) if str(i).isdigit() and int(i) != int(keep_id)]
    if not ids:
        raise ValueError("합칠 회원을 골라 주세요")
    with store.tx() as conn:
        keep = conn.execute("SELECT * FROM customers WHERE id=? AND store_id=?",
                            (keep_id, stores.current())).fetchone()
        if not keep:
            raise LookupError("남길 회원을 찾을 수 없습니다")
        for other in ids:
            row = conn.execute("SELECT * FROM customers WHERE id=?", (other,)).fetchone()
            if not row:
                continue
            if row["phone"] and keep["phone"] and row["phone"] != keep["phone"]:
                # 연락처가 다르면 진짜 다른 사람일 수 있다 → 합치지 않는다
                raise ValueError(f"'{row['name']}' 회원은 연락처가 달라 합칠 수 없습니다")
            conn.execute("UPDATE orders SET customer_id=?,"
                         " customer_name=CASE WHEN customer_name='' THEN ? ELSE customer_name END"
                         " WHERE customer_id=? AND store_id=?", (keep_id, row["name"], other,
                                                                stores.current()))
            conn.execute("UPDATE point_events SET customer_id=? WHERE customer_id=?", (keep_id, other))
            conn.execute(
                "UPDATE customers SET phone=COALESCE(NULLIF(phone,''),?),"
                " birthday=COALESCE(NULLIF(birthday,''),?),"
                " memo=CASE WHEN memo='' THEN ? ELSE memo END,"
                " consent=MAX(consent,?), updated_at=? WHERE id=?",
                (row["phone"], row["birthday"], row["memo"], row["consent"], store.now(), keep_id))
            conn.execute("DELETE FROM customers WHERE id=?", (other,))
        store.bump(conn)
    return get_member(keep_id)


def delete(cust_id):
    with store.tx() as conn:
        conn.execute("UPDATE orders SET customer_id=NULL WHERE customer_id=? AND store_id=?",
                     (cust_id, stores.current()))
        conn.execute("DELETE FROM point_events WHERE customer_id=?", (cust_id,))
        cur = conn.execute("DELETE FROM customers WHERE id=? AND store_id=?",
                           (cust_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("회원을 찾을 수 없습니다")
        store.bump(conn)


def to_csv(rows=None):
    rows = rows if rows is not None else list_customers()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["이름", "등급", "연락처", "생일", "방문횟수", "누적결제금액", "미결제금액", "포인트",
                "최근방문", "첫방문", "재방문주기(일)", "연락처수집동의", "즐겨찾는메뉴", "메모"])
    for c in rows:
        w.writerow([
            c["name"], c["gradeLabel"], c["phone"], c["birthday"], c["visits"], c["paidTotal"],
            c["unpaidTotal"], c["points"], (c["lastVisit"] or "")[:16], (c["firstVisit"] or "")[:16],
            c["cycleDays"] if c["cycleDays"] is not None else "",
            "Y" if c["consent"] else "",
            ", ".join(f["name"] for f in c["favoriteMenus"]), c["memo"].replace("\n", " "),
        ])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # 엑셀에서 한글이 깨지지 않게 BOM
