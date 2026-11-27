"""웨이팅(대기 접수) 모듈 — 독립 모듈.

책임: 매장 대기 접수(이름·전화번호·인원) → 대기번호 발급 → 호출/입장/취소/노쇼,
고객이 자기 순서를 다시 볼 수 있는 개인 링크, 디스플레이용 보드 데이터, 예상 대기시간 계산.

경계:
- 다른 모듈은 이 모듈의 테이블(waiting_tickets)을 직접 읽지 않는다. 주문·테이블·회원과는
  공개 함수로만 연결한다(입장 시 테이블 존재 확인은 tables.get, 회원 기록은 customers.upsert).
- 문자·카카오 발송은 하지 않는다. notifier 모듈(채널 구조)이 연결 전까지 "미연결" 기록만 남긴다.

개인정보: 이름·전화번호는 대기 처리 목적으로만 쓰고, 입장·취소·노쇼 후 하루가 지나면
자동으로 지운다(cleanup). 번호 추측이 어렵도록 개인 링크에는 임의 토큰을 쓴다.
"""
import re
import secrets
from datetime import datetime, timedelta

from . import customers, notifier, settings, stores, store, tables

FMT = "%Y-%m-%d %H:%M:%S"
STATUSES = {"WAITING": "대기", "CALLED": "호출 중", "SEATED": "입장", "CANCELED": "취소", "NOSHOW": "노쇼"}
CLOSED = ("SEATED", "CANCELED", "NOSHOW")
KEEP_HOURS = 24          # 입장·취소 후 개인정보를 지우기까지
MAX_PARTY = 20


def _notify(channel, event, ticket):
    """문자·카카오는 연결 전까지 '미연결' 기록만 남긴다(실제 전송 없음). 브라우저는 화면이 띄운다."""
    try:
        return notifier.send(channel, event, ticket)
    except ValueError:
        return None


def _now():
    return store.now()


def _parse(ts):
    try:
        return datetime.strptime((ts or "")[:19], FMT)
    except ValueError:
        return None


def normalize_phone(phone):
    digits = re.sub(r"[^0-9]", "", phone or "")
    if not digits.startswith("0") or len(digits) not in (10, 11):
        raise ValueError("전화번호를 정확히 넣어 주세요 (예: 010-1234-5678)")
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _mask_phone(phone):
    d = re.sub(r"[^0-9]", "", phone or "")
    return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 8 else ""


def _row(r, position=None, ahead=None):
    return {
        "id": r["id"], "storeId": r["store_id"] if "store_id" in r.keys() else 1,
        "ticketNo": r["ticket_no"], "token": r["token"], "name": r["name"],
        "phone": r["phone"], "phoneMasked": _mask_phone(r["phone"]), "partySize": r["party_size"],
        "status": r["status"], "statusLabel": STATUSES.get(r["status"], r["status"]),
        "createdAt": r["created_at"], "calledAt": r["called_at"], "seatedAt": r["seated_at"],
        "closedAt": r["closed_at"], "tableId": r["table_id"], "note": r["note"],
        "waitMinutes": max(0, int((( _parse(r["closed_at"] or store.now())) - _parse(r["created_at"])).total_seconds() // 60))
        if _parse(r["created_at"]) else 0,
        "expired": bool(r["purged"]), "consent": bool(r["consent"]),
        "position": position, "ahead": ahead,
    }


def _today():
    return store.today()


def _next_no(conn):
    # 번호는 매장별로 따로 센다(1번 매장은 기존처럼 날짜만, 다른 매장은 날짜:매장)
    sid = stores.current()
    date = _today() if sid == 1 else f"{_today()}:{sid}"
    row = conn.execute("SELECT last_no FROM waiting_counters WHERE date=?", (date,)).fetchone()
    nxt = (row["last_no"] if row else 0) + 1
    conn.execute(
        "INSERT INTO waiting_counters(date, last_no) VALUES(?,?)"
        " ON CONFLICT(date) DO UPDATE SET last_no=excluded.last_no", (date, nxt))
    return f"A-{nxt}"


def _active_for_phone(conn, phone):
    return conn.execute(
        "SELECT * FROM waiting_tickets WHERE phone=? AND status IN ('WAITING','CALLED')"
        " AND store_id=? ORDER BY id DESC LIMIT 1", (phone, stores.current())).fetchone()


def config():
    """웨이팅 ON/OFF·안내 문구·한 팀 최대 인원(매장 설정)."""
    return settings.waiting_conf()


def create(name, phone, party_size, consent, note=""):
    """대기 접수. 같은 번호로 다시 접수하면 기존 대기를 그대로 돌려준다."""
    conf = config()
    if not conf.get("enabled"):
        raise ValueError("지금은 웨이팅을 받지 않습니다. 매장에 문의해 주세요")
    limit_party = int(conf.get("maxParty") or MAX_PARTY)
    name = (name or "").strip()
    if not name:
        raise ValueError("이름을 넣어 주세요")
    if len(name) > 20:
        raise ValueError("이름은 20자 이내로 넣어 주세요")
    phone = normalize_phone(phone)
    if not consent:
        raise ValueError("전화번호 수집·이용에 동의해 주세요")
    try:
        party = int(party_size or 1)
    except (TypeError, ValueError):
        raise ValueError("인원은 숫자로 넣어 주세요")
    if not (1 <= party <= min(MAX_PARTY, limit_party)):
        raise ValueError(f"인원은 1~{min(MAX_PARTY, limit_party)}명 사이로 넣어 주세요")
    cleanup()
    with store.tx() as conn:
        found = _active_for_phone(conn, phone)
        if found:
            store.bump(conn)
            return {"ticket": _status_row(conn, found), "reused": True}
        token = secrets.token_urlsafe(16)
        cur = conn.execute(
            "INSERT INTO waiting_tickets(store_id, ticket_no, token, name, phone, party_size, consent,"
            " status, created_at, note, purged) VALUES(?,?,?,?,?,?,?,'WAITING',?,?,0)",
            (stores.current(), _next_no(conn), token, name, phone, party, 1, _now(),
             (note or "").strip()[:200]))
        store.bump(conn)
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (cur.lastrowid,)).fetchone()
        ticket = _status_row(conn, r)
    return {"ticket": ticket, "reused": False}


def _waiting_rows(conn):
    return conn.execute(
        "SELECT * FROM waiting_tickets WHERE status='WAITING' AND purged=0 AND store_id=?"
        " ORDER BY id", (stores.current(),)).fetchall()


def _status_row(conn, r):
    t = _row(r)
    if r["status"] == "WAITING":
        waiting = _waiting_rows(conn)
        ids = [x["id"] for x in waiting]
        pos = ids.index(r["id"]) + 1 if r["id"] in ids else None
        t["position"] = pos
        t["ahead"] = (pos - 1) if pos else None
        t["estimatedMinutes"] = None
        est = estimate_minutes(conn)
        t["estimateAvailable"] = est is not None
        if est is not None and pos:
            t["estimatedMinutes"] = int(est * max(0, pos - 1))
    elif r["status"] == "CALLED":
        t["position"] = 0
        t["ahead"] = 0
        t["estimateAvailable"] = True
        t["estimatedMinutes"] = 0
    return t


def by_token(token):
    cleanup()
    with store.read() as conn:
        r = conn.execute("SELECT * FROM waiting_tickets WHERE token=?", (token,)).fetchone()
        if not r:
            raise LookupError("대기 정보를 찾을 수 없습니다. 번호가 맞는지 확인해 주세요")
        sid = r["store_id"] if "store_id" in r.keys() else 1
        with stores.use(sid):
            return _status_row(conn, r)


def by_phone(phone):
    cleanup()
    phone = normalize_phone(phone)
    with store.read() as conn:
        r = conn.execute(
            "SELECT * FROM waiting_tickets WHERE phone=? AND store_id=? ORDER BY id DESC LIMIT 1",
            (phone, stores.current())
        ).fetchone()
        if not r:
            raise LookupError("이 번호로 오늘 접수한 대기가 없습니다")
        return _status_row(conn, r)


def estimate_minutes(conn=None):
    """최근 입장 처리된 대기들의 평균 대기시간(분). 표본이 2건 미만이면 None(계산 중)."""
    close = False
    if conn is None:
        conn, close = store.connect(), True
    try:
        rows = conn.execute(
            "SELECT created_at, seated_at FROM waiting_tickets WHERE status='SEATED'"
            " AND seated_at IS NOT NULL AND store_id=? ORDER BY id DESC LIMIT 10",
            (stores.current(),)).fetchall()
    finally:
        if close:
            conn.close()
    spans = []
    for r in rows:
        a, b = _parse(r["created_at"]), _parse(r["seated_at"])
        if a and b:
            spans.append(max(0, (b - a).total_seconds() / 60))
    if len(spans) < 2:
        return None
    return sum(spans) / len(spans)


def _today_counts(conn):
    day = _today()
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM waiting_tickets WHERE substr(created_at,1,10)=?"
        " AND store_id=? GROUP BY status", (day, stores.current())).fetchall()
    base = {k: 0 for k in STATUSES}
    for r in rows:
        base[r["status"]] = r["c"]
    return base


def board():
    """매장 앞 디스플레이. 매장 이름은 api 가 settings 에서 붙인다."""
    cleanup()
    with store.read() as conn:
        waiting = _waiting_rows(conn)
        called = conn.execute(
            "SELECT * FROM waiting_tickets WHERE status='CALLED' AND purged=0 AND store_id=?"
            " ORDER BY called_at", (stores.current(),)
        ).fetchall()
        counts = _today_counts(conn)
        est = estimate_minutes(conn)
    return {
        "called": [_row(r) for r in called],
        "waiting": [_row(r, i + 1) for i, r in enumerate(waiting)],
        "waitingCount": len(waiting),
        "calledCount": len(called),
        "partyTotal": sum(r["party_size"] for r in waiting),
        "estimateMinutes": round(est) if est is not None else None,
        "counts": counts,
        "serverTime": store.now(),
    }


def admin_list():
    cleanup()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM waiting_tickets WHERE substr(created_at,1,10)=? AND purged=0"
            " AND store_id=?"
            " ORDER BY CASE status WHEN 'CALLED' THEN 0 WHEN 'WAITING' THEN 1 ELSE 2 END, id",
            (_today(), stores.current())).fetchall()
        counts = _today_counts(conn)
        est = estimate_minutes(conn)
        waiting = [r for r in rows if r["status"] == "WAITING"]
        waiting_ids = [r["id"] for r in waiting]
        reserved = {row["reserved_for"]: row["c"] for row in conn.execute(
            "SELECT reserved_for, COUNT(*) c FROM orders WHERE status='RESERVED' AND store_id=?"
            " GROUP BY reserved_for", (stores.current(),)).fetchall()}
    out = []
    for r in rows:
        t = _row(r)
        t["reservedOrders"] = reserved.get(r["id"], 0)
        if r["status"] == "WAITING":
            t["position"] = waiting_ids.index(r["id"]) + 1
            t["ahead"] = t["position"] - 1
        if est is not None:
            t["estimatedMinutes"] = int(est * max(0, (t.get("ahead") or 0)))
        out.append(t)
    return {
        "tickets": out, "counts": counts, "waitingCount": len(waiting),
        "estimateMinutes": round(est) if est is not None else None,
        "estimateAvailable": est is not None,
        "partyTotal": sum(r["party_size"] for r in waiting),
    }


def call(ticket_id):
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not r:
            raise LookupError("대기 정보를 찾을 수 없습니다")
        if r["status"] not in ("WAITING", "CALLED"):
            raise ValueError(f"'{STATUSES.get(r['status'])}' 상태에서는 호출할 수 없습니다")
        conn.execute("UPDATE waiting_tickets SET status='CALLED', called_at=? WHERE id=?",
                     (_now(), ticket_id))
        store.bump(conn)
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        ticket = _status_row(conn, r)
    for ch in ("sms", "kakao"):
        _notify(ch, "called", ticket)
    return ticket


def seat(ticket_id, table_id=None):
    """입장 처리. 테이블을 고르면 그 테이블로 배정하고, 회원 쪽에도 방문 기록을 남긴다."""
    table = None
    if table_id:
        table = tables.get(int(table_id))
        if not table["active"]:
            raise ValueError(f"'{table['label']}'은(는) 비활성 테이블입니다")
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not r:
            raise LookupError("대기 정보를 찾을 수 없습니다")
        if r["status"] not in ("WAITING", "CALLED"):
            raise ValueError(f"'{STATUSES.get(r['status'])}' 상태는 입장 처리할 수 없습니다")
        conn.execute(
            "UPDATE waiting_tickets SET status='SEATED', seated_at=?, closed_at=?, table_id=? WHERE id=?",
            (_now(), _now(), table["id"] if table else None, ticket_id))
        # 회원 모듈의 공개 함수로만 기록한다(회원 테이블 직접 접근 금지)
        customers.upsert(conn, r["name"], r["phone"], bool(r["consent"]))
        store.bump(conn)
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        ticket = _row(r)
    ticket["tableLabel"] = table["label"] if table else ""
    # 미리 주문한 게 있으면 입장과 함께 주방으로 넘긴다
    from . import orders as orders_mod
    ticket["startedOrders"] = orders_mod.start_reserved(ticket_id, table["id"] if table else None)
    for ch in ("sms", "kakao"):
        _notify(ch, "seated", dict(ticket))
    return ticket


def close(ticket_id, status="CANCELED"):
    if status not in ("CANCELED", "NOSHOW"):
        raise ValueError("취소 또는 노쇼로만 닫을 수 있습니다")
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not r:
            raise LookupError("대기 정보를 찾을 수 없습니다")
        if r["status"] in CLOSED:
            raise ValueError(f"이미 '{STATUSES.get(r['status'])}' 처리된 대기입니다")
        conn.execute("UPDATE waiting_tickets SET status=?, closed_at=? WHERE id=?",
                     (status, _now(), ticket_id))
        from . import orders as orders_mod
        orders_mod.cancel_reserved_conn(
            conn, ticket_id, "대기 취소" if status == "CANCELED" else "노쇼로 취소")
        store.bump(conn)
        r = conn.execute("SELECT * FROM waiting_tickets WHERE id=?", (ticket_id,)).fetchone()
        return _row(r)


def cleanup(now=None):
    """입장·취소·노쇼 후 KEEP_HOURS 가 지난 대기의 개인정보를 지운다. 몇 건 정리했는지 돌려준다."""
    ts = now or store.now()
    limit = (datetime.strptime(ts, FMT) - timedelta(hours=KEEP_HOURS)).strftime(FMT)
    with store.tx() as conn:
        cur = conn.execute(
            "UPDATE waiting_tickets SET name='', phone='', token='purged-'||id, purged=1"
            " WHERE purged=0 AND status IN ('SEATED','CANCELED','NOSHOW')"
            " AND COALESCE(closed_at, created_at) < ?", (limit,))
        return cur.rowcount
