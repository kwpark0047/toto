"""주방 모듈.

책임: 조리해야 할 주문 대기열(접수·조리중), 주문 경과 시간과 지연 표시, 테이블별 현황판.
상태 변경 자체는 주문 모듈(orders.set_status)에 맡기고, 여기서는 '보여 줄 것'을 만든다.
"""
from datetime import datetime

from . import catalog, config, orders, stores, store, tables as tables_mod
from .config import STATUS_LABELS


def _elapsed(created_at):
    try:
        start = datetime.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0
    return max(0, int((datetime.now(store.TZ).replace(tzinfo=None) - start).total_seconds()))


def queue():
    """조리해야 할 주문 목록. 오래된 주문이 위로 온다.

    알레르기 정보가 있는 메뉴가 포함된 주문은 allergens 를 함께 돌려준다(주방에서 강조).
    """
    menu = {i["id"]: i for i in catalog.items()}
    rows = []
    for o in reversed(orders.active()):  # list는 최신순이므로 뒤집어 오래된 것부터
        sec = _elapsed(o["createdAt"])
        mins = sec // 60
        if mins >= config.DELAY_LATE_MIN:
            delay = "late"
        elif mins >= config.DELAY_WARN_MIN:
            delay = "warn"
        else:
            delay = "ok"
        o["elapsedSec"] = sec
        o["elapsedMin"] = mins
        o["delay"] = delay
        o["statusLabel"] = STATUS_LABELS[o["status"]]
        seen = []
        for item in o.get("items", []):
            for a in (menu.get(item.get("itemId")) or {}).get("allergens", []):
                if a not in seen:
                    seen.append(a)
        o["allergens"] = seen
        o["hasAllergen"] = bool(seen)
        rows.append(o)
    rows.sort(key=lambda x: (not x["hasAllergen"], -x["elapsedSec"]))
    return rows


def counts():
    today = store.today()
    with store.read() as conn:
        def c(sql, *p):
            return conn.execute(sql, p).fetchone()["c"]
        sid = stores.current()
        return {
            "new": c("SELECT COUNT(*) c FROM orders WHERE status='NEW' AND store_id=?", sid),
            "accepted": c("SELECT COUNT(*) c FROM orders WHERE status='ACCEPTED' AND store_id=?", sid),
            "cooking": c("SELECT COUNT(*) c FROM orders WHERE status='COOKING' AND store_id=?", sid),
            "waiting": c("SELECT COUNT(*) c FROM orders WHERE status IN ('NEW','ACCEPTED')"
                         " AND store_id=?", sid),
            "serving": c("SELECT COUNT(*) c FROM orders WHERE status='DONE' AND store_id=?", sid),
            "servedToday": c("SELECT COUNT(*) c FROM orders WHERE status='SERVED'"
                             " AND substr(created_at,1,10)=? AND store_id=?", today, sid),
            "doneToday": c("SELECT COUNT(*) c FROM orders WHERE status IN ('DONE','SERVED')"
                           " AND substr(created_at,1,10)=? AND store_id=?", today, sid),
            "unpaidToday": c("SELECT COUNT(*) c FROM orders WHERE payment_status='UNPAID'"
                             " AND status<>'CANCELED' AND substr(created_at,1,10)=? AND store_id=?",
                             today, sid),
        }


def tables():
    """테이블 현황판. 테이블 목록은 tables 모듈에서 가져온다(비활성 포함, 화면에서 구분)."""
    today = store.today()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE substr(created_at,1,10)=? AND store_id=?"
            " AND status NOT IN ('CANCELED','RESERVED')"
            " ORDER BY id DESC", (today, stores.current())
        ).fetchall()
        items = conn.execute(
            "SELECT oi.order_id, oi.name, oi.qty FROM order_items oi"
            " JOIN orders o ON o.id=oi.order_id WHERE substr(o.created_at,1,10)=? AND o.store_id=?",
            (today, stores.current())
        ).fetchall()
    by_order = {}
    for it in items:
        by_order.setdefault(it["order_id"], []).append(f"{it['name']}×{it['qty']}")

    out = []
    for t in tables_mod.list_tables():
        mine = [r for r in rows if r["table_no"] == t["id"]]
        active = [r for r in mine if r["status"] in orders.OPEN_STATUSES]
        unpaid = [r for r in mine if r["payment_status"] == "UNPAID"]
        if active:
            a = active[0]  # 가장 최근 진행 중 주문
            state = a["status"]
            info = {
                "menu": ", ".join(by_order.get(a["id"], []))[:80],
                "since": a["created_at"][11:16],
                "elapsedMin": _elapsed(a["created_at"]) // 60,
                "total": sum(x["total"] for x in active),
                "unpaid": sum(x["total"] for x in unpaid),
                "orders": len(active),
            }
        elif unpaid:
            state = "UNPAID"
            info = {"menu": "결제 확인 필요", "since": unpaid[0]["created_at"][11:16],
                    "elapsedMin": _elapsed(unpaid[0]["created_at"]) // 60,
                    "total": sum(x["total"] for x in unpaid),
                    "unpaid": sum(x["total"] for x in unpaid), "orders": len(unpaid)}
        else:
            state = "IDLE"
            info = {"menu": "", "since": "", "elapsedMin": 0, "total": 0, "unpaid": 0, "orders": 0}
        out.append({
            "table": t["id"], "label": t["label"], "code": t["code"],
            "seats": t["seats"], "active": t["active"],
            "state": state, "stateLabel": STATUS_LABELS.get(state, "빈 테이블"),
            "orders": info["orders"], "menu": info["menu"], "since": info["since"],
            "elapsedMin": info["elapsedMin"],
            "total": info["total"], "unpaid": info["unpaid"],
        })
    return out


def soldout_alerts():
    """품절 연동 알림.

    - 지금 품절인데 조리 대기 주문에 들어 있는 메뉴(손님·홀에 먼저 알려야 함)
    - 품절로 바꿨지만 화면에 표시가 늦을 수 있으니 목록을 함께 준다
    """
    menu = {i["id"]: i for i in catalog.items()}
    sold = [i for i in menu.values() if i["soldout"]]
    sold_ids = {i["id"] for i in sold}
    hits = []
    for o in orders.active():
        bad = [it["name"] for it in o.get("items", []) if it.get("itemId") in sold_ids]
        if bad:
            hits.append({"orderId": o["id"], "orderNo": o["orderNo"], "table": o["table"],
                         "tableLabel": o["tableLabel"], "items": bad})
    return {"soldout": [{"itemId": i["id"], "name": i["name"], "category": i["category"]}
                        for i in sold],
            "affectedOrders": hits}


def summary():
    """주방 화면 상단용 상태 요약(경로·품절 알림 포함)."""
    rows = queue()
    channels = {}
    for o in rows:
        key = o.get("channel") or "table"
        channels[key] = channels.get(key, 0) + 1
    return {**counts(), "channels": channels, "channelLabels": config.CHANNEL_LABELS,
            "alerts": soldout_alerts()}


def serving():
    """서빙 대기(조리완료) 목록. 오래 기다린 순서대로, 경과 시간을 함께 준다."""
    rows = []
    for o in orders.serving():
        o["statusLabel"] = STATUS_LABELS.get(o["status"], o["status"])
        o["servingMin"] = o.get("servingMin", 0)
        o["servingSec"] = o.get("servingSec", 0)
        o["servingLate"] = o["servingMin"] >= config.DELAY_WARN_MIN
        rows.append(o)
    rows.sort(key=lambda x: -x.get("servingSec", 0))
    return rows
