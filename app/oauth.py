"""구글·카카오 소셜 로그인 (파이썬 표준 라이브러리만 사용).

책임: 인가 URL 만들기, state(CSRF) 검증, 인가 코드 → 토큰 → 프로필 교환,
      프로필과 staff 계정 연결(oauth_accounts), 첫 방문 시 매장·사장님 계정 생성.

원칙
- 앱 키가 없으면 '설정되지 않음'을 그대로 알린다. 가짜 로그인으로 속이지 않는다.
- 외부 통신은 HTTPS 로만 하고, 실패는 OAuthError(code) 로만 돌려준다(원문 응답은 남기지 않는다).
- 첫 방문(아직 사장님 계정이 없을 때)만 계정을 자동으로 만든다. 이미 매장이 있으면
  연결되지 않은 소셜 계정으로 관리자 계정을 새로 만들지 않는다(unlinked).
"""
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

from . import auth, config, staff, store

TIMEOUT = 10
STATE_COOKIE = "mj_oauth_state"
STATE_PATH = "/api/auth/oauth"
STATE_MAX_AGE = 600          # 10분

PROVIDERS = {
    "google": {
        "label": "구글",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
        "secret_required": True,
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "profile": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "kakao": {
        "label": "카카오",
        "id_env": "KAKAO_CLIENT_ID",
        "secret_env": "KAKAO_CLIENT_SECRET",
        "secret_required": False,   # 카카오는 보안 강화 시에만 시크릿을 쓴다
        "authorize": "https://kauth.kakao.com/oauth/authorize",
        "token": "https://kauth.kakao.com/oauth/token",
        "profile": "https://kapi.kakao.com/v2/user/me",
        "scope": "profile_nickname account_email",
    },
}


class OAuthError(Exception):
    """소셜 로그인 실패. code 는 화면 안내 문구 키(token/profile/state/denied/server)."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def _env(name):
    return (os.environ.get(name) or "").strip()


def credentials(name):
    meta = PROVIDERS.get(name)
    if not meta:
        return "", ""
    return _env(meta["id_env"]), _env(meta["secret_env"])


def configured(name):
    """로그인 버튼이 실제로 동작할 수 있는 상태인가(앱 키가 있는가)."""
    meta = PROVIDERS.get(name)
    if not meta:
        return False
    client_id, secret = credentials(name)
    if not client_id:
        return False
    if meta["secret_required"] and not secret:
        return False
    return True


def status():
    out = {}
    for name, meta in PROVIDERS.items():
        client_id, secret = credentials(name)
        out[name] = {
            "label": meta["label"],
            "configured": configured(name),
            "loginUrl": f"/api/auth/oauth/{name}",
            "clientIdSet": bool(client_id),
            "clientSecretSet": bool(secret),
            "secretRequired": meta["secret_required"],
        }
    return out


# ------------------------------------------------------------------ 주소
_LOCAL_HOST = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|\[::1\]|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)")


def public_base(raw_base=""):
    """OAuth 리다이렉트에 쓸 공개 주소. OAUTH_BASE_URL 이 있으면 그것을 우선한다."""
    env = _env("OAUTH_BASE_URL").rstrip("/")
    if env:
        return env
    raw = (raw_base or "").strip().rstrip("/")
    if not raw:
        return f"http://localhost:{config.PORT}"
    host = raw.split("//", 1)[1] if "//" in raw else raw
    scheme = "http" if _LOCAL_HOST.match(host) else "https"
    return f"{scheme}://{host}"


def redirect_uri(name, raw_base=""):
    return f"{public_base(raw_base)}{STATE_PATH}/{name}/callback"


# ------------------------------------------------------------------ state(CSRF)
def new_state():
    return secrets.token_urlsafe(24)


def state_cookie(name, state):
    return (f"{STATE_COOKIE}={name}.{state}; Path={STATE_PATH}; HttpOnly; "
            f"SameSite=Lax; Max-Age={STATE_MAX_AGE}")


def clear_state_cookie():
    return (f"{STATE_COOKIE}=; Path={STATE_PATH}; HttpOnly; "
            f"SameSite=Lax; Max-Age=0")


def state_from_cookie(cookie_header):
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == STATE_COOKIE:
            return value
    return ""


def check_state(provider, state, cookie_value):
    """인가 요청에서 심은 state 와 돌아온 state 가 같은지(제공자 이름까지) 확인한다."""
    if not state or not cookie_value:
        return False
    name, _, saved = cookie_value.partition(".")
    if name != provider or not saved:
        return False
    return True if secrets.compare_digest(saved, state) else False


# ------------------------------------------------------------------ 인가 URL
def authorize_url(name, raw_base="", state="", next_path=""):
    meta = PROVIDERS.get(name)
    if not meta or not configured(name):
        return ""
    client_id, _ = credentials(name)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(name, raw_base),
        "response_type": "code",
        "state": state,
        "scope": meta["scope"],
    }
    if name == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    if name == "kakao":
        params["prompt"] = "login"
    return meta["authorize"] + "?" + urllib.parse.urlencode(params)


# ------------------------------------------------------------------ 외부 통신
def _request_json(url, data=None, headers=None, code="token"):
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url, data=body, method="POST" if body is not None else "GET",
        headers={"Accept": "application/json", **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        e.close()
        raise OAuthError(code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OAuthError(code)
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        raise OAuthError(code)
    if not isinstance(payload, dict):
        raise OAuthError(code)
    return payload


def exchange_code(name, code, raw_base=""):
    meta = PROVIDERS[name]
    client_id, secret = credentials(name)
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(name, raw_base),
        "code": code,
    }
    if secret:
        data["client_secret"] = secret
    payload = _request_json(meta["token"], data, code="token")
    token = payload.get("access_token")
    if not token:
        raise OAuthError("token")
    return token


def fetch_profile(name, access_token):
    meta = PROVIDERS[name]
    payload = _request_json(meta["profile"], headers={"Authorization": f"Bearer {access_token}"},
                            code="profile")
    if name == "google":
        subject = payload.get("sub") or ""
        email = payload.get("email") or ""
        nickname = payload.get("name") or (email.split("@")[0] if email else "")
    else:  # kakao
        subject = payload.get("id") or ""
        account = payload.get("kakao_account") or {}
        profile = account.get("profile") or {}
        email = account.get("email") or ""
        nickname = profile.get("nickname") or ""
    if not subject:
        raise OAuthError("profile")
    return {
        "provider": name,
        "subject": str(subject),
        "email": str(email)[:120],
        "name": (str(nickname).strip() or "사장님")[:40],
    }


# ------------------------------------------------------------------ 계정 연결
def linked_staff_id(provider, subject):
    with store.read() as conn:
        row = conn.execute(
            "SELECT staff_id FROM oauth_accounts WHERE provider=? AND subject=?",
            (provider, subject)).fetchone()
    return row["staff_id"] if row else None


def _link(staff_id, profile):
    ts = store.now()
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO oauth_accounts(provider, subject, staff_id, email, name, linked_at,"
            " last_login_at) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(provider, subject) DO UPDATE SET staff_id=excluded.staff_id,"
            " email=excluded.email, name=excluded.name, last_login_at=excluded.last_login_at",
            (profile["provider"], profile["subject"], staff_id, profile["email"],
             profile["name"], ts, ts))


def _touch(provider, subject):
    with store.tx() as conn:
        conn.execute(
            "UPDATE oauth_accounts SET last_login_at=? WHERE provider=? AND subject=?",
            (store.now(), provider, subject))


def _free_username(provider, subject):
    base = re.sub(r"[^A-Za-z0-9]", "", f"{provider}{subject}")[:18] or f"{provider}user"
    with store.read() as conn:
        taken = {r["username"].lower() for r in conn.execute("SELECT username FROM staff").fetchall()}
    candidate, n = base, 1
    while candidate.lower() in taken:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def _store_name(profile):
    nickname = (profile.get("name") or "").strip()
    if nickname and nickname != "사장님":
        return f"{nickname[:16]}의 매장"
    return config.STORE.get("name") or "맛집"


def login_with_profile(profile, provider, ip="", user_agent="", store_name=""):
    """소셜 프로필 → (user, token, expires, created).

    이미 연결된 계정이면 로그인하고, 처음이면 자기 매장을 가진 사업자 계정을 새로 만든다.
    배포 하나에 여러 사업자가 가입할 수 있으므로 다른 사장님이 있어도 막지 않는다.
    (새 계정은 자기 매장만 보이고, 다른 매장 데이터는 보이지 않는다.)
    """
    staff_id = linked_staff_id(provider, profile["subject"])
    if staff_id:
        user, token, expires = auth.login_staff(staff_id, ip, user_agent)
        _touch(provider, profile["subject"])
        return user, token, expires, False

    username = _free_username(provider, profile["subject"])
    user, token, expires, _ = staff.signup(
        (store_name or "").strip() or _store_name(profile),
        username,
        secrets.token_urlsafe(18),
        table_count=config.STORE.get("tables", 8),
    )
    _link(user["id"], profile)
    return user, token, expires, True
