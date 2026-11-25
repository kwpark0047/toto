"""사업자 로그인·세션 모듈.

책임: 비밀번호 해시, 로그인/로그아웃, 세션 쿠키(서버 저장 방식), 로그인 실패 잠금.
직원 정보 자체는 staff 모듈이 다루고, 이 모듈은 '누구로 로그인했는가'만 책임진다.

- 비밀번호는 표준 라이브러리 hashlib(pbkdf2_sha256) + 계정별 salt 로만 저장한다. 평문은 남기지 않는다.
- 세션은 DB(staff_sessions)에 두고, 브라우저에는 HttpOnly 쿠키 하나만 준다.
- 같은 아이디로 5회 틀리면 5분 동안 잠근다(시제품 수준의 최소 방어).
"""
import hashlib
import hmac
import json
import secrets
import string
import threading
import time
from datetime import datetime, timedelta

from . import config, store

ITERATIONS = 120_000
PREFIX = "pbkdf2_sha256"


class AuthError(Exception):
    """로그인이 필요하거나 권한이 없다."""
    status = 401

    def __init__(self, message, status=None):
        super().__init__(message)
        if status:
            self.status = status


class LockedError(AuthError):
    status = 429


class ForbiddenError(AuthError):
    status = 403


# 로그인 실패 기록: {아이디: [실패 시각, ...]} — 서버를 재시작하면 초기화된다.
_fails = {}
_fails_lock = threading.Lock()


def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS)
    return f"{PREFIX}${ITERATIONS}${salt}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
        iterations = int(iterations)
    except (AttributeError, ValueError):
        return False
    if algo != PREFIX:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return hmac.compare_digest(dk.hex(), digest)


def _check_lock(username):
    key = (username or "").strip().lower()
    with _fails_lock:
        stamps = [t for t in _fails.get(key, []) if time.time() - t < config.LOGIN_FAIL_WINDOW]
        _fails[key] = stamps
        if len(stamps) >= config.LOGIN_MAX_FAILS:
            remain = int(config.LOGIN_LOCK_SECONDS - (time.time() - stamps[-1]))
            if remain > 0:
                raise LockedError(
                    f"비밀번호를 {config.LOGIN_MAX_FAILS}회 틀렸습니다. {max(1, remain // 60 + 1)}분 뒤에 다시 시도해 주세요")


def _record_fail(username):
    key = (username or "").strip().lower()
    with _fails_lock:
        _fails.setdefault(key, []).append(time.time())


def _clear_fail(username):
    with _fails_lock:
        _fails.pop((username or "").strip().lower(), None)


def attempts_left(username):
    key = (username or "").strip().lower()
    with _fails_lock:
        used = len([t for t in _fails.get(key, []) if time.time() - t < config.LOGIN_FAIL_WINDOW])
    return max(0, config.LOGIN_MAX_FAILS - used)


def _user_row(row):
    raw_perms = row["permissions"] if "permissions" in row.keys() else "{}"
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["name"],
        "role": row["role"],
        "roleLabel": config.ROLE_LABELS.get(row["role"], row["role"]),
        "active": bool(row["active"]),
        "storeId": (row["store_id"] if "store_id" in row.keys() else 1) or 1,
        "mustChange": bool(row["must_change"]) if "must_change" in row.keys() else False,
        "permissions": sorted(permissions_for(row["role"], raw_perms)),
    }


def permissions_for(role, raw="{}"):
    """역할 기본 권한 + 직원별 예외(JSON) → 실제 권한 집합.

    관리자는 항상 전부(스스로 잠기지 않게 예외를 두지 않는다).
    """
    if role == "admin":
        return set(config.PERMISSION_CODES)
    perms = set(config.ROLE_PERMISSIONS.get(role, []))
    try:
        overrides = json.loads(raw or "{}")
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for code, value in overrides.items():
            if code not in config.PERMISSION_CODES or value is None:
                continue
            if value:
                perms.add(code)
            else:
                perms.discard(code)
    return perms


def has_perm(user, code):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return code in (user.get("permissions") or [])


def login(username, password, ip="", user_agent=""):
    """성공하면 (user, token). 실패는 AuthError / LockedError."""
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise AuthError("아이디와 비밀번호를 넣어 주세요")
    _check_lock(username)
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE username=?", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        _record_fail(username)
        left = attempts_left(username)
        raise AuthError("아이디 또는 비밀번호가 맞지 않습니다" + (f" (남은 시도 {left}회)" if left else ""))
    if not row["active"]:
        raise AuthError("사용하지 않는 계정입니다. 사장님에게 문의해 주세요")
    _clear_fail(username)
    token, expires = _new_session(row["id"], ip, user_agent,
                                 row["store_id"] if "store_id" in row.keys() else 1)
    user = _user_row(row)
    user["storeId"] = row["store_id"] if "store_id" in row.keys() else 1
    return user, token, expires


def login_staff(staff_id, ip="", user_agent=""):
    """비밀번호 없이 세션을 만든다(소셜 로그인처럼 신원이 이미 확인된 경우).

    소셜 계정은 oauth 모듈이 확인한 뒤 이 함수로 세션만 발급한다.
    """
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if not row:
        raise AuthError("계정을 찾을 수 없습니다", 404)
    if not row["active"]:
        raise AuthError("사용하지 않는 계정입니다. 사장님에게 문의해 주세요")
    store_id = row["store_id"] if "store_id" in row.keys() else 1
    token, expires = _new_session(row["id"], ip, user_agent, store_id)
    user = _user_row(row)
    user["storeId"] = store_id
    return user, token, expires


def _new_session(staff_id, ip="", user_agent="", store_id=None):
    token = secrets.token_urlsafe(32)
    ts = store.now()
    expires = (datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
               + timedelta(hours=config.SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with store.tx() as conn:
        conn.execute("DELETE FROM staff_sessions WHERE expires_at < ?", (ts,))
        conn.execute(
            "INSERT INTO staff_sessions(token, staff_id, created_at, last_seen, expires_at, ip, user_agent,"
            " active_store) VALUES(?,?,?,?,?,?,?,?)",
            (token, staff_id, ts, ts, expires, (ip or "")[:60], (user_agent or "")[:200],
             int(store_id) if store_id else None),
        )
        conn.execute("UPDATE staff SET last_login_at=? WHERE id=?", (ts, staff_id))
    return token, expires


def logout(token):
    if not token:
        return
    with store.tx() as conn:
        conn.execute("DELETE FROM staff_sessions WHERE token=?", (token,))


def user_for_token(token):
    """쿠키 토큰 → 로그인 사용자. 만료·비활성·없음이면 None."""
    if not token:
        return None
    ts = store.now()
    with store.read() as conn:
        row = conn.execute(
            "SELECT s.staff_id AS sid, s.expires_at, s.active_store, u.* FROM staff_sessions s"
            " JOIN staff u ON u.id = s.staff_id WHERE s.token=?", (token,)
        ).fetchone()
    if not row:
        return None
    if row["expires_at"] < ts or not row["active"]:
        logout(token)
        return None
    with store.tx() as conn:
        conn.execute("UPDATE staff_sessions SET last_seen=? WHERE token=?", (ts, token))
    user = _user_row(row)
    # 세션에 고른 매장이 있으면 그 매장으로, 없으면 직원의 소속 매장으로
    active = row["active_store"] or user["storeId"]
    from . import stores
    user["storeId"] = active if stores.exists(active) else user["storeId"]
    return user


def switch_store(user, token, store_id):
    """관리자가 일하는 매장을 바꾼다(세션 단위). 다른 역할은 소속 매장을 벗어날 수 없다."""
    from . import stores
    if not user:
        raise AuthError("로그인이 필요합니다")
    if user["role"] != "admin":
        raise ForbiddenError("매장 전환은 관리자만 할 수 있습니다")
    try:
        sid = int(store_id)
    except (TypeError, ValueError):
        raise ValueError("매장을 골라 주세요")
    target = stores.get(sid)
    if not target["active"]:
        raise ValueError("사용하지 않는 매장입니다")
    with store.tx() as conn:
        conn.execute("UPDATE staff_sessions SET active_store=? WHERE token=?", (sid, token))
    user["storeId"] = sid
    return user


def sessions_for(staff_id, current_token=None):
    ts = store.now()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM staff_sessions WHERE staff_id=? AND expires_at>=? ORDER BY last_seen DESC",
            (staff_id, ts),
        ).fetchall()
    return [{
        "createdAt": r["created_at"], "lastSeen": r["last_seen"], "expiresAt": r["expires_at"],
        "ip": r["ip"], "device": _device(r["user_agent"]), "current": r["token"] == current_token,
    } for r in rows]


def _device(ua):
    ua = ua or ""
    if not ua:
        return "알 수 없는 기기"
    for key, name in (("iPhone", "아이폰"), ("iPad", "아이패드"), ("Android", "안드로이드"),
                      ("Windows", "윈도우 PC"), ("Macintosh", "맥"), ("Linux", "리눅스")):
        if key.lower() in ua.lower():
            return name
    return ua[:40]


def change_password(staff_id, current, new, keep_token=None):
    """현재 비밀번호를 확인한 뒤 바꾼다. 다른 기기의 세션은 끊는다."""
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if not row:
        raise AuthError("계정을 찾을 수 없습니다", 404)
    if not verify_password(current or "", row["password_hash"]):
        raise AuthError("현재 비밀번호가 맞지 않습니다", 403)
    if len((new or "").strip()) < config.PASSWORD_MIN_LEN:
        raise ValueError(f"새 비밀번호는 {config.PASSWORD_MIN_LEN}자 이상으로 정해 주세요")
    with store.tx() as conn:
        conn.execute("UPDATE staff SET password_hash=?, must_change=0, updated_at=? WHERE id=?",
                     (hash_password(new.strip()), store.now(), staff_id))
        if keep_token:
            conn.execute("DELETE FROM staff_sessions WHERE staff_id=? AND token<>?",
                         (staff_id, keep_token))
    return True


def reset_password(staff_id):
    """관리자가 직원 비밀번호를 초기화한다. 임시 비밀번호는 이때 한 번만 돌려준다."""
    alphabet = string.ascii_lowercase + string.digits
    temp = "mj" + "".join(secrets.choice(alphabet) for _ in range(6))
    with store.tx() as conn:
        cur = conn.execute(
            "UPDATE staff SET password_hash=?, must_change=1, updated_at=? WHERE id=?",
            (hash_password(temp), store.now(), staff_id))
        if cur.rowcount == 0:
            raise LookupError("직원을 찾을 수 없습니다")
        conn.execute("DELETE FROM staff_sessions WHERE staff_id=?", (staff_id,))
        store.bump(conn)
    return temp


def require_perm(user, code):
    if not user:
        raise AuthError("로그인이 필요합니다")
    if not has_perm(user, code):
        raise ForbiddenError("이 기능을 쓸 권한이 없습니다")
    return True


def require(user, roles):
    """권한 검사. roles 가 None/빈 값이면 로그인만 확인한다."""
    if not user:
        raise AuthError("로그인이 필요합니다")
    if roles and user["role"] not in roles:
        raise ForbiddenError("이 화면을 볼 권한이 없습니다")


def cookie_header(token, max_age):
    parts = [
        f"{config.SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    return "; ".join(parts)


def token_from_cookie(cookie_header_value):
    for part in (cookie_header_value or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == config.SESSION_COOKIE:
            return value
    return None
