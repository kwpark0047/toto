"""결제 모듈.

책임: 결제수단별 설정(현금·계좌이체·카드·간편결제)과 결제 기록.
- 현금: 계산대에서 받고 사장님이 '결제 확인'.
- 계좌이체: 손님이 매장 계좌로 입금하고 입금자명을 남긴다. 사장님이 입금을 확인해야 결제 완료.
- 카드·간편결제: 매장 설정에서 켜고 끈다. PG 계약 전에는 **모의 승인**만 하고
  실제 돈은 오가지 않는다(화면에도 'PG 미연결'로 표시).

포인트 적립·재고 차감은 주문 모듈(orders.set_payment)이 맡고, 이 모듈은
'어떤 수단으로 얼마를 받았는지'와 수수료 계산만 책임진다.
"""
import secrets

from . import config, orders, settings, store, stores

METHOD_KEY = {"CASH": "cash", "TRANSFER": "transfer", "CARD": "card", "PAY": "quick"}
KEY_METHOD = {v: k for k, v in METHOD_KEY.items()}


def _norm(method):
    code = (method or "").strip().upper()
    if not code:
        return ""
    if code in METHOD_KEY:
        return code
    # 화면에서 한글 이름으로 와도 받아 준다
    for c, label, _d in config.PAYMENT_METHODS:
        if (method or "").strip() == label:
            return c
    raise ValueError("결제수단은 현금·계좌이체·카드·간편결제 중에서 골라 주세요")


def conf():
    return settings.payments()


def method_conf(method):
    code = _norm(method)
    return conf()[METHOD_KEY[code]]


def available():
    """지금 손님에게 보여 줄 결제수단. 계좌이체는 계좌가 등록돼야 나온다."""
    out = []
    cfg = conf()
    for code, label, desc in config.PAYMENT_METHODS:
        item = cfg[METHOD_KEY[code]]
        if not item.get("enabled"):
            continue
        if code == "TRANSFER" and not (item.get("bank") and item.get("accountNo")):
            continue
        out.append({
            "code": code, "label": label, "desc": desc,
            "note": item.get("note", ""),
            "bank": item.get("bank", ""), "accountNo": item.get("accountNo", ""),
            "holder": item.get("holder", ""),
            "feeRate": item.get("feeRate", 0),
            "provider": item.get("provider", ""),
        })
    return out


class Adapter:
    """PG 연동 대비 어댑터.

    실제 PG(토스페이먼츠·나이스·이니시스 등) 계약과 키가 있어야 진짜 승인이 난다.
    키가 없으면 어떤 결제도 실제로 일어나지 않도록 모의 승인으로만 응답한다.
    """

    def __init__(self, provider=""):
        self.provider = (provider or "none").strip() or "none"

    @property
    def configured(self):
        """실제 키가 설정돼 있는지. 지금 배포는 키가 없어 항상 False(모의)."""
        import os
        if self.provider in ("", "none"):
            return False
        return bool(os.environ.get(f"PG_{self.provider.upper()}_SECRET_KEY"))

    def authorize(self, amount, order_no, method, memo=""):
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("결제 금액이 올바르지 않습니다")
        if self.configured:
            # 실제 PG 호출은 계약·키가 들어온 뒤 이 자리에 구현한다.
            # 지금은 실제 승인을 흉내 내지 않는다.
            return {"ok": False, "simulated": False, "txn": "",
                    "message": "PG 연동 코드가 아직 연결되지 않았습니다. 카운터 단말기로 결제해 주세요"}
        txn = "SIM-" + method + "-" + secrets.token_hex(4).upper()
        return {"ok": True, "simulated": True, "txn": txn,
                "message": "PG 미연결 · 모의 승인(실제 결제 아님)"}


def _order(order_id):
    o = orders.get(order_id)
    if o.get("storeId") and o["storeId"] != stores.current():
        raise LookupError("주문을 찾을 수 없습니다")
    return o


def _fee(amount, rate):
    try:
        rate = float(rate or 0)
    except (TypeError, ValueError):
        rate = 0.0
    return int(round(int(amount) * rate / 100.0))


def _record(conn, order, method, status, amount=None, provider="", txn="", simulated=False,
            depositor="", memo="", fee_rate=None):
    amount = int(amount if amount is not None else order["total"])
    conf_item = conf()[METHOD_KEY[method]]
    fee_rate = conf_item.get("feeRate", 0) if fee_rate is None else fee_rate
    ts = store.now()
    cur = conn.execute(
        "INSERT INTO payments(store_id, order_id, method, amount, fee_rate, fee, status, provider,"
        " provider_txn, simulated, depositor, memo, created_at, confirmed_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order.get("storeId") or stores.current(), order["id"], method, amount, fee_rate,
         _fee(amount, fee_rate), status, provider or conf_item.get("provider", ""), txn,
         1 if simulated else 0, (depositor or "").strip()[:40], (memo or "")[:120], ts,
         ts if status in ("PAID", "REFUNDED") else None),
    )
    return cur.lastrowid


def begin_transfer(order_id, depositor):
    """손님이 계좌이체를 고르고 입금자명을 남긴다. 아직 결제 완료는 아니다."""
    method = "TRANSFER"
    item = method_conf(method)
    if not item.get("enabled") or not (item.get("bank") and item.get("accountNo")):
        raise ValueError("이 매장은 계좌이체를 받지 않습니다")
    depositor = (depositor or "").strip()
    if not depositor:
        raise ValueError("입금자명을 넣어 주세요 (사장님이 입금과 대조합니다)")
    o = _order(order_id)
    if o["paymentStatus"] == "PAID":
        return {"order": o, "payment": None, "alreadyPaid": True}
    if o["status"] == "CANCELED":
        raise ValueError("취소된 주문입니다")
    with store.tx() as conn:
        conn.execute("UPDATE orders SET payment_method=?, transfer_depositor=?, updated_at=?"
                     " WHERE id=?", (method, depositor[:40], store.now(), o["id"]))
        existing = conn.execute(
            "SELECT id FROM payments WHERE order_id=? AND method='TRANSFER' AND status='PENDING'",
            (o["id"],)).fetchone()
        if not existing:
            _record(conn, o, method, "PENDING", depositor=depositor, memo="입금 확인 대기")
        store.bump(conn)
    return {"order": orders.get(o["id"]), "payment": order_payments(o["id"]),
            "notice": f"{item.get('bank')} {item.get('accountNo')} (예금주 {item.get('holder') or '매장'})"}


def charge(order_id, method, memo="", depositor=""):
    """카드·간편결제(또는 현금) 결제를 기록하고 결제 완료로 바꾼다.

    PG 키가 없으면 모의 승인이며, 응답의 simulated=true 로 반드시 알린다.
    """
    code = _norm(method)
    if code == "TRANSFER":
        raise ValueError("계좌이체는 입금자명을 남기고 사장님이 입금을 확인합니다")
    if code == "CASH":
        # 현금은 결제 기록만 남기고 바로 확인 처리한다(모의 승인 아님)
        return confirm(order_id, "CASH", actor=None)
    item = method_conf(code)
    if not item.get("enabled"):
        raise ValueError(f"{config.PAYMENT_METHOD_LABELS[code]} 결제는 이 매장에서 쓰지 않습니다")
    o = _order(order_id)
    if o["status"] == "CANCELED":
        raise ValueError("취소된 주문은 결제할 수 없습니다")
    if o["paymentStatus"] == "PAID":
        raise ValueError("이미 결제가 끝난 주문입니다")
    adapter = Adapter(item.get("provider") if code in ("CARD", "PAY") else "none")
    result = adapter.authorize(o["total"], o["orderNo"], code, memo)
    if not result["ok"]:
        raise ValueError(result["message"])
    with store.tx() as conn:
        _record(conn, o, code, "PAID", provider=adapter.provider, txn=result["txn"],
                simulated=result["simulated"], depositor=depositor, memo=memo)
        conn.execute("UPDATE orders SET payment_method=?, updated_at=? WHERE id=?",
                     (code, store.now(), o["id"]))
    paid = orders.set_payment(o["id"], True)
    return {"order": paid, "method": code, "simulated": result["simulated"],
            "message": result["message"], "txn": result["txn"],
            "payments": order_payments(o["id"])}


def confirm(order_id, method=None, actor=None):
    """사장님이 입금·현금을 확인하고 결제 완료로 바꾼다(계좌이체·현금)."""
    o = _order(order_id)
    if o["status"] == "CANCELED":
        raise ValueError("취소된 주문은 결제 확인할 수 없습니다")
    if o["paymentStatus"] == "PAID":
        return {"order": o, "alreadyPaid": True, "payments": order_payments(o["id"])}
    code = _norm(method) if method else (o.get("paymentMethod") or "CASH")
    item = method_conf(code)
    if not item.get("enabled"):
        raise ValueError(f"{config.PAYMENT_METHOD_LABELS[code]} 결제는 이 매장에서 쓰지 않습니다")
    ts = store.now()
    with store.tx() as conn:
        pend = conn.execute(
            "SELECT * FROM payments WHERE order_id=? AND status='PENDING' ORDER BY id DESC LIMIT 1",
            (o["id"],)).fetchone()
        if pend:
            conn.execute("UPDATE payments SET status='PAID', confirmed_at=?, method=? WHERE id=?",
                         (ts, code, pend["id"]))
        else:
            _record(conn, o, code, "PAID", depositor=o.get("transferDepositor", ""))
        conn.execute("UPDATE orders SET payment_method=?, transfer_confirmed_at=?, updated_at=?"
                     " WHERE id=?",
                     (code, ts if code == "TRANSFER" else None, ts, o["id"]))
    paid = orders.set_payment(o["id"], True)
    return {"order": paid, "method": code, "confirmedAt": ts,
            "payments": order_payments(o["id"])}


def cancel(order_id, actor=None):
    """결제 취소·환불. 주문은 결제 전으로 돌아가고 결제 기록은 환불로 남긴다."""
    o = _order(order_id)
    if o["paymentStatus"] != "PAID":
        raise ValueError("결제 완료된 주문이 아닙니다")
    ts = store.now()
    with store.tx() as conn:
        conn.execute("UPDATE payments SET status='REFUNDED', memo=CASE WHEN memo='' THEN ?"
                     " ELSE memo || ' / ' || ? END WHERE order_id=? AND status='PAID'",
                     (f"{ts} 취소", f"{ts} 취소", o["id"]))
        conn.execute("UPDATE orders SET transfer_confirmed_at=NULL, updated_at=? WHERE id=?",
                     (ts, o["id"]))
    refunded = orders.set_payment(o["id"], False)
    return {"order": refunded, "payments": order_payments(o["id"])}


def order_payments(order_id):
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE order_id=? AND store_id=? ORDER BY id",
            (int(order_id), stores.current())).fetchall()
    return [_pay_row(r) for r in rows]


def _pay_row(r):
    return {
        "id": r["id"], "orderId": r["order_id"], "method": r["method"],
        "methodLabel": config.PAYMENT_METHOD_LABELS.get(r["method"], r["method"]),
        "amount": r["amount"], "feeRate": r["fee_rate"], "fee": r["fee"],
        "status": r["status"], "provider": r["provider"], "txn": r["provider_txn"],
        "simulated": bool(r["simulated"]), "depositor": r["depositor"],
        "memo": r["memo"], "createdAt": r["created_at"], "confirmedAt": r["confirmed_at"],
    }


def pending_transfers(limit=100):
    """입금 확인을 기다리는 계좌이체 주문."""
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE store_id=? AND payment_method='TRANSFER'"
            " AND payment_status<>'PAID' AND status<>'CANCELED' ORDER BY id DESC LIMIT ?",
            (stores.current(), int(limit))).fetchall()
    labels = None
    out = []
    for r in rows:
        out.append({
            "orderId": r["id"], "orderNo": r["order_no"], "table": r["table_no"],
            "total": r["total"], "depositor": r["transfer_depositor"] or "",
            "createdAt": r["created_at"], "note": r["note"],
        })
    return {"pending": out, "account": {
        "bank": conf()["transfer"].get("bank", ""),
        "accountNo": conf()["transfer"].get("accountNo", ""),
        "holder": conf()["transfer"].get("holder", ""),
    }}


def summary(date=None):
    date = date or store.today()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT method, COUNT(*) c, COALESCE(SUM(amount),0) a, COALESCE(SUM(fee),0) f"
            " FROM payments WHERE store_id=? AND status='PAID' AND substr(created_at,1,10)=?"
            " GROUP BY method", (stores.current(), date)).fetchall()
    by_method = []
    total = fee = 0
    for r in rows:
        total += r["a"]
        fee += r["f"]
        by_method.append({"method": r["method"],
                          "label": config.PAYMENT_METHOD_LABELS.get(r["method"], r["method"]),
                          "count": r["c"], "amount": r["a"], "fee": r["f"]})
    for code, label, _d in config.PAYMENT_METHODS:
        if not any(x["method"] == code for x in by_method):
            by_method.append({"method": code, "label": label, "count": 0, "amount": 0, "fee": 0})
    return {"date": date, "methods": by_method, "total": total, "fee": fee,
            "adapter": {"configured": Adapter(conf()["card"].get("provider")).configured,
                        "mode": "live" if Adapter(conf()["card"].get("provider")).configured
                        else "simulation"}}
