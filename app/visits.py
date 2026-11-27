"""QR·NFC 유입 기록 모듈.

책임: 손님이 매장 메뉴판을 QR로 열었는지 NFC 태그로 열었는지 세어
사장님 화면에서 비교할 수 있게 한다(테이블별·경로별).

기록은 매장·테이블·경로(via)만 남기고 개인정보(전화·기기)는 남기지 않는다.
"""
from . import store, stores

VIAS = {"qr": "QR", "nfc": "NFC", "link": "링크", "direct": "직접 주소"}


def _via(value):
    v = (value or "").strip().lower()
    if v in VIAS:
        return v
    return "qr"


def record(store_id, table_id=None, via="qr", path=""):
    sid = int(store_id)
    if not stores.exists(sid):
        raise LookupError("매장을 찾을 수 없습니다")
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO visit_events(store_id, table_id, via, path, created_at) VALUES(?,?,?,?,?)",
            (sid, int(table_id) if table_id else None, _via(via), (path or "")[:80], store.now()))
        store.bump(conn)
    return {"recorded": True, "storeId": sid, "via": _via(via)}


def summary(store_id=None, date=None, days=7):
    """오늘과 최근 N일의 QR/NFC 유입 비교."""
    sid = int(store_id or stores.current())
    date = date or store.today()
    try:
        days = max(1, min(90, int(days or 7)))
    except (TypeError, ValueError):
        days = 7
    with store.read() as conn:
        today_rows = conn.execute(
            "SELECT via, COUNT(*) c FROM visit_events WHERE store_id=? AND substr(created_at,1,10)=?"
            " GROUP BY via", (sid, date)).fetchall()
        total_today = conn.execute(
            "SELECT COUNT(*) c FROM visit_events WHERE store_id=? AND substr(created_at,1,10)=?",
            (sid, date)).fetchone()["c"]
        recent = conn.execute(
            "SELECT substr(created_at,1,10) d, via, COUNT(*) c FROM visit_events"
            " WHERE store_id=? AND substr(created_at,1,10)>=? GROUP BY d, via ORDER BY d",
            (sid, store.today()[:10][:8] + "01")).fetchall()
        by_table = conn.execute(
            "SELECT v.table_id, t.label, v.via, COUNT(*) c FROM visit_events v"
            " LEFT JOIN dining_tables t ON t.id=v.table_id"
            " WHERE v.store_id=? AND substr(v.created_at,1,10)>=?"
            " GROUP BY v.table_id, t.label, v.via ORDER BY c DESC LIMIT 50",
            (sid, _start_day(date, days))).fetchall()
    counts = {v: 0 for v in VIAS}
    for r in today_rows:
        counts[r["via"]] = counts.get(r["via"], 0) + r["c"]
    series = {}
    for r in recent:
        series.setdefault(r["d"], {v: 0 for v in VIAS})[r["via"]] = r["c"]
    tables = {}
    for r in by_table:
        key = r["table_id"] or 0
        item = tables.setdefault(key, {"tableId": key, "label": r["label"] or "매장 메뉴판",
                                       **{v: 0 for v in VIAS}})
        item[r["via"]] = r["c"]
    return {
        "storeId": sid, "date": date, "days": days,
        "today": {"total": total_today, "byVia": counts,
                  "nfcShare": round(counts.get("nfc", 0) * 100.0 / total_today, 1) if total_today else 0},
        "series": [{"date": d, **vals} for d, vals in sorted(series.items())],
        "byTable": sorted(tables.values(), key=lambda x: sum(x[v] for v in VIAS), reverse=True),
        "viaLabels": VIAS,
    }


def _start_day(date, days):
    from datetime import date as _date, timedelta
    try:
        d = _date.fromisoformat(date)
    except ValueError:
        return date
    return (d - timedelta(days=days - 1)).isoformat()
