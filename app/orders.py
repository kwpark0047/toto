"""주문 모듈.

책임: 주문 생성(가격은 서버의 메뉴 가격으로 계산), 주문 상태 전이, 현금 결제 확인,
포인트 사용·적립의 주문 쪽 연결(계산 자체는 customers 모듈).

결제는 현금만 다룬다. 카드·간편결제는 자리만 있고 실제 결제는 일어나지 않는다.
테이블은 tables 모듈에서 확인한다(비활성 테이블은 주문을 받지 않는다).
"""
from . import catalog, config, customers, events, inventory, settings, stores, store, tables
from .config import STATUS_LABELS

CHANNEL_LABELS = config.CHANNEL_LABELS

# 주방 4단계: 접수 → 조리중 → 조리완료(서빙 대기) → 서빙 완료
STATUS_FLOW = {
    "RESERVED": {"NEW", "CANCELED"},
    "NEW": {"ACCEPTED", "CANCELED"},
    "ACCEPTED": {"COOKING", "NEW", "CANCELED"},
    "COOKING": {"DONE", "ACCEPTED", "CANCELED"},
    "DONE": {"SERVED", "COOKING", "CANCELED"},
    "SERVED": set(),
    "CANCELED": {"NEW"},
}
ACTIVE_STATUSES = ("NEW", "ACCEPTED", "COOKING")      # 조리 중(주방 대기열)
SERVING_STATUSES = ("DONE",)                          # 서빙 대기
OPEN_STATUSES = ACTIVE_STATUSES + SERVING_STATUSES    # 테이블을 차지하고 있는 상태


def _order_no(conn):
    row = conn.execute(
        "SELECT COUNT(*) c FROM orders WHERE substr(created_at,1,10)=? AND store_id=?",
        (store.today(), stores.current())
    ).fetchone()
    return f"{row['c'] + 1:03d}"


def _items_of(conn, order_id):
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,)
    ).fetchall()
    return [
        {
            "id": r["id"], "itemId": r["item_id"], "name": r["name"],
            "price": r["price"], "qty": r["qty"], "options": r["options_text"],
        }
        for r in rows
    ]


def cook_estimate(conn):
    """최근 완료 주문들의 평균 조리 시간(분). 표본이 2건 미만이면 None(계산 중)."""
    rows = conn.execute(
        "SELECT created_at, done_at FROM orders WHERE status='DONE' AND done_at IS NOT NULL"
        " ORDER BY id DESC LIMIT 10").fetchall()
    spans = []
    for row in rows:
        try:
            a = store.datetime.strptime(row["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            b = store.datetime.strptime(row["done_at"][:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        spans.append(max(0, (b - a).total_seconds() / 60))
    if len(spans) < 2:
        return None
    return round(sum(spans) / len(spans))


def _row_to_order(conn, r, with_items=True, labels=None):
    o = {
        "id": r["id"],
        "storeId": r["store_id"] if "store_id" in r.keys() else 1,
        "orderNo": r["order_no"],
        "table": r["table_no"],
        "tableLabel": ("대기 중(미리 주문)" if r["status"] == "RESERVED"
                       else (labels or {}).get(r["table_no"], f"{r['table_no']}번")),
        "status": r["status"],
        "paymentStatus": r["payment_status"],
        "paymentMethod": r["payment_method"],
        "subtotal": r["subtotal"] or r["total"],
        "discount": (r["discount"] if "discount" in r.keys() else 0) or 0,
        "couponId": r["coupon_id"] if "coupon_id" in r.keys() else None,
        "paymentMethodLabel": config.PAYMENT_METHOD_LABELS.get(r["payment_method"], r["payment_method"]),
        "channel": (r["channel"] if "channel" in r.keys() else "table") or "table",
        "channelLabel": CHANNEL_LABELS.get(
            (r["channel"] if "channel" in r.keys() else "table") or "table", ""),
        "transferDepositor": (r["transfer_depositor"] if "transfer_depositor" in r.keys() else "") or "",
        "transferConfirmedAt": (r["transfer_confirmed_at"]
                                if "transfer_confirmed_at" in r.keys() else None),
        "pointsUsed": r["points_used"],
        "pointsEarned": r["points_earned"],
        "reservedFor": r["reserved_for"] if "reserved_for" in r.keys() else None,
        "receiptType": (r["receipt_type"] if "receipt_type" in r.keys() else "none") or "none",
        "receiptNoMasked": _mask_no(r["receipt_no"]) if "receipt_no" in r.keys() else "",
        "receiptIssued": bool(r["receipt_issued"]) if "receipt_issued" in r.keys() else False,
        "reserved": r["status"] == "RESERVED",
        "total": r["total"],
        "customerId": r["customer_id"],
        "customerName": r["customer_name"],
        "customerPhone": r["customer_phone"],
        "note": r["note"],
        "createdAt": r["created_at"],
        "acceptedAt": r["accepted_at"],
        "cookingAt": r["cooking_at"],
        "doneAt": r["done_at"],
        "paidAt": r["paid_at"],
        "servedAt": r["served_at"] if "served_at" in r.keys() else None,
    }
    if r["status"] in OPEN_STATUSES:
        try:
            start = store.datetime.strptime(r["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            now = store.datetime.now(store.TZ).replace(tzinfo=None)
            o["elapsedMin"] = max(0, int((now - start).total_seconds() // 60))
        except (TypeError, ValueError):
            o["elapsedMin"] = 0
        o["cookEstimate"] = cook_estimate(conn)
    if r["status"] in SERVING_STATUSES:
        # 조리완료(서빙 대기)에서 얼마나 지났는지 — 주방 화면·손님 화면이 함께 쓴다
        try:
            done = store.datetime.strptime((r["done_at"] or r["created_at"])[:19], "%Y-%m-%d %H:%M:%S")
            now = store.datetime.now(store.TZ).replace(tzinfo=None)
            o["servingMin"] = max(0, int((now - done).total_seconds() // 60))
            o["servingSec"] = max(0, int((now - done).total_seconds()))
        except (TypeError, ValueError):
            o["servingMin"] = 0
            o["servingSec"] = 0
    if with_items:
        o["items"] = _items_of(conn, r["id"])
    return o


def _clean_receipt(receipt):
    """현금영수증 요청(휴대폰·사업자번호). 실제 발급은 하지 않는다."""
    receipt = receipt or {}
    kind = (receipt.get("type") or "none").strip().lower()
    if kind in ("", "none"):
        return "none", ""
    digits = "".join(ch for ch in (receipt.get("no") or "") if ch.isdigit())
    if kind == "phone":
        if len(digits) not in (10, 11):
            raise ValueError("현금영수증 휴대폰번호를 정확히 넣어 주세요 (예: 010-1234-5678)")
        return "phone", f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
    if kind == "biz":
        if len(digits) != 10:
            raise ValueError("사업자번호는 숫자 10자리로 넣어 주세요")
        return "biz", f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    raise ValueError("현금영수증 종류가 올바르지 않습니다")


def _mask_no(value):
    d = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(d) < 6:
        return ""
    return f"{d[:3]}-****-{d[-4:]}"


def create(table_no, items, customer=None, note="", points_used=0, preorder_token=None, receipt=None,
           channel=None, pay_method=None, coupon_id=None):
    """주문을 만든다. 결제는 하지 않고 '결제 전(UNPAID)' 상태로 접수된다.

    channel: table(매장 테이블) · pickup(포장) · delivery(배달) · preorder(대기 미리 주문)
    pay_method: CASH · TRANSFER · CARD · PAY (매장 설정에서 켜 둔 것만)
    """
    customer = customer or {}
    ch = (channel or "").strip().lower()
    if preorder_token:
        ch = "preorder"
    if not ch:
        ch = "table"
    if ch not in config.CHANNEL_LABELS:
        raise ValueError("주문 방식이 올바르지 않습니다")

    conf = settings.channel()
    if ch == "table":
        if not settings.offline_on():
            raise ValueError("이 매장은 지금 매장 테이블 주문을 받지 않습니다(온라인 전용 매장)")
    elif ch == "preorder":
        if not conf.get("preorder"):
            raise ValueError("이 매장은 대기 중 미리 주문을 받지 않습니다")
    else:
        if not settings.online_on():
            raise ValueError("이 매장은 지금 온라인 주문(포장·배달)을 받지 않습니다")
        if ch == "pickup" and not conf.get("pickup"):
            raise ValueError("이 매장은 포장 주문을 받지 않습니다")
        if ch == "delivery" and not conf.get("delivery"):
            raise ValueError("이 매장은 배달 주문을 받지 않습니다")
        if not (customer.get("name") or "").strip() or not (customer.get("phone") or "").strip():
            raise ValueError("포장·배달 주문은 이름과 연락처를 남겨 주세요")

    method = (pay_method or "CASH").strip().upper()
    if method not in config.PAYMENT_METHOD_LABELS:
        raise ValueError("결제수단이 올바르지 않습니다")
    pay_conf = settings.payments()
    pay_key = {"CASH": "cash", "TRANSFER": "transfer", "CARD": "card", "PAY": "quick"}[method]
    if not pay_conf[pay_key].get("enabled"):
        raise ValueError(f"{config.PAYMENT_METHOD_LABELS[method]} 결제는 이 매장에서 쓰지 않습니다")
    if method == "TRANSFER" and not (pay_conf["transfer"].get("bank")
                                    and pay_conf["transfer"].get("accountNo")):
        raise ValueError("이 매장은 아직 계좌이체 계좌를 등록하지 않았습니다")

    reserved_for = None
    if ch == "preorder":
        from . import waiting
        ticket = waiting.by_token(preorder_token)
        if ticket["status"] not in ("WAITING", "CALLED"):
            raise ValueError("대기 중일 때만 미리 주문할 수 있습니다")
        reserved_for = ticket["id"]
        table = {"id": 0, "label": "대기(미리 주문)", "active": True,
                 "storeId": ticket.get("storeId") or stores.current()}
    elif ch in ("pickup", "delivery"):
        table = {"id": 0, "label": "포장" if ch == "pickup" else "배달", "active": True,
                 "storeId": stores.current()}
    else:
        try:
            table_no = int(table_no)
        except (TypeError, ValueError):
            raise ValueError("테이블 번호가 올바르지 않습니다")
        table = tables.get_any(table_no)
        if not table["active"]:
            raise ValueError(f"'{table['label']}' 테이블은 지금 주문을 받지 않습니다. 직원에게 문의해 주세요")
    if not items:
        raise ValueError("주문할 메뉴를 선택해 주세요")

    # 테이블(또는 대기표)이 속한 매장의 메뉴·가격으로 계산한다
    ctx = stores.use(table.get("storeId") or stores.current())
    ctx.__enter__()
    try:
        return _create_in_store(table, items, customer, note, points_used, reserved_for, receipt,
                                channel=ch, pay_method=method, coupon_id=coupon_id)
    finally:
        ctx.__exit__(None, None, None)


def _create_in_store(table, items, customer, note, points_used, reserved_for, receipt,
                     channel="table", pay_method="CASH", coupon_id=None):

    # 1) 메뉴 확인과 금액 계산 (고객이 보낸 가격은 쓰지 않는다)
    catalog_now = {i["id"]: i for i in catalog.items()}
    lines, subtotal = [], 0
    for line in items:
        try:
            item_id = int(line.get("itemId"))
            qty = int(line.get("qty", 1))
        except (TypeError, ValueError):
            raise ValueError("주문 항목이 올바르지 않습니다")
        item = catalog_now.get(item_id)
        if not item:
            raise ValueError("메뉴를 찾을 수 없습니다")
        if item["soldout"]:
            raise ValueError(f"'{item['name']}'은(는) 품절입니다")
        if not (1 <= qty <= 99):
            raise ValueError("수량은 1~99개 사이로 선택해 주세요")
        opts = []
        for g in item["options"]:
            chosen = (line.get("options") or {}).get(g["name"], g["default"])
            if chosen not in g["choices"]:
                chosen = g["default"]
            opts.append(f"{g['name']}: {chosen}")
        lines.append({
            "itemId": item["id"], "name": item["name"], "price": item["price"],
            "qty": qty, "options": ", ".join(opts),
        })
        subtotal += item["price"] * qty
    if channel == "delivery":
        try:
            fee = int(settings.channel().get("deliveryFee") or 0)
        except (TypeError, ValueError):
            fee = 0
        subtotal += max(0, fee)

    try:
        points_used = int(points_used or 0)
    except (TypeError, ValueError):
        raise ValueError("사용할 포인트가 올바르지 않습니다")
    if points_used < 0:
        raise ValueError("사용할 포인트가 올바르지 않습니다")

    # 2) 이벤트·쿠폰 (주문 시점 설정으로 다시 계산한다)
    cid_guess = None
    if (customer.get("phone") or "").strip():
        m = customers.by_phone(customer.get("phone"))
        cid_guess = m["id"] if m else None
    coupon = events.preview_coupon(cid_guess, coupon_id, subtotal) if coupon_id else \
        {"id": None, "amount": 0, "title": ""}
    time_amount, time_label = events.time_discount(subtotal)
    discount = min(subtotal, int(coupon["amount"]) + int(time_amount))

    receipt_type, receipt_no = _clean_receipt(receipt)
    ts = store.now()
    sid = stores.current()
    status = "RESERVED" if reserved_for else "NEW"
    with store.tx() as conn:
        cid = customers.upsert(conn, customer.get("name", ""), customer.get("phone", ""),
                               customer.get("consent", False))
        order_no = _order_no(conn)
        cur = conn.execute(
            "INSERT INTO orders(store_id, order_no, table_no, status, payment_status, payment_method,"
            " subtotal, discount, coupon_id, points_used, points_earned, total, channel, customer_id,"
            " customer_name, customer_phone, note, created_at, updated_at)"
            " VALUES(?,?,?,?,'UNPAID',?,?,?,?,0,0,?,?,?,?,?,?,?,?)",
            (sid, order_no, table["id"], status, pay_method, subtotal, discount,
             coupon["id"], subtotal - discount, channel, cid, customer.get("name", "").strip(),
             customer.get("phone", "").strip(), (note or "").strip()[:300], ts, ts),
        )
        order_id = cur.lastrowid
        # 포인트 차감은 주문과 같은 트랜잭션에서 처리한다(잔액이 어긋나지 않게)
        used = customers.use_points(conn, cid, order_id, points_used, subtotal) if points_used else 0
        total = subtotal - discount - used
        if total < 0:
            raise ValueError("포인트 사용 금액이 주문 금액보다 큽니다")
        if used:
            conn.execute("UPDATE orders SET points_used=?, total=? WHERE id=?",
                         (used, total, order_id))
        if coupon["id"]:
            events.mark_coupon_used(conn, coupon["id"], order_id)
        conn.execute("UPDATE orders SET reserved_for=?, receipt_type=?, receipt_no=? WHERE id=?",
                     (reserved_for, receipt_type, receipt_no, order_id))
        for ln in lines:
            conn.execute(
                "INSERT INTO order_items(order_id, item_id, name, price, qty, options_text)"
                " VALUES(?,?,?,?,?,?)",
                (order_id, ln["itemId"], ln["name"], ln["price"], ln["qty"], ln["options"]),
            )
        store.bump(conn)
    out = get(order_id)
    out["discountLabel"] = " + ".join(x for x in (time_label,
                                                  f"쿠폰 {coupon['title']}" if coupon["id"] else "") if x)
    return out


def get(order_id):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not r:
            raise LookupError("주문을 찾을 수 없습니다")
        return _row_to_order(conn, r, labels=tables.label_map())


def list_orders(date=None, status=None, table=None, ids=None, unpaid=False, limit=200):
    sql = "SELECT * FROM orders WHERE store_id=?"
    params = [stores.current()]
    if date:
        sql += " AND substr(created_at,1,10)=?"
        params.append(date)
    if status:
        sts = status.split(",")
        sql += f" AND status IN ({','.join('?' * len(sts))})"
        params.extend(sts)
    if table:
        sql += " AND table_no=?"
        params.append(int(table))
    if ids:
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    if unpaid:
        sql += " AND payment_status='UNPAID' AND status <> 'CANCELED'"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    labels = tables.label_map()
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_order(conn, r, labels=labels) for r in rows]


def set_status(order_id, status):
    if status not in STATUS_LABELS:
        raise ValueError("알 수 없는 주문 상태입니다")
    ts = store.now()
    stamps = {"ACCEPTED": "accepted_at", "COOKING": "cooking_at", "DONE": "done_at",
              "SERVED": "served_at", "CANCELED": "canceled_at"}
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM orders WHERE id=? AND store_id=?",
                         (order_id, stores.current())).fetchone()
        if not r:
            raise LookupError("주문을 찾을 수 없습니다")
        if status == r["status"]:
            return _row_to_order(conn, r, labels=tables.label_map())
        if status not in STATUS_FLOW.get(r["status"], set()):
            raise ValueError(
                f"'{STATUS_LABELS[r['status']]}' 에서 '{STATUS_LABELS[status]}'(으)로 바꿀 수 없습니다")
        col = stamps.get(status)
        if col:
            conn.execute(f"UPDATE orders SET status=?, {col}=?, updated_at=? WHERE id=?",
                         (status, ts, ts, order_id))
        else:
            conn.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, ts, order_id))
        if status == "CANCELED":
            # 취소: 쓴 포인트는 돌려주고, 이미 적립한 포인트는 회수한다
            customers.refund_use(conn, order_id)
            events.restore_coupon(conn, order_id)
            if r["payment_status"] == "PAID":
                customers.cancel_earn(conn, order_id)
                inventory.restore_conn(conn, order_id)      # 재료도 되돌린다
                conn.execute("UPDATE orders SET payment_status='UNPAID', paid_at=NULL WHERE id=?",
                             (order_id,))
        if status == "NEW" and r["status"] == "CANCELED":
            # 취소 되돌리기: 할인 금액은 그대로 두되 결제 전 상태로 돌아간다
            conn.execute("UPDATE orders SET payment_status='UNPAID', paid_at=NULL WHERE id=?",
                         (order_id,))
        store.bump(conn)
        r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return _row_to_order(conn, r, labels=tables.label_map())


def set_payment(order_id, paid):
    """현금 결제 확인/취소. 확인하면 설정된 적립률로 포인트를 적립한다."""
    ts = store.now()
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM orders WHERE id=? AND store_id=?",
                         (order_id, stores.current())).fetchone()
        if not r:
            raise LookupError("주문을 찾을 수 없습니다")
        if r["status"] == "CANCELED" and paid:
            raise ValueError("취소된 주문은 결제 확인할 수 없습니다")
        if paid:
            already = conn.execute(
                "SELECT COALESCE(SUM(delta),0) d FROM point_events"
                " WHERE order_id=? AND kind IN ('earn','earn_cancel')", (order_id,)).fetchone()["d"]
            if not r["points_earned"] and not already:
                customers.earn_on_payment(conn, r)
            inventory.consume_conn(conn, r)      # 레시피대로 재료 차감(같은 트랜잭션, 한 번만)
        else:
            if r["points_earned"]:
                customers.cancel_earn(conn, order_id)
            inventory.restore_conn(conn, order_id)
        conn.execute(
            "UPDATE orders SET payment_status=?, paid_at=?, updated_at=? WHERE id=?",
            ("PAID" if paid else "UNPAID", ts if paid else None, ts, order_id),
        )
        if paid:
            # 첫 방문·재방문·생일·쿠폰 같은 고객 이벤트를 같은 트랜잭션에서 적용한다
            try:
                events.on_payment(conn, {
                    "id": r["id"], "customer_id": r["customer_id"], "total": r["total"],
                    "discountApplied": "시간 할인" if (r["discount"] if "discount" in r.keys() else 0)
                    else "",
                })
            except ValueError:
                pass      # 이벤트 계산 오류로 결제 확인을 막지는 않는다
        store.bump(conn)
        r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return _row_to_order(conn, r, labels=tables.label_map())


def cancel_by_customer(order_id, reason=""):
    """손님 주문 취소. 조리 시작 전(NEW·ACCEPTED)에만 허용한다."""
    with store.read() as conn:
        r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not r:
        raise LookupError("주문을 찾을 수 없습니다")
    if r["status"] in ("COOKING", "DONE"):
        raise ValueError("조리가 시작되어 앱에서는 취소할 수 없습니다. 직원에게 말씀해 주세요")
    if r["status"] == "CANCELED":
        return get(order_id)
    note = (r["note"] or "")
    if reason:
        note = (note + " / " if note else "") + f"손님 취소: {reason}"[:80]
    with store.tx() as conn:
        conn.execute("UPDATE orders SET note=?, updated_at=? WHERE id=?", (note, store.now(), order_id))
    return set_status(order_id, "CANCELED")


def set_receipt_issued(order_id, issued=True):
    with store.tx() as conn:
        cur = conn.execute("UPDATE orders SET receipt_issued=?, updated_at=? WHERE id=? AND store_id=?",
                           (1 if issued else 0, store.now(), order_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("주문을 찾을 수 없습니다")
        store.bump(conn)
        r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return _row_to_order(conn, r, labels=tables.label_map())


def start_reserved(reserved_for, table_id=None, staff=False):
    """대기 예약 주문을 주방으로 넘긴다(입장 처리 또는 직원의 수동 시작)."""
    with store.tx() as conn:
        rows = conn.execute("SELECT * FROM orders WHERE reserved_for=? AND status='RESERVED' AND store_id=?",
                            (reserved_for, stores.current())).fetchall()
        started = []
        for r in rows:
            if table_id:
                conn.execute("UPDATE orders SET table_no=?, status='NEW', updated_at=? WHERE id=?",
                             (int(table_id), store.now(), r["id"]))
            else:
                conn.execute("UPDATE orders SET status='NEW', updated_at=? WHERE id=?", (store.now(), r["id"]))
            started.append(r["id"])
        if started:
            store.bump(conn)
        return started


def cancel_reserved_conn(conn, reserved_for, reason="대기 취소"):
    """같은 트랜잭션 안에서 예약 주문을 취소한다(대기 취소·노쇼 처리와 함께)."""
    rows = conn.execute("SELECT * FROM orders WHERE reserved_for=? AND status='RESERVED'",
                        (reserved_for,)).fetchall()
    ts = store.now()
    for r in rows:
        conn.execute("UPDATE orders SET status='CANCELED', canceled_at=?,"
                     " note=CASE WHEN note='' THEN ? ELSE note || ' / ' || ? END, updated_at=?"
                     " WHERE id=?", (ts, reason, reason, ts, r["id"]))
    return [r["id"] for r in rows]


def cancel_reserved(reserved_for, reason="대기 취소"):
    with store.tx() as conn:
        ids = cancel_reserved_conn(conn, reserved_for, reason)
        if ids:
            store.bump(conn)
        return ids


def active(table_no=None):
    status = ",".join(ACTIVE_STATUSES)
    return list_orders(status=status, table=table_no)


def serving(limit=100):
    """조리완료(서빙 대기) 주문 — 오래된 것부터."""
    rows = list_orders(status="DONE", limit=limit)
    return list(reversed(rows))
