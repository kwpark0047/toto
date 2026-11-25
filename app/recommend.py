"""추천·예상시간 모듈.

책임:
- '또 시킬까요?' : 이 테이블(브라우저)에서 최근에 주문한 메뉴를 다시 보여 준다.
- '함께 많이 시키는 메뉴' : 같은 주문에 함께 담긴 조합 통계(표본이 적으면 추천하지 않는다).
- '지금 주문하면 약 N분' : 주방 대기 건수와 최근 평균 조리시간으로 예상 시간·혼잡도를 계산한다.
  표본이 적으면 계산하지 않고 '계산 중'으로 돌려준다.

개인정보: 테이블 단위 주문 이력만 쓴다(이름·연락처와 분리).
"""
from . import catalog, orders, store

MIN_PAIR_SAMPLE = 3      # 조합 추천 최소 표본
MIN_ESTIMATE_SAMPLE = 2  # 예상 시간 최소 표본


def _items_map():
    return {i["id"]: i for i in catalog.items()}


def reorder(table_id=None, limit=6):
    """이 테이블에서 최근 주문한 메뉴(최근 순, 중복 제거)."""
    if not table_id:
        return []
    with store.read() as conn:
        rows = conn.execute(
            "SELECT oi.item_id, MAX(o.id) last_order FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " WHERE o.table_no=? AND o.status<>'CANCELED' AND o.status<>'RESERVED'"
            " GROUP BY oi.item_id ORDER BY last_order DESC LIMIT ?", (int(table_id), limit)
        ).fetchall()
    items = _items_map()
    out = []
    for r in rows:
        it = items.get(r["item_id"])
        if it:
            out.append(it)
    return out


def pairs(item_ids, limit=2):
    """같은 주문에 함께 담긴 횟수가 많은 메뉴(표본 MIN_PAIR_SAMPLE 이상)."""
    ids = [int(i) for i in (item_ids or []) if str(i).isdigit()]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    with store.read() as conn:
        rows = conn.execute(
            f"SELECT oi2.item_id, COUNT(*) c FROM order_items oi1"
            f" JOIN order_items oi2 ON oi2.order_id = oi1.order_id AND oi2.item_id <> oi1.item_id"
            f" JOIN orders o ON o.id = oi1.order_id"
            f" WHERE oi1.item_id IN ({marks}) AND o.status <> 'CANCELED' AND o.status <> 'RESERVED'"
            f" AND oi2.item_id NOT IN ({marks})"
            f" GROUP BY oi2.item_id HAVING c >= ? ORDER BY c DESC LIMIT ?",
            (*ids, *ids, MIN_PAIR_SAMPLE, limit)).fetchall()
    items = _items_map()
    out = []
    for r in rows:
        it = items.get(r["item_id"])
        if it and not it["soldout"]:
            it = dict(it)
            it["togetherCount"] = r["c"]
            out.append(it)
    return out


def estimate():
    """지금 주문하면 걸리는 시간(분)과 혼잡도. 표본이 적으면 None."""
    with store.read() as conn:
        waiting = conn.execute(
            "SELECT COUNT(*) c FROM orders WHERE status IN ('NEW','ACCEPTED','COOKING')").fetchone()["c"]
        avg = orders.cook_estimate(conn)
    if avg is None:
        return {"minutes": None, "level": "unknown", "label": "계산 중",
                "queue": waiting, "avgCookMinutes": None}
    # 대기 주문이 많을수록 늘어난다(조리대 1개 가정: 앞 주문의 절반씩 겹친다고 본다)
    minutes = max(1, round(avg * max(1, (waiting + 1) / 2)))
    if minutes <= avg:
        level, label = "calm", "여유"
    elif minutes <= avg * 2:
        level, label = "normal", "보통"
    else:
        level, label = "busy", "혼잡"
    return {"minutes": int(minutes), "level": level, "label": label,
            "queue": waiting, "avgCookMinutes": avg}


def for_customer(table_id=None, cart_ids=None):
    return {
        "reorder": reorder(table_id),
        "pairs": pairs(cart_ids or []),
        "estimate": estimate(),
    }
