"""직원 호출(손님 요청) 모듈.

책임: 손님이 테이블에서 부른 직원 호출을 접수·처리한다.
같은 테이블에서 손님이 다시 부르면 새로 만들지 않고 기존 호출을 그대로 쓴다(중복 방지).
사장님·주방 화면은 OPEN 상태 목록을 폴링으로 보여 주고, '처리 완료'를 누르면 닫힌다.
"""
from . import stores, store, tables

STATUS = {"OPEN": "호출 중", "DONE": "처리 완료"}


def _row(r):
    return {
        "id": r["id"], "tableId": r["table_no"],
        "tableLabel": r["table_label"] or f"{r['table_no']}번",
        "status": r["status"], "statusLabel": STATUS.get(r["status"], r["status"]),
        "note": r["note"], "createdAt": r["created_at"], "doneAt": r["done_at"],
        "elapsedMin": _elapsed(r["created_at"]),
    }


def _elapsed(ts):
    from datetime import datetime
    try:
        a = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0
    return max(0, int((datetime.now(store.TZ).replace(tzinfo=None) - a).total_seconds() // 60))


def call(table_id, note=""):
    """손님 호출. 같은 테이블에 열린 호출이 있으면 그것을 돌려준다."""
    t = tables.get(int(table_id))
    if not t["active"]:
        raise ValueError("지금은 호출을 받지 않는 테이블입니다")
    with store.tx() as conn:
        found = conn.execute(
            "SELECT * FROM service_calls WHERE table_no=? AND status='OPEN' AND store_id=?"
            " ORDER BY id DESC LIMIT 1", (t["id"], stores.current())).fetchone()
        if found:
            return {"call": _row(found), "reused": True}
        cur = conn.execute(
            "INSERT INTO service_calls(store_id, table_no, table_label, status, note, created_at)"
            " VALUES(?,?,?,'OPEN',?,?)",
            (stores.current(), t["id"], t["label"], (note or "")[:80], store.now()))
        store.bump(conn)
        r = conn.execute("SELECT * FROM service_calls WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"call": _row(r), "reused": False}


def done(call_id, staff_id=None):
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM service_calls WHERE id=?", (call_id,)).fetchone()
        if not r:
            raise LookupError("호출을 찾을 수 없습니다")
        if r["status"] == "DONE":
            return _row(r)
        conn.execute("UPDATE service_calls SET status='DONE', done_at=?, staff_id=? WHERE id=?",
                     (store.now(), staff_id, call_id))
        store.bump(conn)
        r = conn.execute("SELECT * FROM service_calls WHERE id=?", (call_id,)).fetchone()
        return _row(r)


def open_calls(table_id=None):
    sql = "SELECT * FROM service_calls WHERE status='OPEN' AND store_id=?"
    params = [stores.current()]
    if table_id:
        sql += " AND table_no=?"
        params.append(int(table_id))
    sql += " ORDER BY id"
    with store.read() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


def today_summary():
    with store.read() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM service_calls WHERE substr(created_at,1,10)=?"
            " AND store_id=? GROUP BY status", (store.today(), stores.current())).fetchall()
    by = {r["status"]: r["c"] for r in rows}
    return {"open": by.get("OPEN", 0), "done": by.get("DONE", 0),
            "total": by.get("OPEN", 0) + by.get("DONE", 0)}


def table_state(table_id):
    """손님 화면용: 이 테이블에 열린 호출."""
    rows = open_calls(table_id)
    return rows[0] if rows else None
