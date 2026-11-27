"""고객 이벤트·쿠폰 모듈.

책임:
- 매장 설정의 이벤트(첫 방문·재방문·생일·시간 할인·쿠폰)를 실제 주문에 적용한다.
- 결제가 끝나면 조건에 맞는 고객에게 포인트를 주고 쿠폰을 발급한다.
- 쿠폰 발급·사용·복원 내역을 남긴다.

계산은 서버가 한다. 손님이 보낸 할인 금액은 쓰지 않고, 주문 시점의 설정으로 다시 계산한다.
"""
from datetime import datetime, timedelta

from . import config, customers, settings, store, stores
from . import store as store_mod

EVENTS = [
    ("firstVisit", "첫 방문"),
    ("revisit", "재방문"),
    ("birthday", "생일"),
    ("timeDiscount", "시간 할인"),
    ("coupon", "쿠폰"),
]


def conf():
    return settings.events_conf()


def _hm(text):
    try:
        h, m = str(text or "").split(":")
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def time_discount(subtotal, at=None):
    """지금 시각이 시간 할인 구간이면 (할인 금액, 안내문)을 돌려준다."""
    cfg = conf()["timeDiscount"]
    if not cfg.get("enabled"):
        return 0, ""
    now = at or store.now()[11:16]
    start, end = _hm(cfg.get("start")), _hm(cfg.get("end"))
    cur = _hm(now)
    if start is None or end is None or cur is None:
        return 0, ""
    if not (start <= cur < end):
        return 0, ""
    percent = max(0, min(90, int(cfg.get("percent") or 0)))
    amount = int(int(subtotal) * percent / 100)
    if amount <= 0:
        return 0, ""
    return amount, f"시간 할인 {percent}% ({cfg.get('start')}~{cfg.get('end')})"


# ---------------------------------------------------------------- 쿠폰
def _coupon_template(conn, event_key):
    cfg = conf()["coupon"]
    sid = stores.current()
    row = conn.execute("SELECT * FROM coupons WHERE store_id=? AND event=? ORDER BY id LIMIT 1",
                       (sid, event_key)).fetchone()
    title = {"firstVisit": "첫 방문 감사 쿠폰", "birthday": "생일 축하 쿠폰"}.get(
        event_key, cfg.get("title") or "단골 감사 쿠폰")
    if row:
        return row
    cur = conn.execute(
        "INSERT INTO coupons(store_id, title, kind, amount, min_spend, valid_days, active, event,"
        " created_at) VALUES(?,?,?,?,?,?,1,?,?)",
        (sid, title[:40], "amount", int(cfg.get("amount") or 0), int(cfg.get("minSpend") or 0),
         int(cfg.get("validDays") or 30), event_key, store.now()),
    )
    return conn.execute("SELECT * FROM coupons WHERE id=?", (cur.lastrowid,)).fetchone()


def issue(conn, customer_id, event_key="coupon", coupon_id=None):
    """고객에게 쿠폰을 발급한다. 같은 이벤트 쿠폰이 이미 유효하게 있으면 또 주지 않는다."""
    sid = stores.current()
    if coupon_id:
        c = conn.execute("SELECT * FROM coupons WHERE id=? AND store_id=?",
                         (int(coupon_id), sid)).fetchone()
    else:
        c = _coupon_template(conn, event_key)
    if not c:
        raise LookupError("쿠폰을 찾을 수 없습니다")
    if not c["active"]:
        raise ValueError("지금은 쓰지 않는 쿠폰입니다")
    issued_at = store.now()
    expires = (datetime.strptime(issued_at, "%Y-%m-%d %H:%M:%S")
               + timedelta(days=int(c["valid_days"] or 30))).strftime("%Y-%m-%d %H:%M:%S")
    if event_key != "manual":
        dup = conn.execute(
            "SELECT id FROM customer_coupons WHERE store_id=? AND customer_id=? AND coupon_id=?"
            " AND status='ISSUED' AND expires_at>=?", (sid, customer_id, c["id"], issued_at)
        ).fetchone()
        if dup:
            return None
    cur = conn.execute(
        "INSERT INTO customer_coupons(store_id, coupon_id, customer_id, status, issued_at, expires_at)"
        " VALUES(?,?,?,'ISSUED',?,?)",
        (sid, c["id"], customer_id, issued_at, expires))
    return {"id": cur.lastrowid, "couponId": c["id"], "title": c["title"],
            "amount": c["amount"], "minSpend": c["min_spend"], "expiresAt": expires}


def customer_coupons(customer_id, status=None):
    sql = ("SELECT cc.*, c.title, c.kind, c.amount, c.min_spend FROM customer_coupons cc"
           " JOIN coupons c ON c.id=cc.coupon_id WHERE cc.customer_id=? AND cc.store_id=?")
    params = [int(customer_id), stores.current()]
    if status:
        sql += " AND cc.status=?"
        params.append(status)
    sql += " ORDER BY cc.id DESC"
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    now = store.now()
    out = []
    for r in rows:
        status_now = r["status"]
        if status_now == "ISSUED" and r["expires_at"] < now:
            status_now = "EXPIRED"
        out.append({
            "id": r["id"], "couponId": r["coupon_id"], "title": r["title"],
            "kind": r["kind"], "amount": r["amount"], "minSpend": r["min_spend"],
            "status": status_now, "orderId": r["order_id"], "issuedAt": r["issued_at"],
            "expiresAt": r["expires_at"], "usable": status_now == "ISSUED",
        })
    return out


def preview_coupon(customer_id, coupon_id, subtotal):
    """주문 전에 쿠폰을 쓸 수 있는지 확인하고 할인 금액을 돌려준다."""
    if not coupon_id:
        return {"id": None, "amount": 0, "title": ""}
    if not customer_id:
        raise ValueError("쿠폰을 쓰려면 연락처를 남겨 주세요")
    with store.read() as conn:
        r = conn.execute(
            "SELECT cc.*, c.title, c.kind, c.amount, c.min_spend, c.active FROM customer_coupons cc"
            " JOIN coupons c ON c.id=cc.coupon_id"
            " WHERE cc.id=? AND cc.customer_id=? AND cc.store_id=?",
            (int(coupon_id), int(customer_id), stores.current())).fetchone()
    if not r:
        raise ValueError("쿠폰을 찾을 수 없습니다")
    if r["status"] != "ISSUED":
        raise ValueError("이미 쓴 쿠폰입니다")
    if not r["active"]:
        raise ValueError("지금은 쓰지 않는 쿠폰입니다")
    if r["expires_at"] < store.now():
        raise ValueError("유효 기간이 지난 쿠폰입니다")
    subtotal = int(subtotal or 0)
    if subtotal < int(r["min_spend"] or 0):
        raise ValueError(f"{int(r['min_spend'] or 0):,}원 이상 주문할 때 쓸 수 있는 쿠폰입니다")
    if r["kind"] == "percent":
        amount = int(subtotal * int(r["amount"]) / 100)
    else:
        amount = int(r["amount"])
    amount = max(0, min(amount, subtotal))
    return {"id": r["id"], "amount": amount, "title": r["title"],
            "minSpend": r["min_spend"]}


def mark_coupon_used(conn, cc_id, order_id):
    ts = store.now()
    cur = conn.execute(
        "UPDATE customer_coupons SET status='USED', order_id=?, used_at=? WHERE id=? AND status='ISSUED'",
        (int(order_id), ts, int(cc_id)))
    if cur.rowcount == 0:
        raise ValueError("쿠폰을 쓸 수 없습니다")
    return ts


def restore_coupon(conn, order_id):
    """주문 취소 시 쿠폰을 다시 쓸 수 있게 돌려준다."""
    conn.execute("UPDATE customer_coupons SET status='ISSUED', order_id=NULL, used_at=NULL"
                 " WHERE order_id=? AND status='USED'", (int(order_id),))


# ---------------------------------------------------------------- 결제 후 이벤트
def _log(conn, customer_id, order_id, event, title, points=0, coupon_id=None):
    conn.execute(
        "INSERT INTO event_log(store_id, customer_id, order_id, event, title, points, coupon_id,"
        " created_at) VALUES(?,?,?,?,?,?,?,?)",
        (stores.current(), customer_id, order_id, event, title[:60], int(points or 0),
         coupon_id, store.now()))


def on_payment(conn, order):
    """결제가 확인되면 조건에 맞는 이벤트를 적용한다(같은 트랜잭션).

    이미 처리한 주문이면 event_log 로 확인해 두 번 주지 않는다.
    """
    cid = order["customer_id"]
    if not cid:
        return []
    cfg = conf()
    done = conn.execute("SELECT event FROM event_log WHERE order_id=? AND store_id=?",
                        (order["id"], stores.current())).fetchall()
    done_keys = {r["event"] for r in done}
    granted = []
    info = customers.visit_info(conn, cid, exclude_order=order["id"])

    def give_points(event, points, title):
        if points <= 0:
            return
        customers.add_points(conn, cid, order["id"], f"event:{event}", int(points), title)
        _log(conn, cid, order["id"], event, title, points=points)
        granted.append({"event": event, "title": title, "points": int(points)})

    first = cfg["firstVisit"]
    if first.get("enabled") and "firstVisit" not in done_keys and info["paidVisits"] == 0:
        give_points("firstVisit", int(first.get("points") or 0), "첫 방문 감사 포인트")
        if first.get("coupon"):
            c = issue(conn, cid, "firstVisit")
            if c:
                _log(conn, cid, order["id"], "firstVisitCoupon", "첫 방문 쿠폰", coupon_id=c["id"])
                granted.append({"event": "firstVisitCoupon", "title": c["title"],
                                "couponId": c["id"]})

    rev = cfg["revisit"]
    if rev.get("enabled") and "revisit" not in done_keys and info["paidVisits"] > 0:
        days = int(rev.get("days") or 0)
        last = info["lastVisit"]
        try:
            gap = (datetime.strptime(store.today(), "%Y-%m-%d")
                   - datetime.strptime(last, "%Y-%m-%d")).days if last else 999
        except ValueError:
            gap = 999
        if gap <= days:
            give_points("revisit", int(rev.get("points") or 0), f"{days}일 안 재방문 포인트")

    bday = cfg["birthday"]
    if bday.get("enabled") and "birthday" not in done_keys:
        if customers.birthday_of(conn, cid) == int(store.today()[5:7]):
            if not conn.execute("SELECT 1 FROM event_log WHERE customer_id=? AND event='birthday'"
                                " AND substr(created_at,1,4)=? AND store_id=?",
                                (cid, store.today()[:4], stores.current())).fetchone():
                give_points("birthday", int(bday.get("points") or 0), "생일 축하 포인트")
                if bday.get("coupon"):
                    c = issue(conn, cid, "birthday")
                    if c:
                        _log(conn, cid, order["id"], "birthdayCoupon", "생일 축하 쿠폰",
                             coupon_id=c["id"])
                        granted.append({"event": "birthdayCoupon", "title": c["title"],
                                        "couponId": c["id"]})

    if order.get("discountApplied"):
        _log(conn, cid, order["id"], "timeDiscount", order["discountApplied"],
             points=0)
    return granted


# ---------------------------------------------------------------- 사장님 화면
def coupons():
    with store.read() as conn:
        rows = conn.execute("SELECT * FROM coupons WHERE store_id=? ORDER BY id", (stores.current(),)).fetchall()
        counts = {r["coupon_id"]: r for r in conn.execute(
            "SELECT coupon_id, COUNT(*) issued,"
            " SUM(CASE WHEN status='USED' THEN 1 ELSE 0 END) used"
            " FROM customer_coupons WHERE store_id=? GROUP BY coupon_id", (stores.current(),)).fetchall()}
    return {"coupons": [{
        "id": r["id"], "title": r["title"], "kind": r["kind"], "amount": r["amount"],
        "minSpend": r["min_spend"], "validDays": r["valid_days"], "active": bool(r["active"]),
        "event": r["event"], "issued": (counts.get(r["id"]) or {"issued": 0})["issued"] or 0,
        "used": (counts.get(r["id"]) or {"used": 0})["used"] or 0,
    } for r in rows]}


def create_coupon(data):
    data = data or {}
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("쿠폰 이름을 넣어 주세요")
    try:
        amount = int(data.get("amount") or 0)
        min_spend = int(data.get("minSpend") or 0)
        valid_days = int(data.get("validDays") or 30)
    except (TypeError, ValueError):
        raise ValueError("쿠폰 금액·조건은 숫자로 넣어 주세요")
    if amount <= 0:
        raise ValueError("쿠폰 금액은 1원 이상으로 넣어 주세요")
    if valid_days < 1 or valid_days > 365:
        raise ValueError("쿠폰 유효 기간은 1~365일로 넣어 주세요")
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO coupons(store_id, title, kind, amount, min_spend, valid_days, active,"
            " event, created_at) VALUES(?,?,?,?,?,?,1,'manual',?)",
            (stores.current(), title[:40], "amount", amount, max(0, min_spend), valid_days,
             store.now()))
        store.bump(conn)
        return {"id": cur.lastrowid, "title": title, "amount": amount}


def issue_to(customer_id, coupon_id=None):
    with store.tx() as conn:
        cid = int(customer_id)
        if not conn.execute("SELECT 1 FROM customers WHERE id=? AND store_id=?",
                            (cid, stores.current())).fetchone():
            raise LookupError("회원을 찾을 수 없습니다")
        issued = issue(conn, cid, "manual" if coupon_id else "coupon", coupon_id)
        if not issued:
            return {"issued": False, "reason": "이미 같은 쿠폰을 가지고 있습니다"}
        store.bump(conn)
    return {"issued": True, "coupon": issued}


def events_view():
    """이벤트 설정·쿠폰·최근 적용 내역을 한 번에(사장님 화면)."""
    with store.read() as conn:
        logs = conn.execute(
            "SELECT l.*, c.name AS customer_name FROM event_log l"
            " LEFT JOIN customers c ON c.id=l.customer_id"
            " WHERE l.store_id=? ORDER BY l.id DESC LIMIT 30", (stores.current(),)).fetchall()
    return {
        "config": conf(),
        "catalog": [{"code": c, "label": l} for c, l in EVENTS],
        "coupons": coupons()["coupons"],
        "recent": [{
            "id": r["id"], "customer": r["customer_name"] or "", "event": r["event"],
            "title": r["title"], "points": r["points"], "createdAt": r["created_at"],
        } for r in logs],
    }
