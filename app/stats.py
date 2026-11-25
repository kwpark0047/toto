"""매출·정산 모듈.

책임:
- 오늘 요약(사장님 대시보드): 매출·주문 수·진행 중 주문·인기 메뉴·미수금
- 기간별(오늘/이번 주/이번 달/임의) 매출: 일별 표, 시간대별 표
- 결제수단별(현금만 실제, 카드는 '미연동' 표시), 인기 메뉴·카테고리 비중
- 취소·할인(포인트 사용)을 실제 결제 금액과 구분해서 표시
- 미수금(결제 전)과 결제 확인 금액을 분리
- CSV 내보내기

매출 = 현금 결제 확인(PAID)된 주문의 결제 금액(total). 취소된 주문은 매출에서 빠지고 따로 센다.
카드·간편결제는 결제(PG) 연동이 없어 항상 0원이며 화면에 '미연동'으로 표시한다.
"""
import csv
import io
from datetime import datetime, timedelta

from . import stores, store


def _bounds(start, end):
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("날짜는 2026-11-01 형식으로 넣어 주세요")
    if e < s:
        raise ValueError("끝 날짜가 시작 날짜보다 빠릅니다")
    if (e - s).days > 366:
        raise ValueError("한 번에 1년까지 볼 수 있습니다")
    return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")


def resolve_period(preset="today", start=None, end=None, date=None):
    """preset(today/week/month/custom) → (시작일, 끝일)."""
    date = date or store.today()
    today = datetime.strptime(date, "%Y-%m-%d")
    preset = (preset or "today").lower()
    if preset == "today":
        return date, date
    if preset == "week":
        monday = today - timedelta(days=today.weekday())
        return monday.strftime("%Y-%m-%d"), date
    if preset == "month":
        return today.replace(day=1).strftime("%Y-%m-%d"), date
    if preset == "custom":
        return _bounds(start or date, end or date)
    raise ValueError("기간은 오늘·이번 주·이번 달·직접 선택 중에서 골라 주세요")


def _rows(conn, start, end):
    return conn.execute(
        "SELECT * FROM orders WHERE store_id=? AND substr(created_at,1,10)>=?"
        " AND substr(created_at,1,10)<=? AND status<>'RESERVED'",
        (stores.current(), start, end)).fetchall()


def _is_paid(r):
    return r["payment_status"] == "PAID" and r["status"] != "CANCELED"


def _total(r):
    return int(r["total"] or 0)


def summary(date=None):
    """하루 요약(사장님 화면 상단·대시보드). 기존 화면이 쓰는 항목 이름을 유지한다."""
    date = date or store.today()
    with store.read() as conn:
        rows = _rows(conn, date, date)
        top = conn.execute(
            "SELECT oi.name, SUM(oi.qty) qty, SUM(oi.qty*oi.price) amount"
            " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " WHERE o.store_id=? AND substr(o.created_at,1,10)=? AND o.payment_status='PAID'"
            " AND o.status<>'CANCELED' GROUP BY oi.name ORDER BY qty DESC LIMIT 5",
            (stores.current(), date)).fetchall()
        hours = conn.execute(
            "SELECT substr(created_at,12,2) h, COUNT(*) c,"
            " SUM(CASE WHEN payment_status='PAID' AND status<>'CANCELED' THEN total ELSE 0 END) amt"
            " FROM orders WHERE store_id=? AND substr(created_at,1,10)=? AND status<>'CANCELED'"
            " GROUP BY h ORDER BY h", (stores.current(), date)).fetchall()

    paid = [r for r in rows if _is_paid(r)]
    unpaid = [r for r in rows if r["payment_status"] == "UNPAID" and r["status"] != "CANCELED"]
    active = [r for r in rows if r["status"] in ("NEW", "ACCEPTED", "COOKING", "DONE")]
    canceled = [r for r in rows if r["status"] == "CANCELED"]
    paid_amount = sum(_total(r) for r in paid)
    discount = sum(int(r["points_used"] or 0) for r in paid)
    return {
        "date": date,
        "orderCount": len([r for r in rows if r["status"] != "CANCELED"]),
        "paidCount": len(paid),
        "paidAmount": paid_amount,
        "unpaidCount": len(unpaid),
        "unpaidAmount": sum(_total(r) for r in unpaid),
        "activeCount": len(active),
        "doneCount": len([r for r in rows if r["status"] == "DONE"]),
        "servedCount": len([r for r in rows if r["status"] == "SERVED"]),
        "canceledCount": len(canceled),
        "canceledAmount": sum(_total(r) for r in canceled),
        "discountAmount": discount,
        "grossAmount": paid_amount + discount,
        "avgTicket": round(paid_amount / len(paid)) if paid else 0,
        "cashAmount": paid_amount,
        "cardAmount": 0,
        "topItems": [{"name": r["name"], "qty": r["qty"], "amount": r["amount"]} for r in top],
        "hourly": [{"hour": r["h"], "count": r["c"], "amount": r["amt"] or 0} for r in hours],
    }


def period(start=None, end=None):
    """기간 매출: 일별 표 + 합계 + 시간대별 + 결제수단 + 인기 메뉴·카테고리 비중."""
    start, end = _bounds(start or store.today(), end or store.today())
    with store.read() as conn:
        rows = _rows(conn, start, end)
        items = conn.execute(
            "SELECT oi.name, oi.item_id, SUM(oi.qty) qty, SUM(oi.qty*oi.price) amount"
            " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " WHERE o.store_id=? AND substr(o.created_at,1,10)>=? AND substr(o.created_at,1,10)<=?"
            " AND o.payment_status='PAID' AND o.status<>'CANCELED'"
            " GROUP BY oi.name ORDER BY amount DESC", (stores.current(), start, end)).fetchall()
        cats = conn.execute(
            "SELECT COALESCE(c.name,'기타') cat, SUM(oi.qty) qty, SUM(oi.qty*oi.price) amount"
            " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
            " LEFT JOIN menu_items m ON m.id=oi.item_id"
            " LEFT JOIN categories c ON c.id=m.category_id"
            " WHERE o.store_id=? AND substr(o.created_at,1,10)>=? AND substr(o.created_at,1,10)<=?"
            " AND o.payment_status='PAID' AND o.status<>'CANCELED'"
            " GROUP BY cat ORDER BY amount DESC", (stores.current(), start, end)).fetchall()
        hours = conn.execute(
            "SELECT substr(created_at,12,2) h, COUNT(*) c,"
            " SUM(CASE WHEN payment_status='PAID' AND status<>'CANCELED' THEN total ELSE 0 END) amt"
            " FROM orders WHERE store_id=? AND substr(created_at,1,10)>=? AND substr(created_at,1,10)<=?"
            " AND status<>'CANCELED' GROUP BY h", (stores.current(), start, end)).fetchall()

    paid = [r for r in rows if _is_paid(r)]
    unpaid = [r for r in rows if r["payment_status"] == "UNPAID" and r["status"] != "CANCELED"]
    canceled = [r for r in rows if r["status"] == "CANCELED"]
    paid_amount = sum(_total(r) for r in paid)
    discount = sum(int(r["points_used"] or 0) for r in paid)

    # 일별 표(주문이 없는 날도 0으로 채운다)
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    days = []
    cur = s
    while cur <= e:
        d = cur.strftime("%Y-%m-%d")
        day_rows = [r for r in rows if r["created_at"][:10] == d]
        day_paid = [r for r in day_rows if _is_paid(r)]
        day_unpaid = [r for r in day_rows if r["payment_status"] == "UNPAID" and r["status"] != "CANCELED"]
        day_canceled = [r for r in day_rows if r["status"] == "CANCELED"]
        days.append({
            "date": d, "weekday": "월화수목금토일"[cur.weekday()],
            "orderCount": len([r for r in day_rows if r["status"] != "CANCELED"]),
            "paidCount": len(day_paid),
            "paidAmount": sum(_total(r) for r in day_paid),
            "unpaidCount": len(day_unpaid),
            "unpaidAmount": sum(_total(r) for r in day_unpaid),
            "canceledCount": len(day_canceled),
            "canceledAmount": sum(_total(r) for r in day_canceled),
            "discountAmount": sum(int(r["points_used"] or 0) for r in day_paid),
        })
        cur += timedelta(days=1)

    hour_map = {r["h"]: {"count": r["c"], "amount": r["amt"] or 0} for r in hours}
    hourly = []
    for h in range(24):
        key = f"{h:02d}"
        entry = hour_map.get(key, {"count": 0, "amount": 0})
        hourly.append({"hour": key, "label": f"{key}시", "count": entry["count"],
                       "amount": entry["amount"]})
    peak = max(hourly, key=lambda x: x["amount"]) if hours else None

    item_total = sum(r["amount"] for r in items) or 1
    cat_total = sum(r["amount"] for r in cats) or 1
    return {
        "start": start, "end": end,
        "totals": {
            "orderCount": len([r for r in rows if r["status"] != "CANCELED"]),
            "paidCount": len(paid),
            "paidAmount": paid_amount,
            "unpaidCount": len(unpaid),
            "unpaidAmount": sum(_total(r) for r in unpaid),
            "canceledCount": len(canceled),
            "canceledAmount": sum(_total(r) for r in canceled),
            "discountAmount": discount,
            "grossAmount": paid_amount + discount,
            "avgTicket": round(paid_amount / len(paid)) if paid else 0,
            "cashAmount": paid_amount,
            "cardAmount": 0,
        },
        "days": days,
        "hourly": hourly,
        "peakHour": peak if peak and peak["amount"] else None,
        "paymentMethods": [
            {"method": "CASH", "label": "현금", "count": len(paid), "amount": paid_amount,
             "connected": True, "note": ""},
            {"method": "CARD", "label": "카드·간편결제", "count": 0, "amount": 0,
             "connected": False, "note": "PG 미연동 — 실제 결제 없음"},
        ],
        "topItems": [
            {"name": r["name"], "qty": r["qty"], "amount": r["amount"],
             "share": round(r["amount"] * 100 / item_total, 1)} for r in items[:10]
        ],
        "categories": [
            {"name": r["cat"], "qty": r["qty"], "amount": r["amount"],
             "share": round(r["amount"] * 100 / cat_total, 1)} for r in cats
        ],
    }


def dashboard(date=None):
    """사장님 대시보드: 오늘 매출·주문 수·진행 중 주문·인기 메뉴."""
    date = date or store.today()
    s = summary(date)
    week = period(*resolve_period("week", date=date))
    month = period(*resolve_period("month", date=date))
    return {
        "date": date,
        "today": s,
        "week": {"paidAmount": week["totals"]["paidAmount"],
                 "orderCount": week["totals"]["orderCount"]},
        "month": {"paidAmount": month["totals"]["paidAmount"],
                  "orderCount": month["totals"]["orderCount"]},
        "serverTime": store.now(),
    }


def revenue_csv(start=None, end=None):
    data = period(start, end)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["날짜", "요일", "주문", "결제건", "결제확인금액", "미수건", "미수금", "취소건",
                "취소금액", "할인(포인트)"])
    for d in data["days"]:
        w.writerow([d["date"], d["weekday"], d["orderCount"], d["paidCount"], d["paidAmount"],
                    d["unpaidCount"], d["unpaidAmount"], d["canceledCount"], d["canceledAmount"],
                    d["discountAmount"]])
    t = data["totals"]
    w.writerow([])
    w.writerow(["합계", "", t["orderCount"], t["paidCount"], t["paidAmount"], t["unpaidCount"],
                t["unpaidAmount"], t["canceledCount"], t["canceledAmount"], t["discountAmount"]])
    w.writerow([])
    w.writerow(["시간대", "주문", "결제확인금액"])
    for h in data["hourly"]:
        if h["count"]:
            w.writerow([h["label"], h["count"], h["amount"]])
    w.writerow([])
    w.writerow(["인기 메뉴", "수량", "금액", "비중(%)"])
    for i in data["topItems"]:
        w.writerow([i["name"], i["qty"], i["amount"], i["share"]])
    w.writerow([])
    w.writerow(["카테고리", "수량", "금액", "비중(%)"])
    for c in data["categories"]:
        w.writerow([c["name"], c["qty"], c["amount"], c["share"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), f"revenue-{data['start']}~{data['end']}.csv"
