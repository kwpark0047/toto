"""예약 모듈.

책임:
- 사장님이 직접 예약을 등록(날짜·시간·인원·연락처·메모·테이블 선택)
- 손님은 QR 링크(/reserve)로 '예약 신청'만 한다(확정은 사장님이 직접)
- 상태: 신청(PENDING) → 확정(CONFIRMED) → 도착(ARRIVED) / 노쇼(NOSHOW) / 취소(CANCELED)
- 일자별 목록·월 캘린더·오늘 예약 요약

하지 않는 것: 문자·카카오 알림(미연결), 자동 확정, 좌석 자동 배정.
개인정보: 연락처는 예약 처리 목적으로만 쓰고, 지난 예약은 목록에서 상태만 남긴다(자동 삭제는 추후).
"""
import re
import secrets
from datetime import datetime, timedelta

from . import stores, store, tables

STATUSES = {
    "PENDING": "신청",
    "CONFIRMED": "확정",
    "ARRIVED": "도착",
    "NOSHOW": "노쇼",
    "CANCELED": "취소",
}
FLOW = {
    "PENDING": {"CONFIRMED", "CANCELED"},
    "CONFIRMED": {"ARRIVED", "NOSHOW", "CANCELED", "PENDING"},
    "ARRIVED": set(),
    "NOSHOW": {"CONFIRMED"},
    "CANCELED": {"PENDING"},
}
CLOSED = ("ARRIVED", "NOSHOW", "CANCELED")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _norm_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) in (10, 11):
        return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
    return (phone or "").strip()


def _check_date(value):
    value = (value or "").strip()
    if not DATE_RE.match(value):
        raise ValueError("날짜는 2026-11-30 형식으로 넣어 주세요")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("없는 날짜입니다")
    return value


def _check_time(value):
    value = (value or "").strip()
    if not TIME_RE.match(value):
        raise ValueError("시간은 18:30 형식으로 넣어 주세요")
    h, m = int(value[:2]), int(value[3:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("시간이 올바르지 않습니다")
    return f"{h:02d}:{m:02d}"


def _row(r, label=None):
    return {
        "id": r["id"], "token": r["token"] if "token" in r.keys() else "",
        "date": r["res_date"], "time": r["res_time"], "partySize": r["party_size"],
        "name": r["name"], "phone": r["phone"], "memo": r["memo"],
        "status": r["status"], "statusLabel": STATUSES.get(r["status"], r["status"]),
        "tableId": r["table_id"], "tableLabel": (label or {}).get(r["table_id"], ""),
        "consent": bool(r["consent"]), "createdAt": r["created_at"],
        "updatedAt": r["updated_at"], "past": r["res_date"] < store.today(),
        "closed": r["status"] in CLOSED,
        "dateTime": f"{r['res_date']} {r['res_time']}",
    }


def create(date, time, party_size, name, phone, memo="", consent=False, table_id=None,
           status="PENDING", public=True):
    """예약 등록. public=True(손님 신청)이면 동의가 필요하고 상태는 '신청'이다."""
    date = _check_date(date)
    time = _check_time(time)
    name = (name or "").strip()
    if not name:
        raise ValueError("이름을 넣어 주세요")
    if len(name) > 20:
        raise ValueError("이름은 20자 이내로 넣어 주세요")
    phone = _norm_phone(phone)
    if len("".join(ch for ch in phone if ch.isdigit())) < 10:
        raise ValueError("연락처를 정확히 넣어 주세요 (예: 010-1234-5678)")
    if public and not consent:
        raise ValueError("연락처 수집·이용에 동의해 주세요")
    try:
        party = int(party_size or 2)
    except (TypeError, ValueError):
        raise ValueError("인원은 숫자로 넣어 주세요")
    if not (1 <= party <= 30):
        raise ValueError("인원은 1~30명 사이로 넣어 주세요")
    if status not in STATUSES:
        raise ValueError("예약 상태가 올바르지 않습니다")
    if public:
        status = "PENDING"
    if date < store.today():
        raise ValueError("지난 날짜로는 예약을 받을 수 없습니다")
    label = None
    if table_id:
        t = tables.get(int(table_id))
        if not t["active"]:
            raise ValueError(f"'{t['label']}'은(는) 비활성 테이블입니다")
        table_id, label = t["id"], t["label"]
    token = secrets.token_urlsafe(12)
    ts = store.now()
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO reservations(store_id, token, res_date, res_time, party_size, name, phone,"
            " memo, status, table_id, consent, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (stores.current(), token, date, time, party, name, phone, (memo or "").strip()[:200],
             status, table_id, 1 if (consent or not public) else 0, ts, ts))
        store.bump(conn)
        rid = cur.lastrowid
    out = get(rid)
    out["tableLabel"] = label or out.get("tableLabel") or ""
    return out


def get(reservation_id):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM reservations WHERE id=? AND store_id=?",
                         (reservation_id, stores.current())).fetchone()
        if not r:
            raise LookupError("예약을 찾을 수 없습니다")
    return _row(r, tables.label_map())


def by_token(token):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM reservations WHERE token=?", (token,)).fetchone()
        if not r:
            raise LookupError("예약을 찾을 수 없습니다")
    with stores.use(r["store_id"]):
        label = tables.label_map()
    return _row(r, label)


def list_reservations(date=None, month=None, status=None, include_closed=True):
    sql = "SELECT * FROM reservations WHERE store_id=?"
    params = [stores.current()]
    if date:
        sql += " AND res_date=?"
        params.append(_check_date(date))
    if month:
        sql += " AND substr(res_date,1,7)=?"
        params.append(month[:7])
    if status:
        sql += " AND status=?"
        params.append(status)
    elif not include_closed:
        sql += " AND status NOT IN ('CANCELED')"
    sql += " ORDER BY res_date, res_time, id"
    labels = tables.label_map()
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r, labels) for r in rows]


def calendar(month=None):
    """월 캘린더용: 날짜별 건수·상태 요약."""
    month = month or store.today()[:7]
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValueError("월은 2026-11 형식으로 넣어 주세요")
    with store.read() as conn:
        rows = conn.execute(
            "SELECT res_date, status, COUNT(*) c FROM reservations"
            " WHERE store_id=? AND substr(res_date,1,7)=? GROUP BY res_date, status",
            (stores.current(), month)).fetchall()
    days = {}
    for r in rows:
        d = days.setdefault(r["res_date"], {"total": 0, "byStatus": {}})
        d["total"] += r["c"]
        d["byStatus"][r["status"]] = r["c"]
    return {"month": month, "days": days}


def set_status(reservation_id, status):
    if status not in STATUSES:
        raise ValueError("예약 상태가 올바르지 않습니다")
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM reservations WHERE id=? AND store_id=?",
                         (reservation_id, stores.current())).fetchone()
        if not r:
            raise LookupError("예약을 찾을 수 없습니다")
        if status == r["status"]:
            pass
        elif status not in FLOW.get(r["status"], set()):
            raise ValueError(
                f"'{STATUSES.get(r['status'], r['status'])}'에서 "
                f"'{STATUSES[status]}'(으)로 바꿀 수 없습니다")
        conn.execute("UPDATE reservations SET status=?, updated_at=? WHERE id=?",
                     (status, store.now(), reservation_id))
        store.bump(conn)
    return get(reservation_id)


def assign_table(reservation_id, table_id=None):
    label = ""
    tid = None
    if table_id:
        t = tables.get(int(table_id))
        if not t["active"]:
            raise ValueError(f"'{t['label']}'은(는) 비활성 테이블입니다")
        tid, label = t["id"], t["label"]
    with store.tx() as conn:
        cur = conn.execute("UPDATE reservations SET table_id=?, updated_at=? WHERE id=? AND store_id=?",
                           (tid, store.now(), reservation_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("예약을 찾을 수 없습니다")
        store.bump(conn)
    out = get(reservation_id)
    out["tableLabel"] = label
    return out


def today():
    rows = list_reservations(date=store.today())
    active = [r for r in rows if r["status"] in ("PENDING", "CONFIRMED")]
    return {
        "date": store.today(),
        "count": len(rows),
        "activeCount": len(active),
        "pendingCount": len([r for r in rows if r["status"] == "PENDING"]),
        "arrivedCount": len([r for r in rows if r["status"] == "ARRIVED"]),
        "partyTotal": sum(r["partySize"] for r in active),
        "rows": rows,
    }


def upcoming(days=7):
    end = (datetime.strptime(store.today(), "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM reservations WHERE store_id=? AND res_date>=? AND res_date<=?"
            " AND status IN ('PENDING','CONFIRMED') ORDER BY res_date, res_time",
            (stores.current(), store.today(), end)).fetchall()
    labels = tables.label_map()
    return [_row(r, labels) for r in rows]
