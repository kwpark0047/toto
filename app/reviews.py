"""리뷰(별점·한 줄 평가) 모듈.

책임:
- 손님이 주문 완료 후 별점(1~5)과 한 줄 평가를 남긴다(주문 1건당 1개, 이름·연락처는 받지 않는다)
- 사장님 화면에서 목록·답글 메모·숨김 처리, 평균 별점·최근 추이
- 숨긴 리뷰는 평균에서 빼고, 목록에는 '숨김'으로 남긴다(지우지 않는다)

하지 않는 것: 외부 플랫폼(네이버·구글) 연동, 사진 첨부, 답글 공개 전송.
개인정보를 최소로 받기 위해 연락처·이름 없이 별점과 짧은 글만 저장한다.
"""
from datetime import datetime, timedelta

from . import stores, store, tables

MAX_COMMENT = 120


def _row(r, labels=None):
    return {
        "id": r["id"], "orderId": r["order_id"], "orderNo": r["order_no"] if "order_no" in r.keys() else "",
        "tableNo": r["table_no"], "tableLabel": (labels or {}).get(r["table_no"], f"{r['table_no']}번"),
        "rating": r["rating"], "comment": r["comment"], "hidden": bool(r["hidden"]),
        "reply": r["reply"], "createdAt": r["created_at"], "repliedAt": r["replied_at"],
    }


def _open_order(order_id):
    """리뷰를 남길 수 있는 주문인지 확인한다(우리 매장 주문 + 조리 완료/서빙/결제)."""
    from . import orders
    o = orders.get(int(order_id))
    if (o.get("storeId") or 1) != stores.current():
        raise LookupError("주문을 찾을 수 없습니다")
    if o["status"] == "CANCELED":
        raise ValueError("취소된 주문에는 리뷰를 남길 수 없습니다")
    if o["status"] not in ("DONE", "SERVED") and o["paymentStatus"] != "PAID":
        raise ValueError("조리가 끝난 뒤에 리뷰를 남길 수 있습니다")
    return o


def create(order_id, rating, comment=""):
    order = _open_order(order_id)
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise ValueError("별점을 골라 주세요")
    if not (1 <= rating <= 5):
        raise ValueError("별점은 1~5점 사이로 골라 주세요")
    comment = (comment or "").strip().replace("\n", " ")[:MAX_COMMENT]
    ts = store.now()
    with store.tx() as conn:
        if conn.execute("SELECT 1 FROM reviews WHERE order_id=?", (order["id"],)).fetchone():
            raise ValueError("이 주문에는 이미 리뷰를 남겼습니다")
        cur = conn.execute(
            "INSERT INTO reviews(store_id, order_id, table_no, rating, comment, hidden, reply,"
            " created_at) VALUES(?,?,?,?,?,0,'',?)",
            (stores.current(), order["id"], order["table"], rating, comment, ts))
        store.bump(conn)
        rid = cur.lastrowid
    return get(rid)


def get(review_id):
    with store.read() as conn:
        r = conn.execute(
            "SELECT rv.*, o.order_no FROM reviews rv LEFT JOIN orders o ON o.id=rv.order_id"
            " WHERE rv.id=? AND rv.store_id=?", (review_id, stores.current())).fetchone()
        if not r:
            raise LookupError("리뷰를 찾을 수 없습니다")
    return _row(r, tables.label_map())


def for_order(order_id):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM reviews WHERE order_id=?", (order_id,)).fetchone()
    if not r:
        return None
    return _row(r, tables.label_map())


def list_reviews(limit=200, include_hidden=True):
    sql = ("SELECT rv.*, o.order_no FROM reviews rv LEFT JOIN orders o ON o.id=rv.order_id"
           " WHERE rv.store_id=?")
    if not include_hidden:
        sql += " AND rv.hidden=0"
    sql += " ORDER BY rv.id DESC LIMIT ?"
    with store.read() as conn:
        rows = conn.execute(sql, (stores.current(), int(limit))).fetchall()
    return [_row(r, tables.label_map()) for r in rows]


def reply(review_id, text):
    text = (text or "").strip()[:200]
    with store.tx() as conn:
        cur = conn.execute("UPDATE reviews SET reply=?, replied_at=? WHERE id=? AND store_id=?",
                           (text, store.now() if text else None, review_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("리뷰를 찾을 수 없습니다")
        store.bump(conn)
    return get(review_id)


def set_hidden(review_id, hidden=True):
    with store.tx() as conn:
        cur = conn.execute("UPDATE reviews SET hidden=? WHERE id=? AND store_id=?",
                           (1 if hidden else 0, review_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("리뷰를 찾을 수 없습니다")
        store.bump(conn)
    return get(review_id)


def summary(days=7):
    """평균 별점·건수·분포·최근 추이(숨긴 리뷰는 평균에서 제외)."""
    today = datetime.strptime(store.today(), "%Y-%m-%d")
    start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with store.read() as conn:
        visible = conn.execute(
            "SELECT COUNT(*) c, COALESCE(AVG(rating),0) a FROM reviews"
            " WHERE store_id=? AND hidden=0", (stores.current(),)).fetchone()
        all_count = conn.execute("SELECT COUNT(*) c FROM reviews WHERE store_id=?",
                                 (stores.current(),)).fetchone()["c"]
        dist = {r["rating"]: r["c"] for r in conn.execute(
            "SELECT rating, COUNT(*) c FROM reviews WHERE store_id=? AND hidden=0 GROUP BY rating",
            (stores.current(),)).fetchall()}
        rows = conn.execute(
            "SELECT substr(created_at,1,10) d, COUNT(*) c, AVG(rating) a FROM reviews"
            " WHERE store_id=? AND hidden=0 AND substr(created_at,1,10)>=?"
            " GROUP BY d ORDER BY d", (stores.current(), start)).fetchall()
        replied = conn.execute(
            "SELECT COUNT(*) c FROM reviews WHERE store_id=? AND reply<>''",
            (stores.current(),)).fetchone()["c"]
    by_day = {r["d"]: {"count": r["c"], "avg": round(r["a"], 2)} for r in rows}
    trend = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        trend.append({"date": d, "count": by_day.get(d, {}).get("count", 0),
                      "avg": by_day.get(d, {}).get("avg", 0)})
    return {
        "count": visible["c"], "totalCount": all_count,
        "average": round(visible["a"], 2) if visible["c"] else 0,
        "distribution": {str(k): dist.get(k, 0) for k in range(1, 6)},
        "repliedCount": replied,
        "unrepliedCount": max(0, visible["c"] - replied),
        "trend": trend,
    }
