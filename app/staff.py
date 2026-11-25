"""직원·출퇴근·스케줄·예상 급여 모듈.

책임:
- 직원 계정(이름·연락처·역할·메모·사용 여부·비밀번호) 관리
- 역할(관리자·매니저·카운터·주방·알바) + 직원별 권한 예외 + 시급/월급 정보
- 사업자 계정 가입(가입은 매장 이름 + 아이디·비밀번호 두 가지만 받는다)
- 출근/퇴근 기록, 직원별·월별 근무시간 합계, 근태 CSV
- 근무 스케줄표(등록·주/월 보기·오늘 근무자)와 실제 출퇴근 대조(지각·미출근)
- 예상 급여(참고용): 실제 근무시간 × 시급, 또는 월급. **세금·4대보험·급여명세서는 하지 않는다.**

급여는 참고용 숫자다. 세무 처리는 회계 프로그램·노무 검토가 필요하다.
"""
import csv
import io
import json
from datetime import datetime, timedelta

from . import auth, config, settings, stores, store, tables

ROLE_LABELS = config.ROLE_LABELS
FMT = "%Y-%m-%d %H:%M:%S"
LATE_GRACE_MIN = 10        # 출근 예정보다 10분 넘게 늦으면 지각


# ---------------------------------------------------------------- 직원

def _role(value):
    role = (value or "").strip()
    if role not in ROLE_LABELS:
        raise ValueError("역할은 관리자·매니저·카운터·주방·알바(시간제) 중에서 골라 주세요")
    return role


def _permissions(raw, role):
    """직원별 권한 예외(JSON) — 넘어온 값만 검사해서 저장한다."""
    if raw is None:
        return "{}"
    if not isinstance(raw, dict):
        raise ValueError("권한 설정 형식이 올바르지 않습니다")
    clean = {}
    for code, value in raw.items():
        if code not in config.PERMISSION_CODES:
            continue
        clean[code] = bool(value)
    return json.dumps(clean, ensure_ascii=False)


def _money(value, label):
    try:
        num = int(float(value or 0))
    except (TypeError, ValueError):
        raise ValueError(f"{label}은(는) 숫자로 넣어 주세요")
    if num < 0:
        raise ValueError(f"{label}은(는) 0 이상으로 넣어 주세요")
    if num > 100_000_000:
        raise ValueError(f"{label}이(가) 너무 큽니다")
    return num


def _pay_type(value, role):
    value = (value or "").strip()
    if value not in ("", "hourly", "monthly"):
        raise ValueError("급여 형태는 시급·월급 중에서 골라 주세요")
    if not value:
        return "hourly" if role == config.PART_TIME_ROLE else ""
    return value


def _clean_password(password):
    password = (password or "").strip()
    if len(password) < config.PASSWORD_MIN_LEN:
        raise ValueError(f"비밀번호는 {config.PASSWORD_MIN_LEN}자 이상으로 정해 주세요")
    return password


def _row(r):
    keys = r.keys()
    role = r["role"]
    raw_perms = r["permissions"] if "permissions" in keys else "{}"
    pay_type = (r["pay_type"] if "pay_type" in keys else "") or (
        "hourly" if role == config.PART_TIME_ROLE else "")
    return {
        "id": r["id"], "username": r["username"], "name": r["name"], "phone": r["phone"],
        "role": role, "roleLabel": ROLE_LABELS.get(role, role),
        "roleHint": config.ROLE_HINTS.get(role, ""),
        "storeId": r["store_id"] if "store_id" in keys else 1,
        "memo": r["memo"], "active": bool(r["active"]),
        "lastLoginAt": r["last_login_at"], "createdAt": r["created_at"],
        "payType": pay_type, "payLabel": {"hourly": "시급제", "monthly": "월급제"}.get(pay_type, "미정"),
        "hourlyWage": r["hourly_wage"] if "hourly_wage" in keys else 0,
        "monthlySalary": r["monthly_salary"] if "monthly_salary" in keys else 0,
        "permissions": sorted(auth.permissions_for(role, raw_perms)),
        "permissionOverrides": json.loads(raw_perms or "{}") if raw_perms else {},
        "mustChange": bool(r["must_change"]) if "must_change" in keys else False,
    }


def get(staff_id):
    with store.read() as conn:
        r = conn.execute("SELECT * FROM staff WHERE id=? AND store_id=?",
                         (staff_id, stores.current())).fetchone()
        if not r:
            raise LookupError("직원을 찾을 수 없습니다")
        return _row(r)


def _month_bounds(month=None):
    month = month or store.today()[:7]
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d")
    except ValueError:
        raise ValueError("월은 2026-11 처럼 넣어 주세요")
    end = (start + timedelta(days=32)).replace(day=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), start.strftime("%Y-%m")


def _minutes(clock_in, clock_out):
    try:
        a = datetime.strptime((clock_in or "")[:19], FMT)
        b = datetime.strptime((clock_out or "")[:19], FMT) if clock_out else datetime.now(store.TZ).replace(tzinfo=None)
    except ValueError:
        return 0
    return max(0, int((b - a).total_seconds() // 60))


def clock_state(staff_id, month=None):
    """지금 화면에 보여 줄 출퇴근 상태."""
    today = store.today()
    with store.read() as conn:
        open_row = conn.execute(
            "SELECT * FROM attendance WHERE staff_id=? AND clock_out IS NULL AND store_id=?",
            (staff_id, stores.current())
        ).fetchone()
        today_rows = conn.execute(
            "SELECT * FROM attendance WHERE staff_id=? AND work_date=? AND store_id=?",
            (staff_id, today, stores.current())
        ).fetchall()
    today_min = sum(_minutes(r["clock_in"], r["clock_out"]) for r in today_rows)
    m_start, m_end, m_key = _month_bounds(month)
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM attendance WHERE staff_id=? AND work_date>=? AND work_date<? AND store_id=?",
            (staff_id, m_start, m_end, stores.current()),
        ).fetchall()
    month_min = sum(_minutes(r["clock_in"], r["clock_out"]) for r in rows)
    return {
        "open": bool(open_row),
        "clockIn": open_row["clock_in"] if open_row else None,
        "openMinutes": _minutes(open_row["clock_in"], None) if open_row else 0,
        "todayMinutes": today_min,
        "monthMinutes": month_min,
        "month": m_key,
    }


def list_staff(q="", sort="name", month=None):
    m_start, m_end, m_key = _month_bounds(month)
    with store.read() as conn:
        rows = conn.execute("SELECT * FROM staff WHERE store_id=? ORDER BY name, id",
                            (stores.current(),)).fetchall()
        att = conn.execute(
            "SELECT staff_id, clock_in, clock_out, work_date FROM attendance"
            " WHERE work_date>=? AND work_date<? AND store_id=?", (m_start, m_end, stores.current())
        ).fetchall()
        opens = conn.execute(
            "SELECT staff_id, clock_in FROM attendance WHERE clock_out IS NULL AND store_id=?",
            (stores.current(),)).fetchall()
    minutes, last_in = {}, {}
    for a in att:
        minutes[a["staff_id"]] = minutes.get(a["staff_id"], 0) + _minutes(a["clock_in"], a["clock_out"])
    for a in att:
        if not last_in.get(a["staff_id"]) or a["clock_in"] > last_in[a["staff_id"]]:
            last_in[a["staff_id"]] = a["clock_in"]
    open_map = {o["staff_id"]: o["clock_in"] for o in opens}

    out = []
    for r in rows:
        item = _row(r)
        item["monthMinutes"] = minutes.get(r["id"], 0)
        item["monthText"] = _hhm(item["monthMinutes"])
        item["lastIn"] = last_in.get(r["id"])
        item["open"] = bool(open_map.get(r["id"]))
        item["openSince"] = open_map.get(r["id"])
        out.append(item)

    if q:
        ql = q.lower().replace(" ", "")
        out = [s for s in out if ql in s["name"].lower() or ql in s["username"].lower()
               or ql in (s["phone"] or "").replace("-", "") or ql in s["roleLabel"]]
    keys = {
        "name": lambda s: s["name"],
        "role": lambda s: (config.ROLE_ORDER.index(s["role"]) if s["role"] in config.ROLE_ORDER else 9, s["name"]),
        "hours": lambda s: s["monthMinutes"],
        "recent": lambda s: s["lastIn"] or "",
    }
    if sort == "name":
        out.sort(key=keys["name"])
    else:
        out.sort(key=keys.get(sort, keys["name"]), reverse=True)
    return {"staff": out, "month": m_key}


def _hhm(minutes):
    return f"{minutes // 60}시간 {minutes % 60}분"


def create(data, actor=None):
    name = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip()
    if not name:
        raise ValueError("직원 이름을 넣어 주세요")
    if not username:
        raise ValueError("로그인 아이디를 넣어 주세요")
    if not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValueError("아이디는 영문·숫자로 넣어 주세요 (예: 김주방 → kitchen2)")
    role = _role(data.get("role"))
    password = _clean_password(data.get("password"))
    pay_type = _pay_type(data.get("payType"), role)
    hourly = _money(data.get("hourlyWage", 0), "시급")
    monthly = _money(data.get("monthlySalary", 0), "월급")
    perms = _permissions(data.get("permissions"), role)
    ts = store.now()
    with store.tx() as conn:
        if conn.execute("SELECT id FROM staff WHERE username=?", (username,)).fetchone():
            raise ValueError(f"'{username}' 아이디는 이미 쓰고 있습니다")
        cur = conn.execute(
            "INSERT INTO staff(store_id, username, name, phone, role, memo, active, password_hash,"
            " permissions, pay_type, hourly_wage, monthly_salary, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (stores.current(), username, name, (data.get("phone") or "").strip()[:30], role,
             (data.get("memo") or "").strip()[:500], 1 if data.get("active", True) else 0,
             auth.hash_password(password), perms, pay_type, hourly, monthly, ts, ts),
        )
        staff_id = cur.lastrowid
        store.bump(conn)
    return get(staff_id)


def update(staff_id, data, actor=None):
    ts = store.now()
    with store.tx() as conn:
        r = conn.execute("SELECT * FROM staff WHERE id=? AND store_id=?",
                         (staff_id, stores.current())).fetchone()
        if not r:
            raise LookupError("직원을 찾을 수 없습니다")
        sets, params = [], []
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("직원 이름을 넣어 주세요")
            sets.append("name=?")
            params.append(name)
        if "username" in data and (data.get("username") or "").strip() != r["username"]:
            username = (data.get("username") or "").strip()
            if not username:
                raise ValueError("로그인 아이디를 넣어 주세요")
            if conn.execute("SELECT id FROM staff WHERE username=? AND id<>?",
                            (username, staff_id)).fetchone():
                raise ValueError(f"'{username}' 아이디는 이미 쓰고 있습니다")
            sets.append("username=?")
            params.append(username)
        if "phone" in data:
            sets.append("phone=?")
            params.append((data.get("phone") or "").strip()[:30])
        if "role" in data:
            role = _role(data.get("role"))
            if role != "admin" and r["role"] == "admin" and _admin_count(conn) <= 1:
                raise ValueError("마지막 관리자는 역할을 바꿀 수 없습니다. 다른 관리자를 먼저 만들어 주세요")
            sets.append("role=?")
            params.append(role)
        if "memo" in data:
            sets.append("memo=?")
            params.append((data.get("memo") or "").strip()[:500])
        if "active" in data:
            active = bool(data.get("active"))
            if not active:
                if actor and actor["id"] == staff_id:
                    raise ValueError("지금 로그인한 계정은 비활성으로 바꿀 수 없습니다")
                if r["role"] == "admin" and _admin_count(conn) <= 1:
                    raise ValueError("마지막 관리자는 비활성으로 바꿀 수 없습니다")
            sets.append("active=?")
            params.append(1 if active else 0)
        if "permissions" in data:
            sets.append("permissions=?")
            params.append(_permissions(data.get("permissions"), r["role"]))
        if "payType" in data:
            role_now = _role(data.get("role")) if "role" in data else r["role"]
            sets.append("pay_type=?")
            params.append(_pay_type(data.get("payType"), role_now))
        if "hourlyWage" in data:
            sets.append("hourly_wage=?")
            params.append(_money(data.get("hourlyWage"), "시급"))
        if "monthlySalary" in data:
            sets.append("monthly_salary=?")
            params.append(_money(data.get("monthlySalary"), "월급"))
        if data.get("password"):
            sets.append("password_hash=?")
            params.append(auth.hash_password(_clean_password(data.get("password"))))
        if not sets:
            return get(staff_id)
        sets.append("updated_at=?")
        params.append(ts)
        conn.execute(f"UPDATE staff SET {','.join(sets)} WHERE id=?", (*params, staff_id))
        if data.get("active") is False:
            conn.execute("DELETE FROM staff_sessions WHERE staff_id=?", (staff_id,))
        store.bump(conn)
    return get(staff_id)


def _admin_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM staff WHERE role='admin' AND active=1 AND store_id=?",
                        (stores.current(),)).fetchone()["c"]


# ---------------------------------------------------------------- 가입

def signup(store_name, username, password, table_count=None):
    """첫 사업자 계정 만들기. 매장 이름 + 아이디·비밀번호만 받는다."""
    if has_owner():
        raise ValueError("이미 사업자 계정이 있습니다. 로그인해 주세요")
    name = (store_name or "").strip() or "맛집"
    username = (username or "").strip()
    if not username:
        raise ValueError("아이디를 넣어 주세요")
    if not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValueError("아이디는 영문·숫자로 넣어 주세요")
    password = _clean_password(password)
    ts = store.now()
    with store.tx() as conn:
        if conn.execute("SELECT id FROM staff WHERE username=?", (username,)).fetchone():
            raise ValueError(f"'{username}' 아이디는 이미 쓰고 있습니다")
        cur = conn.execute(
            "INSERT INTO staff(store_id, username, name, phone, role, memo, active, password_hash,"
            " created_at, updated_at) VALUES(1,?,?,'','admin','',1,?,?,?)",
            (username, "사장님", auth.hash_password(password), ts, ts),
        )
        staff_id = cur.lastrowid
        store.bump(conn)
    settings.save({"storeName": name})
    if table_count:
        tables.ensure_count(table_count)
    user, token, expires = auth.login(username, password)
    return user, token, expires, get(staff_id)


def has_owner():
    with store.read() as conn:
        return bool(conn.execute("SELECT 1 FROM staff LIMIT 1").fetchone())


# ---------------------------------------------------------------- 출퇴근

def clock_in(staff_id):
    ts = store.now()
    today = store.today()
    with store.tx() as conn:
        open_row = conn.execute(
            "SELECT * FROM attendance WHERE staff_id=? AND clock_out IS NULL", (staff_id,)
        ).fetchone()
        if open_row:
            raise ValueError(f"이미 출근 상태입니다 (오늘 {open_row['clock_in'][11:16]} 출근)")
        cur = conn.execute(
            "INSERT INTO attendance(store_id, staff_id, work_date, clock_in, clock_out, note, created_at)"
            " VALUES(?,?,?,?,NULL,'',?)", (stores.current(), staff_id, today, ts, ts),
        )
        store.bump(conn)
        rec_id = cur.lastrowid
    return record(rec_id)


def clock_out(staff_id):
    ts = store.now()
    with store.tx() as conn:
        open_row = conn.execute(
            "SELECT * FROM attendance WHERE staff_id=? AND clock_out IS NULL", (staff_id,)
        ).fetchone()
        if not open_row:
            raise ValueError("출근 기록이 없습니다. 먼저 '출근'을 눌러 주세요")
        conn.execute("UPDATE attendance SET clock_out=? WHERE id=?", (ts, open_row["id"]))
        store.bump(conn)
        rec_id = open_row["id"]
    return record(rec_id)


def record(rec_id):
    with store.read() as conn:
        r = conn.execute(
            "SELECT a.*, s.name AS staff_name, s.username FROM attendance a"
            " JOIN staff s ON s.id=a.staff_id WHERE a.id=?", (rec_id,)
        ).fetchone()
    if not r:
        raise LookupError("출퇴근 기록을 찾을 수 없습니다")
    return _att_row(r)


def _att_row(r):
    return {
        "id": r["id"], "staffId": r["staff_id"], "staffName": r["staff_name"],
        "username": r["username"], "date": r["work_date"], "clockIn": r["clock_in"],
        "clockOut": r["clock_out"], "minutes": _minutes(r["clock_in"], r["clock_out"]),
        "minutesText": _hhm(_minutes(r["clock_in"], r["clock_out"])),
        "open": not r["clock_out"], "note": r["note"],
    }


def attendance_list(staff_id=None, month=None):
    m_start, m_end, m_key = _month_bounds(month)
    sql = ("SELECT a.*, s.name AS staff_name, s.username FROM attendance a"
           " JOIN staff s ON s.id=a.staff_id WHERE a.work_date>=? AND a.work_date<? AND a.store_id=?")
    params = [m_start, m_end, stores.current()]
    if staff_id:
        sql += " AND a.staff_id=?"
        params.append(staff_id)
    sql += " ORDER BY a.clock_in DESC"
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"month": m_key, "records": [_att_row(r) for r in rows]}


def month_summary(month=None):
    m_start, m_end, m_key = _month_bounds(month)
    with store.read() as conn:
        rows = conn.execute(
            "SELECT a.*, s.name AS staff_name, s.username FROM attendance a"
            " JOIN staff s ON s.id=a.staff_id WHERE a.work_date>=? AND a.work_date<? AND a.store_id=?",
            (m_start, m_end, stores.current()),
        ).fetchall()
    per = {}
    for r in rows:
        d = per.setdefault(r["staff_id"], {"staffId": r["staff_id"], "name": r["staff_name"],
                                           "minutes": 0, "days": 0, "open": False})
        d["minutes"] += _minutes(r["clock_in"], r["clock_out"])
        d["days"] += 1
        d["open"] = d["open"] or not r["clock_out"]
    out = sorted(per.values(), key=lambda x: x["minutes"], reverse=True)
    for d in out:
        d["text"] = _hhm(d["minutes"])
    return {"month": m_key, "rows": out, "totalMinutes": sum(d["minutes"] for d in out)}


def month_csv(month=None, staff_id=None):
    data = attendance_list(staff_id, month)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["직원", "아이디", "날짜", "출근", "퇴근", "근무시간(분)", "근무시간", "비고"])
    for r in data["records"]:
        w.writerow([r["staffName"], r["username"], r["date"],
                    (r["clockIn"] or "")[11:16], (r["clockOut"] or "")[11:16] if r["clockOut"] else "근무 중",
                    r["minutes"], f"{r['minutes'] // 60}:{r['minutes'] % 60:02d}", r["note"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), data["month"]


# ---------------------------------------------------------------- 근무 스케줄
def _check_time(value, label="시간"):
    value = (value or "").strip()
    try:
        h, m = value.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        raise ValueError(f"{label}은 09:00 형식으로 넣어 주세요")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"{label}이 올바르지 않습니다")
    return f"{h:02d}:{m:02d}"


def _check_date(value):
    value = (value or "").strip()
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError("날짜는 2026-11-30 형식으로 넣어 주세요")
    return value


def set_schedule(staff_id, work_date, start_time, end_time, memo=""):
    """직원 한 명의 하루 근무를 등록한다(같은 날짜는 덮어쓴다)."""
    work_date = _check_date(work_date)
    start = _check_time(start_time, "시작 시간")
    end = _check_time(end_time, "끝 시간")
    if end <= start:
        raise ValueError("끝 시간은 시작 시간보다 늦어야 합니다")
    with store.tx() as conn:
        if not conn.execute("SELECT 1 FROM staff WHERE id=? AND store_id=?",
                            (staff_id, stores.current())).fetchone():
            raise LookupError("직원을 찾을 수 없습니다")
        conn.execute("DELETE FROM staff_schedules WHERE staff_id=? AND work_date=? AND store_id=?",
                     (staff_id, work_date, stores.current()))
        cur = conn.execute(
            "INSERT INTO staff_schedules(store_id, staff_id, work_date, start_time, end_time, memo,"
            " created_at) VALUES(?,?,?,?,?,?,?)",
            (stores.current(), staff_id, work_date, start, end, (memo or "").strip()[:100], store.now()))
        store.bump(conn)
        sid = cur.lastrowid
    return next(r for r in schedule(work_date, work_date) if r["id"] == sid)


def delete_schedule(schedule_id):
    with store.tx() as conn:
        cur = conn.execute("DELETE FROM staff_schedules WHERE id=? AND store_id=?",
                           (schedule_id, stores.current()))
        if cur.rowcount == 0:
            raise LookupError("스케줄을 찾을 수 없습니다")
        store.bump(conn)
    return True


def schedule(start=None, end=None):
    """기간 안의 근무 스케줄 + 실제 출퇴근 대조(지각·미출근)."""
    start = _check_date(start or store.today())
    end = _check_date(end or start)
    if end < start:
        raise ValueError("끝 날짜가 시작 날짜보다 빠릅니다")
    today = store.today()
    now = datetime.now(store.TZ).replace(tzinfo=None)
    with store.read() as conn:
        rows = conn.execute(
            "SELECT sc.*, st.name AS staff_name, st.role, st.username FROM staff_schedules sc"
            " JOIN staff st ON st.id=sc.staff_id WHERE sc.store_id=? AND sc.work_date>=?"
            " AND sc.work_date<=? ORDER BY sc.work_date, sc.start_time, st.name",
            (stores.current(), start, end)).fetchall()
        att = conn.execute(
            "SELECT * FROM attendance WHERE store_id=? AND work_date>=? AND work_date<=?",
            (stores.current(), start, end)).fetchall()
    by_key = {}
    for a in att:
        by_key.setdefault((a["staff_id"], a["work_date"]), []).append(a)
    out = []
    for r in rows:
        planned = datetime.strptime(f"{r['work_date']} {r['start_time']}", "%Y-%m-%d %H:%M")
        planned_end = datetime.strptime(f"{r['work_date']} {r['end_time']}", "%Y-%m-%d %H:%M")
        records = by_key.get((r["staff_id"], r["work_date"]), [])
        first = records[0] if records else None
        late_min, status, label = 0, "PLANNED", "예정"
        if r["work_date"] < today:
            if not first:
                status, label = "MISSING", "미출근"
            else:
                late_min = max(0, int((datetime.strptime(first["clock_in"][:19], FMT) - planned)
                                      .total_seconds() // 60))
                if late_min > LATE_GRACE_MIN:
                    status, label = "LATE", f"지각 {late_min}분"
                else:
                    status, label = "OK", "출근"
        elif r["work_date"] == today:
            if first:
                late_min = max(0, int((datetime.strptime(first["clock_in"][:19], FMT) - planned)
                                      .total_seconds() // 60))
                if late_min > LATE_GRACE_MIN:
                    status, label = "LATE", f"지각 {late_min}분"
                else:
                    status, label = "OK", "출근"
            elif now > planned + timedelta(minutes=LATE_GRACE_MIN):
                status, label = "MISSING", "미출근"
            elif now > planned_end:
                status, label = "MISSING", "미출근"
            else:
                status, label = "WAITING", "출근 전"
        out.append({
            "id": r["id"], "staffId": r["staff_id"], "staffName": r["staff_name"],
            "role": r["role"], "roleLabel": ROLE_LABELS.get(r["role"], r["role"]),
            "date": r["work_date"], "start": r["start_time"], "end": r["end_time"],
            "memo": r["memo"], "status": status, "statusLabel": label, "lateMin": late_min,
            "clockIn": first["clock_in"] if first else None,
            "clockOut": (records[-1]["clock_out"] if records else None),
            "minutes": sum(_minutes(a["clock_in"], a["clock_out"]) for a in records),
        })
    return out


def schedule_week(date=None):
    """월~일 주간 표 + 오늘 근무자 + 지각·미출근 요약."""
    date = _check_date(date or store.today())
    d = datetime.strptime(date, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    days = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    rows = schedule(days[0], days[6])
    by_day = {day: [r for r in rows if r["date"] == day] for day in days}
    today = store.today()
    return {
        "start": days[0], "end": days[6], "days": days, "byDay": by_day,
        "today": today, "todayRows": [r for r in rows if r["date"] == today],
        "lateCount": len([r for r in rows if r["status"] == "LATE"]),
        "missingCount": len([r for r in rows if r["status"] == "MISSING"]),
        "plannedCount": len(rows),
        "staff": [{"id": s["id"], "name": s["name"], "role": s["role"],
                   "roleLabel": s["roleLabel"]} for s in list_staff()["staff"] if s["active"]],
    }


def schedule_month(month=None):
    m_start, m_end, m_key = _month_bounds(month)
    last = (datetime.strptime(m_end, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = schedule(m_start, last)
    by_staff = {}
    for r in rows:
        d = by_staff.setdefault(r["staffId"], {
            "staffId": r["staffId"], "staffName": r["staffName"], "days": 0,
            "minutes": 0, "lateCount": 0, "missingCount": 0})
        d["days"] += 1
        d["minutes"] += r["minutes"]
        d["lateCount"] += 1 if r["status"] == "LATE" else 0
        d["missingCount"] += 1 if r["status"] == "MISSING" else 0
    for d in by_staff.values():
        d["text"] = _hhm(d["minutes"])
    return {"month": m_key, "rows": rows, "byStaff": sorted(by_staff.values(),
                                                           key=lambda x: x["staffName"]),
            "lateCount": len([r for r in rows if r["status"] == "LATE"]),
            "missingCount": len([r for r in rows if r["status"] == "MISSING"])}


# ---------------------------------------------------------------- 예상 급여(참고용)
def payroll(month=None):
    """실제 출퇴근 기록으로 계산한 예상 급여. 세금·4대보험·명세서는 없다(참고용)."""
    m_start, m_end, m_key = _month_bounds(month)
    with store.read() as conn:
        staff_rows = conn.execute(
            "SELECT * FROM staff WHERE store_id=? AND active=1 ORDER BY name", (stores.current(),)
        ).fetchall()
        att = conn.execute(
            "SELECT staff_id, clock_in, clock_out, work_date FROM attendance"
            " WHERE store_id=? AND work_date>=? AND work_date<?", (stores.current(), m_start, m_end)
        ).fetchall()
    per = {}
    for a in att:
        d = per.setdefault(a["staff_id"], {"minutes": 0, "days": set()})
        d["minutes"] += _minutes(a["clock_in"], a["clock_out"])
        d["days"].add(a["work_date"])
    rows = []
    for r in staff_rows:
        role = r["role"]
        pay_type = r["pay_type"] or ("hourly" if role == config.PART_TIME_ROLE else "")
        hourly = int(r["hourly_wage"] or 0)
        monthly = int(r["monthly_salary"] or 0)
        info = per.get(r["id"], {"minutes": 0, "days": set()})
        minutes = info["minutes"]
        hours = round(minutes / 60, 2)
        if pay_type == "monthly" and monthly:
            expected = monthly
        elif pay_type == "hourly" and hourly:
            expected = int(round(hours * hourly))
        else:
            expected = 0
        rows.append({
            "staffId": r["id"], "name": r["name"], "role": role,
            "roleLabel": ROLE_LABELS.get(role, role), "payType": pay_type,
            "payLabel": {"hourly": "시급제", "monthly": "월급제"}.get(pay_type, "미정"),
            "hourlyWage": hourly, "monthlySalary": monthly,
            "days": len(info["days"]), "minutes": minutes, "hours": hours,
            "hoursText": _hhm(minutes), "expectedPay": expected,
            "note": "" if expected else "시급·월급을 넣으면 계산됩니다",
        })
    return {
        "month": m_key,
        "rows": rows,
        "totalPay": sum(r["expectedPay"] for r in rows),
        "totalMinutes": sum(r["minutes"] for r in rows),
        "notice": "참고용입니다. 세금·4대보험·급여명세서는 이 앱에서 처리하지 않습니다(세무는 별도).",
    }


def payroll_csv(month=None):
    data = payroll(month)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["직원", "역할", "급여형태", "시급", "월급", "근무일수", "근무시간(분)",
                "근무시간", "예상급여", "비고"])
    for r in data["rows"]:
        w.writerow([r["name"], r["roleLabel"], r["payLabel"], r["hourlyWage"], r["monthlySalary"],
                    r["days"], r["minutes"], f"{r['minutes'] // 60}:{r['minutes'] % 60:02d}",
                    r["expectedPay"], "참고용"])
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), data["month"]


def reset_password(staff_id):
    """관리자가 직원 비밀번호를 초기화한다(임시 비밀번호 1회 반환, 첫 로그인 때 변경 권장)."""
    with store.read() as conn:
        if not conn.execute("SELECT 1 FROM staff WHERE id=? AND store_id=?",
                            (staff_id, stores.current())).fetchone():
            raise LookupError("직원을 찾을 수 없습니다")
    return auth.reset_password(staff_id)


def add_attendance_manual(staff_id, work_date, start, end, memo=""):
    """관리자가 출퇴근 기록을 보정한다(깜빡하고 안 찍은 날). 실제 기록과 같은 표에 남는다."""
    work_date = _check_date(work_date)
    start = _check_time(start, "시작 시간")
    end = _check_time(end, "끝 시간")
    if end <= start:
        raise ValueError("끝 시간은 시작 시간보다 늦어야 합니다")
    with store.tx() as conn:
        if not conn.execute("SELECT 1 FROM staff WHERE id=? AND store_id=?",
                            (staff_id, stores.current())).fetchone():
            raise LookupError("직원을 찾을 수 없습니다")
        cur = conn.execute(
            "INSERT INTO attendance(store_id, staff_id, work_date, clock_in, clock_out, note, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (stores.current(), staff_id, work_date, f"{work_date} {start}:00",
             f"{work_date} {end}:00", ("보정: " + (memo or "")).strip()[:100], store.now()))
        store.bump(conn)
        rec_id = cur.lastrowid
    return record(rec_id)
