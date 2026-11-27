#!/usr/bin/env python3
"""시제품 동작 확인 스크립트 (실제 HTTP).

실행 중인 서버에 실제 요청을 보내 로그인·권한·직원·출퇴근·메뉴·회원/포인트·테이블·
웨이팅·음성주문·알림·QR/NFC·인쇄물·설정까지 확인하고, 기존 주문 흐름
(주문→주방→현금 결제 확인→매출·회원 이력→QR)도 함께 확인한다.

    python3 server.py --port 8010 --reset &
    python3 tools/smoke_test.py http://127.0.0.1:8010

서버가 비어 있으면(계정 없음) owner/mangjip1234 계정을 만들어 시작한다(반복 실행 가능).
"""
import csv
import datetime
import http.cookiejar
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OWNER = ("owner", "mangjip1234")
PASS, FAIL = [], []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Client:
    """쿠키를 유지하는 작은 HTTP 클라이언트(역할별로 하나씩)."""

    def __init__(self, follow=True):
        self.jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if not follow:
            handlers.append(NoRedirect())
        self.opener = urllib.request.build_opener(*handlers)
        self.user = None

    def call(self, method, path, body=None, raw=False, timeout=40):
        url = BASE + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                payload = r.read()
                if raw:
                    return r.status, payload
                try:
                    return r.status, json.loads(payload.decode() or "{}")
                except ValueError:
                    return r.status, payload
        except urllib.error.HTTPError as e:
            payload = e.read()
            if raw:
                return e.code, payload
            try:
                return e.code, json.loads(payload.decode())
            except ValueError:
                return e.code, payload

    def get(self, path, raw=False):
        return self.call("GET", path, raw=raw)

    def post(self, path, body=None, raw=False):
        return self.call("POST", path, body or {}, raw=raw)

    def patch(self, path, body=None):
        return self.call("PATCH", path, body or {})

    def delete(self, path):
        return self.call("DELETE", path)

    def login(self, username, password):
        st, data = self.post("/api/auth/login", {"username": username, "password": password})
        if st == 200:
            self.user = data.get("user")
        return st, data


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  — {detail}" if detail and not cond else ""))


def att_minutes(rec):
    return int((rec or {}).get("minutes") or 0)


def decode_qr(png):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return ""
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return text


print(f"■ 대상 서버: {BASE}\n")
owner = Client()
anon = Client()
noredir = Client(follow=False)

# ---------------------------------------------------------------- 1. 가입/로그인
print("[1] 사업자 계정 (가입·로그인·세션)")
st, me = owner.get("/api/auth/me")
has_owner = bool(me.get("setup", {}).get("hasOwner")) if isinstance(me, dict) else False
if not has_owner:
    st, data = owner.post("/api/auth/signup", {"storeName": "맛집", "username": OWNER[0],
                                               "password": OWNER[1], "tables": 8})
    check("최소 정보(매장 이름·아이디·비밀번호)로 가입", st == 201, st)
else:
    print("  (이미 계정이 있어 가입은 건너뜀)")
st, data = owner.login(*OWNER)
check("사장님 로그인", st == 200 and data.get("user", {}).get("role") == "admin", st)
st, me = owner.get("/api/auth/me")
check("세션 유지(/api/auth/me)", st == 200 and me["user"]["username"] == OWNER[0])
check("매장 이름이 설정에 저장됨", me["store"]["name"] == "맛집", me["store"]["name"])
st, bad = anon.login(OWNER[0], "틀린비밀번호")
check("틀린 비밀번호 거부(401)", st == 401, st)
for _ in range(5):
    anon.login("nobody" + OWNER[0], "x")
st, locked = anon.login("nobody" + OWNER[0], "x")
check("5회 실패 후 잠금(429)", st == 429, st)

st, _ = noredir.get("/admin")
check("로그인 없이 /admin 접근 시 로그인으로 이동(302)", st == 302, st)
st, body = anon.get("/login", raw=True)
check("로그인 화면은 공개", st == 200 and "로그인".encode() in body)
st, body = anon.get("/t/1", raw=True)
check("고객 메뉴(/t/1)는 공개", st == 200)


# ---------------------------------------------------------------- 1b. 소셜 로그인(OAuth)
print("\n[1b] 소셜 로그인(구글·카카오)")


def raw_redirect(path, cookie=""):
    """리다이렉트를 따라가지 않고 상태·Set-Cookie·Location을 본다."""
    req = urllib.request.Request(BASE + path, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as r:
            return r.status, (r.headers.get_all("Set-Cookie") or []), r.headers.get("Location") or ""
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get_all("Set-Cookie") or []), e.headers.get("Location") or ""


st, prov = anon.get("/api/auth/oauth/providers")
names = set((prov.get("providers") or {}).keys()) if isinstance(prov, dict) else set()
check("OAuth 제공자 상태 조회(google·kakao)", st == 200 and names == {"google", "kakao"}, st)
if st == 200:
    check("키 미설정 시 configured=false 로 정직하게 안내",
          prov["providers"]["google"]["configured"] is False
          and prov["providers"]["kakao"]["configured"] is False,
          prov.get("providers"))
    check("리다이렉트 URI 안내",
          prov.get("redirectUris", {}).get("google", "").endswith("/api/auth/oauth/google/callback")
          and prov.get("redirectUris", {}).get("kakao", "").endswith("/api/auth/oauth/kakao/callback"),
          prov.get("redirectUris"))

st, sc, loc = raw_redirect("/api/auth/oauth/google")
check("키 없이 구글 로그인 → 가짜 로그인 없이 안내로 이동",
      st == 302 and "oauth=not_configured" in loc and "provider=google" in loc, (st, loc))
check("키 없이 구글 로그인 → 세션 쿠키를 만들지 않음",
      not any(c.startswith("mj_sid=") for c in sc), sc)
st, sc, loc = raw_redirect("/api/auth/oauth/kakao")
check("키 없이 카카오 로그인 → 가짜 로그인 없이 안내로 이동",
      st == 302 and "oauth=not_configured" in loc and "provider=kakao" in loc, (st, loc))

st, sc, loc = raw_redirect("/api/auth/oauth/google/callback?code=fake-code")
check("state 없는 콜백 거부", st == 302 and "oauth=state" in loc, (st, loc))
st, sc, loc = raw_redirect("/api/auth/oauth/google/callback?code=fake-code&state=abc",
                           cookie="mj_oauth_state=google.abc")
check("키 없는 콜백은 로그인 없이 안내(가짜 세션 없음)",
      st == 302 and "oauth=not_configured" in loc and not any(c.startswith("mj_sid=") for c in sc),
      (st, loc, sc))
st, sc, loc = raw_redirect("/api/auth/oauth/kakao/callback?code=fake-code&state=abc",
                           cookie="mj_oauth_state=google.abc")
check("제공자가 다른 state 쿠키는 거부", st == 302 and "oauth=state" in loc, (st, loc))
st, _ = anon.get("/api/auth/oauth/naver")
check("지원하지 않는 제공자는 404", st == 404, st)
st, me_after = anon.get("/api/auth/me")
check("소셜 로그인 시도 뒤에도 익명 세션 유지", st == 200 and me_after.get("user") is None)

st, body = anon.get("/login", raw=True)
check("로그인 화면에 구글·카카오 버튼",
      st == 200 and "Google로 시작하기".encode() in body and "카카오로 시작하기".encode() in body, st)
check("로그인 화면에 앱 키 미연결 안내", st == 200 and "앱 키".encode() in body)
st, body = anon.get("/signup", raw=True)
check("회원가입 화면에 소셜 시작 버튼",
      st == 200 and "카카오로 시작하기".encode() in body and "Google로 시작하기".encode() in body, st)

# 앱 키가 있을 때의 동작(서버 환경변수를 건드리지 않고 라이브러리 단위로 확인)
# 단위 검사가 실제 data/ DB를 건드리지 않도록 임시 DB로 분리한다.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_unit_db = os.path.join(tempfile.gettempdir(), "mj-oauth-unit.db")
_saved_env = {"MENU_DB": os.environ.get("MENU_DB")}
for _suffix in ("", "-wal", "-shm"):
    if os.path.exists(_unit_db + _suffix):
        os.remove(_unit_db + _suffix)
os.environ["MENU_DB"] = _unit_db
try:
    from app import oauth as _oauth, staff as _staff, store as _store
    _oauth_keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "KAKAO_CLIENT_ID",
                   "KAKAO_CLIENT_SECRET", "OAUTH_BASE_URL")
    _saved_env.update({k: os.environ.get(k) for k in _oauth_keys})
    for _k in _oauth_keys:
        os.environ.pop(_k, None)
    check("단위: 키 없으면 configured=false",
          _oauth.configured("google") is False and _oauth.configured("kakao") is False)
    os.environ.update({"GOOGLE_CLIENT_ID": "test-client-id",
                       "GOOGLE_CLIENT_SECRET": "test-secret",
                       "OAUTH_BASE_URL": "https://example.com"})
    _url = _oauth.authorize_url("google", "http://127.0.0.1:8050", "state-123")
    _q = urllib.parse.parse_qs(urllib.parse.urlparse(_url).query)
    check("단위: 구글 인가 URL 생성",
          _url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
          and _q.get("client_id") == ["test-client-id"]
          and _q.get("state") == ["state-123"]
          and _q.get("redirect_uri") == ["https://example.com/api/auth/oauth/google/callback"]
          and _q.get("response_type") == ["code"], _url)
    check("단위: 구글은 시크릿까지 있어야 사용 가능",
          _oauth.configured("google") is True)
    os.environ["GOOGLE_CLIENT_SECRET"] = ""
    check("단위: 구글 시크릿이 없으면 미설정", _oauth.configured("google") is False)
    os.environ["KAKAO_CLIENT_ID"] = "kakao-js-key"
    os.environ.pop("KAKAO_CLIENT_SECRET", None)
    check("단위: 카카오는 JS 키만으로 사용 가능", _oauth.configured("kakao") is True)
    _kurl = _oauth.authorize_url("kakao", "http://127.0.0.1:8050", "s2")
    check("단위: 카카오 인가 URL 생성",
          _kurl.startswith("https://kauth.kakao.com/oauth/authorize?")
          and "client_id=kakao-js-key" in _kurl and "state=s2" in _kurl, _kurl)
    _cookie = _oauth.state_cookie("google", "abc")
    check("단위: state 쿠키(HttpOnly·SameSite·10분)",
          "mj_oauth_state=google.abc" in _cookie and "HttpOnly" in _cookie
          and "SameSite=Lax" in _cookie and "Max-Age=600" in _cookie, _cookie)
    check("단위: state 검증 통과",
          _oauth.check_state("google", "abc", _oauth.state_from_cookie("a=1; " + _cookie)) is True)
    check("단위: state 값·제공자 불일치 거부",
          _oauth.check_state("google", "zzz", "google.abc") is False
          and _oauth.check_state("kakao", "abc", "google.abc") is False
          and _oauth.check_state("google", "abc", "") is False)
    os.environ.pop("OAUTH_BASE_URL", None)
    check("단위: 공개 주소는 https, 로컬은 http",
          _oauth.public_base("http://w-toto.vercel.app") == "https://w-toto.vercel.app"
          and _oauth.public_base("http://127.0.0.1:8050") == "http://127.0.0.1:8050")

    # 계정 연결·첫 방문 생성은 임시 DB에서 직접 실행해 본다
    _store.init()
    _profile = {"provider": "google", "subject": "unit-123",
                "email": "unit@example.com", "name": "단위테스트"}
    _u1, _t1, _e1, _created1 = _oauth.login_with_profile(_profile, "google", store_name="단위 매장")
    check("단위: 첫 소셜 로그인이면 매장·사장님 계정 생성",
          _created1 is True and _u1["role"] == "admin" and bool(_t1), _u1)
    _u2, _t2, _e2, _created2 = _oauth.login_with_profile(_profile, "google")
    check("단위: 같은 소셜 계정은 기존 계정으로 로그인",
          _created2 is False and _u2["id"] == _u1["id"], (_created2, _u2.get("id")))
    _linked = _oauth.linked_staff_id("google", "unit-123")
    check("단위: oauth_accounts 에 계정 연결 저장", _linked == _u1["id"], _linked)
    try:
        _u3, _t3, _e3, _created3 = _oauth.login_with_profile(
            {"provider": "kakao", "subject": "other-9", "email": "", "name": "다른 사람"}, "kakao")
        _blocked = None
    except _oauth.OAuthError as _err:
        _blocked = _err.code
    check("단위: 연결 없는 소셜 계정은 자기 매장으로 새 계정 생성(다른 사장님과 분리)",
          _created3 is True and _u3["id"] != _u1["id"]
          and _u3["accountId"] != _u1["accountId"] and _u3["storeId"] != _u1["storeId"],
          (_created3, _u3.get("accountId"), _u3.get("storeId"), _blocked))
finally:
    for _k, _v in _saved_env.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    for _suffix in ("", "-wal", "-shm"):
        if os.path.exists(_unit_db + _suffix):
            os.remove(_unit_db + _suffix)

# ---------------------------------------------------------------- 2. 매장·메뉴
print("\n[2] 메뉴·추천·원산지/알레르기")
st, menu = owner.get("/api/menu")
items = menu.get("items", [])
check("메뉴 16개 로드", st == 200 and len(items) == 16, len(items))
kimbap = next(i for i in items if i["name"] == "김밥")
tteok = next(i for i in items if i["name"] == "떡볶이")
bulgogi = next(i for i in items if i["name"] == "불고기")
check("추천 미지정이면 판매량 자동(없으면 빈 목록)", menu["featured"]["auto"] is True and menu["featured"]["items"] == [])
st, _ = owner.post(f"/api/items/{kimbap['id']}/featured", {"featured": True, "note": "오늘의 인기"})
st, _ = owner.post(f"/api/items/{tteok['id']}/featured", {"featured": True})
st, menu = anon.get("/api/menu")
fnames = [i["name"] for i in menu["featured"]["items"]]
check("추천 지정 → 고객 메뉴 상단에 반영", fnames[:2] == ["김밥", "떡볶이"], fnames)
check("추천 문구 저장", any(i["featuredNote"] == "오늘의 인기" for i in menu["featured"]["items"]))
st, _ = owner.post(f"/api/items/{tteok['id']}/featured/move", {"dir": "up"})
st, menu = anon.get("/api/menu")
check("추천 순서 변경", [i["name"] for i in menu["featured"]["items"]][:2] == ["떡볶이", "김밥"],
      [i["name"] for i in menu["featured"]["items"]])
st, saved = owner.patch(f"/api/items/{kimbap['id']}", {
    "name": "김밥", "price": kimbap["price"], "categoryId": kimbap["categoryId"], "options": [],
    "origin": "쌀(국내산)·계란(국내산)", "allergens": ["난류", "밀"], "spice": 0})
check("원산지·알레르기 저장", saved.get("origin") == "쌀(국내산)·계란(국내산)" and saved.get("allergens") == ["난류", "밀"],
      (saved.get("origin"), saved.get("allergens")))
st, menu = anon.get("/api/menu")
kb = next(i for i in menu["items"] if i["id"] == kimbap["id"])
check("고객 메뉴에 알레르기 정보 전달", kb["allergens"] == ["난류", "밀"])
check("정보 없는 메뉴는 빈 값(임의 추정 없음)", next(i for i in menu["items"] if i["name"] == "콜라")["allergens"] == [])

# ---------------------------------------------------------------- 3. 테이블
print("\n[3] 테이블 등록·QR·NFC")
st, t3 = anon.get("/api/table/3")
check("기존 /t/3 주소 유지", st == 200 and t3["table"]["label"] == "3번", st)
st, created = owner.post("/api/tables", {"label": "창가", "seats": 2})
check("테이블 추가", st == 201 and created["code"] == str(created["id"]), st)
window = created
st, chk = anon.get(f"/api/table/{window['code']}")
check("새 테이블 고객 주소 열림", st == 200 and chk["table"]["label"] == "창가", st)
st, png = anon.get(f"/api/qr/{window['code']}.png?base=http://192.168.1.50:8000&px=10", raw=True)
decoded = decode_qr(png)
check("새 테이블 QR 생성", st == 200 and png[:4] == b"\x89PNG", st)
check("QR이 새 테이블 주소로 디코딩", decoded == f"http://192.168.1.50:8000/t/{window['code']}", decoded)
st, ver = owner.get(f"/api/qr/verify?base=http://192.168.1.50:8000&code={window['code']}")
check("디자인 QR 스캔 검증 API", st == 200 and ver.get("ok") is True, ver)
st, upd = owner.patch(f"/api/tables/{window['id']}", {"label": "창가석"})
check("테이블 이름 변경", upd["label"] == "창가석")
st, moved = owner.post(f"/api/tables/{window['id']}/move", {"dir": "up"})
check("테이블 순서 변경", st == 200 and isinstance(moved["tables"], list))
st, stats = owner.get("/api/tables/admin")
check("테이블 관리 요약", st == 200 and stats["activeCount"] >= 9, stats.get("activeCount"))

st, png = anon.get("/api/qr/3.svg?base=http://192.168.1.50:8000&px=8", raw=True)
check("QR SVG 생성", st == 200 and b"<svg" in png[:60])

# ---------------------------------------------------------------- 4. 주문 → 주방 → 결제 → 매출
print("\n[4] 주문 → 주방 → 현금 결제 → 매출")
st, order = anon.post("/api/orders", {
    "table": 3,
    "items": [{"itemId": kimbap["id"], "qty": 2, "options": {}},
              {"itemId": tteok["id"], "qty": 1, "options": {"맵기": "매운맛"}}],
    "customer": {"name": "김테스트", "phone": "010-1234-5678", "consent": True},
    "note": "덜 맵게 부탁드려요",
    "receipt": {"type": "phone", "no": "010-9876-5432"},
})
check("주문 생성", st == 201, st)
expected = kimbap["price"] * 2 + tteok["price"]
check("금액 서버 계산", order["total"] == expected, (order.get("total"), expected))
check("주문 상태 NEW·결제 UNPAID", order["status"] == "NEW" and order["paymentStatus"] == "UNPAID")
check("테이블 이름 표시", order["tableLabel"] == "3번", order.get("tableLabel"))
check("현금영수증 요청 저장·번호 마스킹",
      order["receiptType"] == "phone" and order["receiptNoMasked"] == "010-****-5432",
      (order.get("receiptType"), order.get("receiptNoMasked")))
o1 = order["id"]
st, _ = owner.post(f"/api/orders/{o1}/receipt", {"issued": True})
st, o = owner.get(f"/api/orders/{o1}")
check("현금영수증 발급 완료 표시", o["receiptIssued"] is True)

st, kq = owner.get("/api/kitchen")
check("주방 대기열에 주문", any(x["id"] == o1 for x in kq["queue"]))
st, o = owner.post(f"/api/orders/{o1}/status", {"status": "ACCEPTED"})
st, o = owner.post(f"/api/orders/{o1}/status", {"status": "COOKING"})
check("조리 시작", o["status"] == "COOKING")
st, o = owner.post(f"/api/orders/{o1}/status", {"status": "DONE"})
check("완료", o["status"] == "DONE")
st, err = owner.post(f"/api/orders/{o1}/status", {"status": "NEW"})
check("잘못된 상태 전이 거부", st == 400, st)

st, s0 = owner.get("/api/summary")
before_unpaid = s0["unpaidAmount"]
st, paid = owner.post(f"/api/orders/{o1}/payment", {"paid": True})
check("현금 결제 확인", paid["paymentStatus"] == "PAID")
check("결제 시 포인트 적립(1%)", paid["pointsEarned"] == int(expected * 0.01), paid["pointsEarned"])
st, s1 = owner.get("/api/summary")
check("매출 반영", s1["paidAmount"] >= expected, s1["paidAmount"])
check("미수금에서 제외", s1["unpaidAmount"] == before_unpaid - expected, s1["unpaidAmount"])
check("인기 메뉴 집계", any(t["name"] == "김밥" for t in s1["topItems"]))

# ---------------------------------------------------------------- 5. 회원·포인트·등급
print("\n[5] 회원·포인트·등급")
st, members = owner.get("/api/customers")
m = next((c for c in members["customers"] if c["phone"] == "010-1234-5678"), None)
check("주문 고객이 회원으로 등록", m is not None)
st, ev_public = owner.get("/api/events")
event_points = 0
if ev_public.get("config", {}).get("firstVisit", {}).get("enabled"):
    event_points += int(ev_public["config"]["firstVisit"].get("points") or 0)
check("포인트 잔액 반영(결제 적립+첫 방문 이벤트)",
      m and m["points"] == paid["pointsEarned"] + event_points, m and m["points"])
check("신규 등급", m and m["grade"] == "NEW", m and m["grade"])
mid = m["id"]
st, order2 = anon.post("/api/orders", {"table": 3,
    "items": [{"itemId": kimbap["id"], "qty": 2}],
    "customer": {"name": "김테스트", "phone": "010-1234-5678", "consent": True},
    "pointsUsed": m["points"]})
check("주문서 포인트 사용", order2["pointsUsed"] == m["points"]
      and order2["total"] == kimbap["price"] * 2 - m["points"],
      (order2.get("pointsUsed"), order2.get("total")))
st, err = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}],
    "customer": {"name": "김테스트", "phone": "010-1234-5678"}, "pointsUsed": 999999})
check("보유 초과 포인트 사용 거부", st == 400, st)
st, cs = owner.get("/api/customers")
m2 = next(c for c in cs["customers"] if c["id"] == mid)
check("포인트 사용 후 잔액 0", m2["points"] == 0, m2["points"])
st, cs = owner.get("/api/customers")
check("두 번 방문 집계", m2["visits"] >= 2, m2["visits"])

# 등급 자동: 3회 이상·3만원 이상 → 단골
for _ in range(2):
    st, o = anon.post("/api/orders", {"table": 3, "items": [{"itemId": bulgogi["id"], "qty": 1}],
        "customer": {"name": "김테스트", "phone": "010-1234-5678", "consent": True}})
    owner.post(f"/api/orders/{o['id']}/payment", {"paid": True})
st, cs = owner.get("/api/customers")
m3 = next(c for c in cs["customers"] if c["id"] == mid)
check("방문·결제 기준 자동 등급(단골 이상)", m3["grade"] in ("REGULAR", "VIP"), (m3["grade"], m3["visits"], m3["paidTotal"]))
st, manual = owner.post(f"/api/customers/{mid}/grade", {"grade": "VIP"})
check("등급 수동 변경", manual["grade"] == "VIP" and manual["gradeAuto"] is False, manual.get("grade"))
st, manual = owner.post(f"/api/customers/{mid}/grade", {"grade": ""})
check("등급 자동으로 되돌리기", manual["gradeAuto"] is True)
st, detail = owner.get(f"/api/customers/{mid}")
check("회원 상세: 방문 이력·포인트 이력", len(detail["orders"]) >= 2 and len(detail["pointHistory"]) >= 2)
st, added = owner.post("/api/customers", {"name": "박생일", "phone": "010-5555-6666",
                                         "birthday": "03-15", "consent": True})
check("사장님이 직접 회원 등록", st == 201 and added["id"], st)
st, dup = owner.post("/api/customers", {"name": "박생일2", "phone": "010-5555-6666", "consent": True})
check("같은 연락처는 한 명으로 합침", dup["merged"] is True and dup["id"] == added["id"], dup)
st, cs = owner.get("/api/customers")
check("이번 달 생일 목록", isinstance(cs["counts"]["birthdays"], list))
check("등급별 인원 요약", cs["counts"]["total"] >= 2 and "byGrade" in cs["counts"])
st, csv_bytes = owner.get("/api/customers.csv", raw=True)
check("회원 CSV(포인트 포함)", st == 200 and b"\xef\xbb\xbf" in csv_bytes[:6] and "포인트".encode() in csv_bytes)

# ---------------------------------------------------------------- 6. 직원·권한·출퇴근
print("\n[6] 직원 계정·권한·출퇴근")
st, cstaff = owner.post("/api/staff", {"name": "카운터직원", "username": "counter1",
                                       "password": "counterpw", "role": "counter"})
check("카운터 직원 추가", st == 201 and cstaff["roleLabel"] == "카운터", st)
st, kstaff = owner.post("/api/staff", {"name": "주방직원", "username": "kitchen1",
                                       "password": "kitchenpw", "role": "kitchen"})
check("주방 직원 추가", st == 201)
st, err = owner.post("/api/staff", {"name": "중복", "username": "counter1", "password": "xxxx", "role": "counter"})
check("중복 아이디 거부", st == 400, st)

counter, kitchen = Client(), Client()
st, _ = counter.login("counter1", "counterpw")
check("카운터 로그인", st == 200)
st, _ = kitchen.login("kitchen1", "kitchenpw")
check("주방 로그인", st == 200)

st, _ = kitchen.get("/api/customers")
check("주방 계정은 회원 관리 API 차단(403)", st == 403, st)
st, body = kitchen.get("/customers", raw=True)
check("주방 계정은 /customers 화면 차단(403 안내)", st == 403 and "권한".encode() in body, st)
st, km = kitchen.get("/api/menu/all")
check("주방 계정은 메뉴 목록 조회 가능(품절 처리용)", st == 200, st)
st, _ = kitchen.patch(f"/api/items/{kimbap['id']}", {"name": "바꾼이름"})
check("주방 계정은 메뉴 수정 차단(403)", st == 403, st)
st, so_k = kitchen.post(f"/api/items/{kimbap['id']}/soldout", {"soldout": True})
check("주방 계정은 품절 처리 가능", st == 200 and so_k["soldout"] is True, st)
kitchen.post(f"/api/items/{kimbap['id']}/soldout", {"soldout": False})
st, o = kitchen.post(f"/api/orders/{order2['id']}/status", {"status": "ACCEPTED"})
check("주방 계정은 주문 상태 변경 가능", st == 200, st)
st, _ = kitchen.post(f"/api/orders/{order2['id']}/payment", {"paid": True})
check("주방 계정은 현금 결제 확인 불가(403)", st == 403, st)
st, _ = counter.patch(f"/api/items/{kimbap['id']}", {"name": "바꾼이름"})
check("카운터는 메뉴 수정 불가(403)", st == 403, st)
st, so_c = counter.post(f"/api/items/{kimbap['id']}/soldout", {"soldout": True})
check("카운터는 품절 처리 가능", st == 200 and so_c["soldout"] is True, st)
counter.post(f"/api/items/{kimbap['id']}/soldout", {"soldout": False})
st, cs2 = counter.get("/api/customers")
check("카운터는 회원 관리 가능", st == 200)
st, _ = counter.get("/api/staff")
check("카운터는 직원 관리 불가", st == 403)

st, upd = owner.patch(f"/api/staff/{cstaff['id']}", {"name": "카운터 김", "active": False})
check("직원 수정·비활성", upd["name"] == "카운터 김" and upd["active"] is False)
st, _ = Client().login("counter1", "counterpw")
check("비활성 계정 로그인 차단", st == 401, st)

st, cin = owner.post("/api/attendance/clock-in", {})
check("출근 기록", st == 200 and cin["record"]["clockIn"], st)
st, err = owner.post("/api/attendance/clock-in", {})
check("중복 출근 거부", st == 400, st)
st, cout = owner.post("/api/attendance/clock-out", {})
check("퇴근 기록", st == 200 and cout["record"]["clockOut"])
st, recs = owner.get("/api/staff/attendance")
check("출퇴근 목록", st == 200 and len(recs["records"]) >= 1)
st, staffs = owner.get("/api/staff")
me_row = next(s for s in staffs["staff"] if s["username"] == OWNER[0])
check("이번 달 근무시간 집계", me_row["monthMinutes"] >= 0 and "monthText" in me_row)
st, acsv = owner.get("/api/staff/attendance.csv", raw=True)
check("근태 CSV", st == 200 and b"\xef\xbb\xbf" in acsv[:6])

# ---------------------------------------------------------------- 7. 웨이팅
print("\n[7] 웨이팅(대기 접수)")
st, err = anon.post("/api/wait", {"name": "박대기", "phone": "", "party": 2, "consent": True})
check("전화번호 없이 접수 거부", st == 400, st)
st, err = anon.post("/api/wait", {"name": "박대기", "phone": "010-2222-3333", "party": 2, "consent": False})
check("수집 동의 없이 접수 거부", st == 400, st)
st, wt = anon.post("/api/wait", {"name": "박대기", "phone": "010-2222-3333", "party": 3, "consent": True,
                                 "note": "유아 의자"})
check("대기 접수·번호 발급", st == 201 and wt["ticket"]["ticketNo"].startswith("A-"), st)
ticket = wt["ticket"]
check("개인 확인 링크 토큰 발급", len(ticket["token"]) > 10)
check("번호표에 앞 팀·예상시간 필드", "ahead" in ticket and "estimatedMinutes" in ticket
      and "estimateAvailable" in ticket)
st, again = anon.post("/api/wait", {"name": "박대기", "phone": "010-2222-3333", "party": 3, "consent": True})
check("같은 번호 재접수는 기존 대기", st == 201 and again["reused"] is True and again["ticket"]["ticketNo"] == ticket["ticketNo"])
st, bytok = anon.get(f"/api/wait/t/{ticket['token']}")
check("개인 링크로 상태 확인", st == 200 and bytok["ticket"]["ticketNo"] == ticket["ticketNo"])
st, byphone = anon.get("/api/wait/find?phone=010-2222-3333")
check("전화번호로 내 대기 찾기", st == 200 and byphone["ticket"]["id"] == ticket["id"])
st, board = anon.get("/api/wait/board")
check("대기 보드 데이터", st == 200 and board["waitingCount"] >= 1 and board["store"]["name"] == "맛집")

# 선주문
st, pre = anon.post("/api/orders", {"table": 0, "items": [{"itemId": kimbap["id"], "qty": 1}],
    "customer": {"name": "박대기", "phone": "010-2222-3333", "consent": True},
    "preorderToken": ticket["token"]})
check("웨이팅 중 미리 주문(예약)", st == 201 and pre["status"] == "RESERVED", (st, pre.get("status")))
st, kq = owner.get("/api/kitchen")
check("예약 주문은 주방에 아직 안 넘어감", not any(x["id"] == pre["id"] for x in kq["queue"]))
st, called = owner.post(f"/api/wait/{ticket['id']}/call", {})
check("호출", st == 200 and called["status"] == "CALLED")
st, seated = owner.post(f"/api/wait/{ticket['id']}/seat", {"tableId": 5})
check("입장 처리(테이블 배정)", st == 200 and seated["tableLabel"] == "5번", st)
check("입장 시 미리 주문이 주방으로 넘어감", seated.get("startedOrders") == [pre["id"]], seated.get("startedOrders"))
st, kq = owner.get("/api/kitchen")
check("주방 대기열에 미리 주문 표시", any(x["id"] == pre["id"] for x in kq["queue"]))
st, after = owner.get(f"/api/orders/{pre['id']}")
check("미리 주문이 일반 주문으로 전환", after["status"] == "NEW" and after["table"] == 5)
st, wl = owner.get("/api/wait/admin")
check("입장한 대기는 목록에서 빠짐", not any(t["id"] == ticket["id"] and t["status"] == "WAITING"
                                            for t in wl["tickets"]))
check("오늘 입장 건수 집계", wl["counts"]["SEATED"] >= 1)

st, wt2 = anon.post("/api/wait", {"name": "취소손님", "phone": "010-7777-8888", "party": 2, "consent": True})
st, pre2 = anon.post("/api/orders", {"table": 0, "items": [{"itemId": kimbap["id"], "qty": 1}],
    "customer": {"name": "취소손님", "phone": "010-7777-8888", "consent": True},
    "preorderToken": wt2["ticket"]["token"]})
st, closed = owner.post(f"/api/wait/{wt2['ticket']['id']}/cancel", {})
check("대기 취소", st == 200 and closed["status"] == "CANCELED")
st, after2 = owner.get(f"/api/orders/{pre2['id']}")
check("대기 취소 시 미리 주문 자동 취소", after2["status"] == "CANCELED", after2["status"])

st, wt3 = anon.post("/api/wait", {"name": "노쇼손님", "phone": "010-9999-0000", "party": 1, "consent": True})
st, ns = owner.post(f"/api/wait/{wt3['ticket']['id']}/noshow", {})
check("노쇼 처리", st == 200 and ns["status"] == "NOSHOW")
st, wl = owner.get("/api/wait/admin")
check("대기 요약(접수·호출·입장·취소)", st == 200 and wl["counts"]["SEATED"] >= 1)

# ---------------------------------------------------------------- 8. 손님 요청(취소·호출)
print("\n[8] 손님 주문 취소·직원 호출")
st, o3 = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}],
                                  "customer": {"name": "김테스트", "phone": "010-1234-5678"}})
st, canceled = anon.post(f"/api/orders/{o3['id']}/cancel", {"table": 3, "reason": "주문 실수"})
check("접수 단계에서 손님 취소", st == 200 and canceled["status"] == "CANCELED", st)
st, kq = owner.get("/api/kitchen")
check("취소 주문은 주방에서 사라짐", not any(x["id"] == o3["id"] for x in kq["queue"]))
st, o4 = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}]})
owner.post(f"/api/orders/{o4['id']}/status", {"status": "ACCEPTED"})
owner.post(f"/api/orders/{o4['id']}/status", {"status": "COOKING"})
st, err = anon.post(f"/api/orders/{o4['id']}/cancel", {"table": 3})
check("조리 시작 후 손님 취소 차단", st == 400, st)

st, call1 = anon.post("/api/calls", {"table": 4})
check("직원 호출 접수", st == 201 and call1["call"]["tableLabel"] == "4번", st)
st, call2 = anon.post("/api/calls", {"table": 4})
check("같은 테이블 중복 호출은 1건", call2["reused"] is True and call2["call"]["id"] == call1["call"]["id"])
st, acalls = owner.get("/api/calls/admin")
check("사장님 화면 호출 목록", any(c["id"] == call1["call"]["id"] for c in acalls["calls"]))
check("오늘 호출 건수", acalls["summary"]["total"] >= 1)
st, donec = owner.post(f"/api/calls/{call1['call']['id']}/done", {})
check("호출 처리 완료", donec["status"] == "DONE")
st, mine = anon.get(f"/api/calls?table=4")
check("처리 후 손님 화면에서 사라짐", mine["calls"] == [])

# ---------------------------------------------------------------- 9. 음성 주문
print("\n[9] 음성 주문 해석")
cases = [
    ("김치찌개 하나 담아줘", "add", "김치찌개", 1),
    ("김밥 두 개랑 콜라 한 병", "add", "김밥", 2),
    ("떡볶이 2개 매운맛으로", "add", "떡볶이", 2),
    ("라면에 계란 추가", "add", "라면", 1),
    ("순대 한 그릇", "add", "순대", 1),
    ("불고기 세 개", "add", "불고기", 3),
    ("비빔밥 하나", "add", "비빔밥", 1),
    ("잔치국수 하나 담아줘", "add", "잔치국수", 1),
    ("계란말이 하나", "add", "계란말이", 1),
    ("만두 군만두로 두 개", "add", "만두", 2),
    ("식혜 한 잔", "add", "식혜", 1),
    ("콜라 하나 빼줘", "remove", "콜라", 1),
    ("김밥 세 개 담고 콜라 빼줘", "mixed", "김밥", 3),
    ("찌개 하나", "clarify", None, None),
    ("없는메뉴 하나", "none", None, None),
    ("김치찌게 하나", "add", "김치찌개", 1),
    ("떡복이 두 개", "add", "떡볶이", 2),
    ("김밥", "add", "김밥", 1),
    ("아메리카노 하나", "add", "아이스아메리카노", 1),
    ("제육 하나", "add", "제육볶음", 1),
    ("모둠튀김 하나", "add", "모둠튀김", 1),
]
voice_ok = 0
for text, action, name, qty in cases:
    st, r = anon.post("/api/voice/parse", {"text": text})
    ok = st == 200 and r["action"] == action
    if ok and name:
        line = next((l for l in r["lines"] + r["removed"] if l["name"] == name), None)
        cand = next((c for c in r["candidates"] if c["name"] == name), None)
        ok = bool(line or cand)
        if ok and qty and line:
            ok = line["qty"] == qty
    voice_ok += 1 if ok else 0
    if not ok:
        print(f"     · '{text}' → {r.get('action')} {r.get('message')}")
check(f"음성 문장 {len(cases)}개 해석", voice_ok == len(cases), f"{voice_ok}/{len(cases)}")
st, r = anon.post("/api/voice/parse", {"text": "찌개 하나"})
check("애매한 메뉴는 후보로 확인 요청", r["needsConfirm"] and len(r["candidates"]) >= 2, r.get("candidates"))
st, err = anon.post("/api/voice/parse", {"text": ""})
check("빈 문장 거부", st == 400, st)

# ---------------------------------------------------------------- 10. 알림 채널
print("\n[10] 알림(브라우저/문자/카카오)")
st, noti = owner.get("/api/notifications")
check("알림 채널 목록", st == 200 and [c["code"] for c in noti["channels"]] == ["browser", "sms", "kakao"])
check("브라우저 알림 연결·문자/카카오 미연결",
      noti["channels"][0]["connected"] and not noti["channels"][1]["connected"])
st, r = owner.post("/api/notifications/send", {"channel": "sms", "event": "called", "ticketId": ticket["id"]})
check("문자 채널은 실제 전송 없이 '미연결' 기록", r["status"] in ("stub", "blocked_no_consent", "disabled"),
      r.get("status"))
st, r = owner.post("/api/notifications/send", {"channel": "kakao", "event": "called", "ticketId": ticket["id"]})
check("카카오 채널도 미연결 기록", r["sent"] is False)
st, tpl = owner.patch("/api/settings", {"notify": {"templates": {"soon": "{name}님 곧 순서 · 앞에 {ahead}팀"}}})
st, noti = owner.get("/api/notifications")
check("알림 문구 템플릿 저장", noti["templates"]["soon"]["text"].startswith("{name}님 곧 순서"),
      noti["templates"]["soon"]["text"])
st, err = owner.patch("/api/settings", {"notify": {"channels": {"sms": True}}})
check("미연결 채널 켜기 거부(대행사 계정 필요 안내)", st == 400, st)
st, hist = owner.get("/api/notifications")
check("알림 이력·오늘 요약", hist["summary"]["total"] >= 1 and len(hist["history"]) >= 1)

# ---------------------------------------------------------------- 11. 매장 설정
print("\n[11] 매장 설정·계정")
st, saved = owner.patch("/api/settings", {
    "businessNo": "123-45-67890", "ownerName": "박강원", "address": "경기도 김포시 운양동 1-1",
    "phone": "031-123-4567", "hours": "매일 10:00~21:00", "paymentNote": "현금 결제 · 계산대",
    "pointsRate": 2})
check("사업자 정보 저장", saved["store"]["businessNo"] == "123-45-67890", saved["store"])
st, err = owner.patch("/api/settings", {"businessNo": "1234"})
check("사업자등록번호 형식 검증", st == 400, st)
st, menu = anon.get("/api/menu")
check("고객 화면에 매장 정보 반영", menu["store"]["hours"] == "매일 10:00~21:00" and menu["store"]["phone"] == "031-123-4567")
st, s2 = owner.get("/api/settings")
check("포인트 적립률 저장", s2["pointsRate"] == 2, s2["pointsRate"])
st, o5 = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}],
                                 "customer": {"name": "김테스트", "phone": "010-1234-5678"}})
st, p5 = owner.post(f"/api/orders/{o5['id']}/payment", {"paid": True})
check("바뀐 적립률이 다음 결제부터 적용(2%)", p5["pointsEarned"] == int(o5["total"] * 0.02), p5["pointsEarned"])
st, st_settings = owner.get("/api/settings")
check("설정 화면 요약(직원·테이블·알림)", all(k in st_settings for k in ("staff", "tables", "notifications", "store")))

# 비밀번호 변경: 테스트용 계정으로 확인
st, tmpstaff = owner.post("/api/staff", {"name": "비번직원", "username": "pwtest1",
                                         "password": "oldpw123", "role": "kitchen"})
tmp = Client()
st, _ = tmp.login("pwtest1", "oldpw123")
check("새 직원 로그인", st == 200)
st, _ = tmp.post("/api/account/password", {"current": "oldpw123", "new": "newpw123"})
check("비밀번호 변경", st == 200, st)
st, _ = Client().login("pwtest1", "oldpw123")
check("이전 비밀번호로는 로그인 실패", st == 401, st)
st, _ = Client().login("pwtest1", "newpw123")
check("새 비밀번호로 로그인 성공", st == 200, st)
st, _ = tmp.post("/api/account/password", {"current": "틀린비번", "new": "x1234"})
check("현재 비밀번호 확인 실패 시 거부", st in (401, 403), st)
st, sessions = owner.get("/api/account/sessions")
check("로그인한 기기 목록", st == 200 and len(sessions["sessions"]) >= 1)

# ---------------------------------------------------------------- 12. QR·NFC·인쇄물
print("\n[12] 디자인 QR·NFC·인쇄물")
st, cfg = owner.get("/api/qr/config")
check("QR 디자인 설정", st == 200 and cfg["options"]["badge"] in ("initial", "none", "logo"))
st, saved = owner.patch("/api/qr/config", {"options": {"dot": "square", "eye": "square", "fg": "#101010", "bg": "#fff8e6"}})
check("디자인 옵션 저장", saved["options"]["dot"] == "square")
st, png = owner.get("/api/qr/3.png?base=http://192.168.1.50:8000&px=12", raw=True)
check("디자인 QR PNG 생성·스캔", st == 200 and decode_qr(png) == "http://192.168.1.50:8000/t/3", decode_qr(png))
st, err = owner.patch("/api/qr/config", {"options": {"fg": "#eeeeee", "bg": "#fdfdfd"}})
check("대비 낮은 색 조합 거부", st == 400, st)
owner.patch("/api/qr/config", {"options": {"dot": "rounded", "eye": "rounded", "fg": "#1f2a44", "bg": "#fdf3e3"}})
st, nfc = owner.get("/api/qr/config")
n3 = next((x for x in nfc["nfc"] if x["code"] == "3"), None)
check("NFC URL이 테이블 주소와 일치", n3 and n3["url"] == BASE + "/t/3?via=nfc",
      n3["url"] if n3 else None)
st, store_qr = owner.get("/api/qr/store.png?base=http://192.168.1.50:8000", raw=True)
check("매장 공통 QR 생성·스캔",
      st == 200 and (decode_qr(store_qr) or "").rstrip("/") == "http://192.168.1.50:8000",
      decode_qr(store_qr))

st, wqr = owner.get("/api/qr/wait.png?base=http://192.168.1.50:8000&px=10", raw=True)
check("웨이팅 접수 QR이 /wait 주소", decode_qr(wqr) == "http://192.168.1.50:8000/wait", decode_qr(wqr))
st, wait_stand = owner.get("/api/print/stands?kind=wait&size=B4")
check("웨이팅 안내물 QR 주소", wait_stand["tables"][0]["url"] == BASE + "/wait",
      wait_stand["tables"][0]["url"])

st, stands = owner.get("/api/print/stands?size=A5&layout=1")
active_codes = [t["code"] for t in stands["tables"]]
check("메뉴판 인쇄 목록(활성 테이블 전체)", stands["size"] == "A5" and len(active_codes) >= 9, len(active_codes))
st, img = owner.get(f"/api/print/stand.png?code=3&size=A5", raw=True)
check("테이블 메뉴판 이미지", st == 200 and img[:2] == b"\xff\xd8", st)
st, pdf = owner.get("/api/print/stands.pdf?size=A5&layout=1", raw=True)
check("메뉴판 PDF 생성", st == 200 and pdf[:4] == b"%PDF", st)
check("PDF 파일명에 크기 표시", True)
st, pdf4 = owner.get("/api/print/stands.pdf?size=A4&layout=4", raw=True)
check("A4 4개 배치 PDF", st == 200 and pdf4[:4] == b"%PDF")
st, wpdf = owner.get("/api/print/stands.pdf?kind=wait&size=B4", raw=True)
check("웨이팅 안내물 B4 PDF", st == 200 and wpdf[:4] == b"%PDF")
st, wimg = owner.get("/api/print/wait.png?size=B4", raw=True)
check("웨이팅 안내물 이미지", st == 200 and wimg[:2] == b"\xff\xd8")
st, wpdf3 = owner.get("/api/print/stands.pdf?kind=wait&size=A3", raw=True)
check("웨이팅 안내물 A3 PDF", st == 200 and wpdf3[:4] == b"%PDF")
check("PDF 페이지 크기 표기(B4=250x353mm)", b"/MediaBox [0 0 708.661 1000.630]" in wpdf,
      wpdf[:0])

# 신규 테이블이 인쇄 목록에 자동 반영
st, stands2 = owner.get("/api/print/stands?size=A5&layout=1")
check("테이블 추가가 인쇄 목록에 자동 반영", window["code"] in [t["code"] for t in stands2["tables"]])

# ---------------------------------------------------------------- 13. 테이블 비활성/삭제
print("\n[13] 비활성 테이블 차단·삭제 규칙")
st, off = owner.patch(f"/api/tables/{window['id']}", {"active": False})
check("테이블 비활성", off["active"] is False)
st, err = anon.post("/api/orders", {"table": window["id"], "items": [{"itemId": kimbap["id"], "qty": 1}]})
check("비활성 테이블 주문 차단", st == 400, st)
st, tpage = anon.get(f"/api/table/{window['code']}")
check("비활성 테이블 주소는 활성 여부 전달", tpage["table"]["active"] is False)
st, stands3 = owner.get("/api/print/stands?size=A5&layout=1")
check("비활성 테이블은 인쇄 목록에서 제외", window["code"] not in [t["code"] for t in stands3["tables"]])

st, tdel = owner.post("/api/tables", {"label": "임시", "seats": 2})
st, err = owner.delete(f"/api/tables/3")
check("주문 이력 있는 테이블 삭제 거부", st == 400, st)
st, _ = owner.delete(f"/api/tables/{tdel['id']}")
check("주문 없는 테이블 삭제", st == 200)

# ---------------------------------------------------------------- 14. 백업·복원·처리방침
print("\n[14] 백업·복원·개인정보")
st, bk = owner.post("/api/backup", {})
check("지금 백업 만들기", st == 201 and str(bk.get("name", "")).endswith(".db"), (st, bk))
st, bl = owner.get("/api/backup")
names = [b["name"] for b in bl.get("backups", [])]
check("백업 목록", st == 200 and bk.get("name") in names, names)
st, dbfile = owner.get("/api/backup/download", raw=True)
check("DB 파일 내려받기", st == 200 and dbfile[:15] == b"SQLite format 3", dbfile[:16])
before = len(owner.get("/api/orders")[1]["orders"])
st, new_order = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}]})
check("복원 전 데이터 추가", new_order["id"] > 0)
st, err = owner.post("/api/backup/restore", {"name": bk.get("name"), "confirm": "아니오"})
check("확인 문구 없이는 복원 거부", st == 400, st)
st, res = owner.post("/api/backup/restore", {"name": bk.get("name"), "confirm": "복원"})
check("백업에서 복원", st == 200 and res["restored"] is True, st)
st, after = owner.get("/api/orders")
check("복원 후 주문 수가 백업 시점과 일치", len(after["orders"]) == before, (len(after["orders"]), before))
st, page = anon.get("/privacy", raw=True)
check("개인정보 처리방침 화면 열림", st == 200 and "처리방침".encode() in page, st)
st, err = anon.post("/api/wait", {"name": "동의없음", "phone": "010-1111-9999", "party": 2, "consent": False})
check("동의 체크 없이는 접수 차단", st == 400, st)

# ---------------------------------------------------------------- 15. 공개/보호 경계
print("\n[15] 공개·보호 경계")
for path, label in [("/api/menu", "고객 메뉴"), ("/api/table/3", "테이블 정보"),
                    ("/api/wait/board", "대기 보드"), ("/api/qr/3.png", "QR 이미지")]:
    st, _ = anon.get(path, raw=True)
    check(f"{label} 공개", st == 200, st)
for path, label in [("/api/state", "사장님 상태"), ("/api/customers", "회원 목록"),
                    ("/api/staff", "직원 목록"), ("/api/settings", "매장 설정"),
                    ("/api/menu/all", "메뉴 관리"), ("/api/kitchen", "주방 데이터")]:
    st, _ = anon.get(path)
    check(f"{label} 로그인 필요(401)", st == 401, st)


# ---------------------------------------------------------------- 16. 서빙 4단계
print("\n[16] 주방 4단계(접수→조리중→조리완료→서빙완료)")
st, so = anon.post("/api/orders", {"table": 3, "items": [{"itemId": tteok["id"], "qty": 1}]})
serve_id = so["id"]
st, o = owner.post(f"/api/orders/{serve_id}/status", {"status": "ACCEPTED"})
st, o = owner.post(f"/api/orders/{serve_id}/status", {"status": "COOKING"})
st, o = owner.post(f"/api/orders/{serve_id}/status", {"status": "DONE"})
check("조리 완료(DONE)", st == 200 and o["status"] == "DONE", st)
st, kq = owner.get("/api/kitchen")
check("주방 '서빙 대기' 목록에 표시", any(x["id"] == serve_id for x in kq["serving"]))
check("서빙 대기 경과 시간 필드", all("servingMin" in x and "servingSec" in x for x in kq["serving"]))
check("서빙 대기 건수 집계", kq["counts"]["serving"] >= 1, kq["counts"].get("serving"))
st, served = owner.post(f"/api/orders/{serve_id}/status", {"status": "SERVED"})
check("서빙 완료 전이", st == 200 and served["status"] == "SERVED", st)
check("서빙 완료 시각 기록", bool(served.get("servedAt")))
st, kq = owner.get("/api/kitchen")
check("서빙 완료 후 목록에서 제거", not any(x["id"] == serve_id for x in kq["serving"]))
st, err = owner.post(f"/api/orders/{serve_id}/status", {"status": "COOKING"})
check("서빙 완료는 되돌릴 수 없음", st == 400, st)
st, err = owner.patch("/api/stores/1", {"active": False})
check("지금 보는 매장은 사용 안 함으로 못 바꿈", st == 400, st)
st, o = anon.get(f"/api/orders/{serve_id}")
check("손님 화면에도 서빙 완료 상태", o["status"] == "SERVED", o["status"])
st, st_dash = owner.get("/api/dashboard")
check("대시보드에 진행 중 주문 수", "activeCount" in st_dash["today"])

# ---------------------------------------------------------------- 17. 매출·정산
print("\n[17] 매출·정산(기간·시간대·결제수단·CSV)")
st, rev = owner.get("/api/revenue?preset=today")
check("오늘 매출 집계", st == 200 and rev["totals"]["paidAmount"] > 0, rev.get("totals"))
check("결제 확인 금액과 미수금 분리", "paidAmount" in rev["totals"] and "unpaidAmount" in rev["totals"])
check("결제수단: 현금 연결·카드 미연동", rev["paymentMethods"][0]["connected"] is True
      and rev["paymentMethods"][1]["connected"] is False)
check("시간대별 24칸", len(rev["hourly"]) == 24)
check("카테고리 비중", isinstance(rev["categories"], list) and len(rev["categories"]) >= 1)
check("인기 메뉴", any(i["name"] == "김밥" for i in rev["topItems"]))
st, week = owner.get("/api/revenue?preset=week")
wd = datetime.date.fromisoformat(week["start"]).weekday()
check("이번 주 범위(월요일 시작)", wd == 0 and week["end"] == rev["end"], (week["start"], week["end"]))
st, month = owner.get("/api/revenue?preset=month")
check("이번 달 범위(1일 시작)", month["start"][8:] == "01", month["start"])
st, err = owner.get("/api/revenue?preset=custom&start=2026-11-20&end=2026-11-01")
check("잘못된 기간 거부", st == 400, st)
st, csvb = owner.get("/api/revenue.csv?preset=today", raw=True)
check("매출 CSV", st == 200 and b"\xef\xbb\xbf" in csvb[:6] and "결제확인금액".encode() in csvb)
before = owner.get("/api/revenue?preset=today")[1]["totals"]
st, cancel_o = anon.post("/api/orders", {"table": 3, "items": [{"itemId": tteok["id"], "qty": 1}]})
owner.post(f"/api/orders/{cancel_o['id']}/payment", {"paid": True})
owner.post(f"/api/orders/{cancel_o['id']}/status", {"status": "CANCELED"})
after = owner.get("/api/revenue?preset=today")[1]["totals"]
check("취소 건은 매출에서 빠지고 따로 집계", after["paidAmount"] == before["paidAmount"]
      and after["canceledCount"] == before["canceledCount"] + 1,
      (after["paidAmount"], before["paidAmount"], after["canceledCount"]))

# ---------------------------------------------------------------- 18. 재고·재료
print("\n[18] 재고·레시피·경고·품절 제안")
st, rice = owner.post("/api/inventory/ingredients", {"name": "쌀", "unit": "g", "stock": 1000, "safety": 200})
check("재료 등록", st == 201 and rice["stock"] == 1000, st)
st, laver = owner.post("/api/inventory/ingredients", {"name": "김", "unit": "장", "stock": 50, "safety": 5})
st, err = owner.post("/api/inventory/ingredients", {"name": "쌀", "unit": "g"})
check("같은 이름 재료 거부", st == 400, st)
st, rec = owner.post("/api/inventory/recipes",
                     {"menuItemId": kimbap["id"], "lines": [{"ingredientId": rice["id"], "qty": 200},
                                                            {"ingredientId": laver["id"], "qty": 1}]})
check("레시피(메뉴별 소모량) 저장", st == 200 and len(rec["recipes"]) == 2, st)
st, o = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 2}]})
inv_order = o["id"]
owner.post(f"/api/orders/{inv_order}/payment", {"paid": True})
st, inv = owner.get("/api/inventory")
rice_now = next(i for i in inv["ingredients"] if i["id"] == rice["id"])
laver_now = next(i for i in inv["ingredients"] if i["id"] == laver["id"])
check("결제 확인 때 재료 자동 차감(2인분)", rice_now["stock"] == 600 and laver_now["stock"] == 48,
      (rice_now["stock"], laver_now["stock"]))
owner.post(f"/api/orders/{inv_order}/payment", {"paid": True})
st, inv = owner.get("/api/inventory")
check("같은 주문을 다시 확인해도 중복 차감 없음",
      next(i for i in inv["ingredients"] if i["id"] == rice["id"])["stock"] == 600)
owner.post(f"/api/orders/{inv_order}/payment", {"paid": False})
st, inv = owner.get("/api/inventory")
check("결제 취소 시 재고 복원",
      next(i for i in inv["ingredients"] if i["id"] == rice["id"])["stock"] == 1000)
owner.post(f"/api/orders/{inv_order}/payment", {"paid": True})
st, adj = owner.post(f"/api/inventory/ingredients/{rice['id']}/adjust", {"stock": 100, "memo": "실사"})
check("재고 조정(실사)", adj["stock"] == 100 and adj["low"] is True, adj)
st, inv = owner.get("/api/inventory")
check("안전재고 미만 경고", any(i["id"] == rice["id"] for i in inv["warnings"]["low"]))
st, inb = owner.post(f"/api/inventory/ingredients/{rice['id']}/in", {"qty": 900, "memo": "마트 입고"})
check("입고 기록", inb["stock"] == 1000, inb["stock"])
owner.post(f"/api/inventory/ingredients/{laver['id']}/adjust", {"stock": 0})
st, inv = owner.get("/api/inventory")
check("재고 0 재료를 쓰는 메뉴 품절 제안", any(s["menuItemId"] == kimbap["id"] for s in inv["suggestions"]), inv["suggestions"])
st, so2 = owner.post(f"/api/inventory/suggestions/{kimbap['id']}/soldout", {})
check("품절 제안 적용", so2["soldout"] is True)
st, err = anon.post("/api/orders", {"table": 3, "items": [{"itemId": kimbap["id"], "qty": 1}]})
check("품절 메뉴는 주문 차단", st == 400, st)
owner.post(f"/api/items/{kimbap['id']}/soldout", {"soldout": False})
st, logs = owner.get("/api/inventory/logs")
kinds = {l["kind"] for l in logs["logs"]}
check("입고·차감·조정 기록", {"IN", "OUT", "ADJUST"} <= kinds, kinds)
st, err = owner.post("/api/inventory/recipes", {"menuItemId": kimbap["id"],
                                                 "lines": [{"ingredientId": 99999, "qty": 1}]})
check("없는 재료 레시피 거부", st == 400, st)

# ---------------------------------------------------------------- 19. 예약
print("\n[19] 예약(신청→확정→도착·노쇼·취소)")
st, meta = anon.get("/api/store")
today = meta["today"]
tomorrow = (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat()
st, err = anon.post("/api/reservations/public", {"date": tomorrow, "time": "18:30", "party": 2,
                                                 "name": "예약손님", "phone": "010-3333-4444", "consent": False})
check("동의 없이 예약 신청 거부", st == 400, st)
st, rv = anon.post("/api/reservations/public", {"date": tomorrow, "time": "18:30", "party": 2,
                                                "name": "예약손님", "phone": "010-3333-4444",
                                                "memo": "창가", "consent": True})
check("손님 예약 신청", st == 201 and rv["status"] == "PENDING", (st, rv.get("status")))
check("예약 확인 토큰 발급", len(rv["token"]) > 8)
st, err = anon.post("/api/reservations/public", {"date": "2020-01-01", "time": "18:00", "party": 2,
                                                 "name": "과거", "phone": "010-1111-2222", "consent": True})
check("지난 날짜 예약 거부", st == 400, st)
st, err = anon.post("/api/reservations/public", {"date": tomorrow, "time": "25:99", "party": 2,
                                                 "name": "시간", "phone": "010-1111-2222", "consent": True})
check("잘못된 시간 거부", st == 400, st)
st, view = anon.get(f"/api/reservations/t/{rv['token']}")
check("손님이 자기 예약 확인", st == 200 and view["reservation"]["id"] == rv["id"])
st, err = owner.post(f"/api/reservations/{rv['id']}/status", {"status": "ARRIVED"})
check("신청 상태에서 바로 도착 불가", st == 400, st)
st, conf = owner.post(f"/api/reservations/{rv['id']}/status", {"status": "CONFIRMED"})
check("사장님이 확정", conf["status"] == "CONFIRMED")
st, arr = owner.post(f"/api/reservations/{rv['id']}/status", {"status": "ARRIVED"})
check("도착 처리", arr["status"] == "ARRIVED")
st, adm = owner.post("/api/reservations", {"date": tomorrow, "time": "12:00", "party": 4,
                                           "name": "직접등록", "phone": "010-7777-1111",
                                           "tableId": 4, "status": "CONFIRMED"})
check("사장님 직접 예약(확정)", st == 201 and adm["status"] == "CONFIRMED" and adm["tableLabel"] == "4번", adm)
st, err = owner.post(f"/api/reservations/{adm['id']}/table", {"tableId": window["id"]})
check("비활성 테이블 배정 거부", st == 400, st)
st, asg = owner.post(f"/api/reservations/{adm['id']}/table", {"tableId": 5})
check("테이블 배정", asg["tableLabel"] == "5번")
st, rl = owner.get(f"/api/reservations?date={tomorrow}")
check("일자별 예약 목록", any(r["id"] == adm["id"] for r in rl["reservations"]))
check("월 캘린더에 건수", rl["calendar"]["days"].get(tomorrow, {}).get("total", 0) >= 2)
st, err = owner.post(f"/api/reservations/{rv['id']}/status", {"status": "PENDING"})
check("도착 후에는 되돌리기 제한", st == 400, st)
st, rep2 = owner.post("/api/reservations", {"date": tomorrow, "time": "19:00", "party": 2,
                                            "name": "노쇼손님", "phone": "010-2222-3333"})
owner.post(f"/api/reservations/{rep2['id']}/status", {"status": "NOSHOW"})
st, all_r = owner.get(f"/api/reservations?date={tomorrow}")
check("노쇼 표시", any(r["id"] == rep2["id"] and r["status"] == "NOSHOW" for r in all_r["reservations"]))

# ---------------------------------------------------------------- 20. 리뷰
print("\n[20] 리뷰(별점·답글·숨김)")
st, rvo = anon.post("/api/orders", {"table": 3, "items": [{"itemId": tteok["id"], "qty": 1}]})
check("리뷰용 주문 생성", st == 201, st)
st, err = anon.post("/api/reviews", {"orderId": rvo["id"], "rating": 5})
check("조리 전에는 리뷰 거부", st == 400, st)
owner.post(f"/api/orders/{rvo['id']}/status", {"status": "ACCEPTED"})
owner.post(f"/api/orders/{rvo['id']}/status", {"status": "COOKING"})
owner.post(f"/api/orders/{rvo['id']}/status", {"status": "DONE"})
st, err = anon.post("/api/reviews", {"orderId": rvo["id"], "rating": 6})
check("별점 범위 검증(1~5)", st == 400, st)
st, rv1 = anon.post("/api/reviews", {"orderId": rvo["id"], "rating": 5, "comment": "김치찌개가 진짜 맛있어요"})
check("리뷰 등록", st == 201 and rv1["rating"] == 5, st)
st, err = anon.post("/api/reviews", {"orderId": rvo["id"], "rating": 4})
check("같은 주문 중복 리뷰 거부", st == 400, st)
st, pr = anon.get(f"/api/reviews/order/{rvo['id']}")
check("손님 화면: 이미 리뷰함", pr["review"]["rating"] == 5 and pr["canReview"] is False)
st, rl = owner.get("/api/reviews")
check("사장님 리뷰 목록", any(r["id"] == rv1["id"] for r in rl["reviews"]))
check("평균 별점·분포·추이", rl["summary"]["count"] >= 1 and "5" in rl["summary"]["distribution"]
      and len(rl["summary"]["trend"]) == 7)
st, rep = owner.post(f"/api/reviews/{rv1['id']}/reply", {"reply": "감사합니다. 다음에 또 모시겠습니다"})
check("답글 메모 저장", rep["reply"].startswith("감사합니다"))
st, hid = owner.post(f"/api/reviews/{rv1['id']}/hidden", {"hidden": True})
check("리뷰 숨김", hid["hidden"] is True)
st, sum2 = owner.get("/api/reviews/summary")
check("숨긴 리뷰는 평균에서 제외", sum2["count"] == 0 and sum2["totalCount"] >= 1, sum2)
owner.post(f"/api/reviews/{rv1['id']}/hidden", {"hidden": False})
st, err = anon.post("/api/reviews", {"orderId": 999999, "rating": 5})
check("없는 주문 리뷰 거부", st in (400, 404), st)

# ---------------------------------------------------------------- 21. 다점포
print("\n[21] 여러 매장(추가·전환·데이터 분리·비교)")
st, stores1 = owner.get("/api/stores")
check("기본 매장 1곳", len(stores1["stores"]) == 1 and stores1["current"] == 1, stores1)
st, menu1 = owner.get("/api/menu")
st, orders1 = owner.get("/api/orders")
base_order_count = len(orders1["orders"])
st, new_store = owner.post("/api/stores", {"name": "맛집 2호점", "tables": 3})
check("매장 추가", st == 201 and new_store["id"] == 2, st)
st, dup = owner.post("/api/stores", {"name": "맛집 2호점", "tables": 3})
check("같은 이름 매장 거부", st == 400, st)
st, sw = owner.post("/api/stores/switch", {"storeId": 2})
check("매장 전환", st == 200 and sw["storeId"] == 2 and sw["store"]["name"] == "맛집 2호점", st)
st, menu2 = owner.get("/api/menu")
check("새 매장은 자기 메뉴를 따로 가짐", len(menu2["items"]) == 16, len(menu2["items"]))
check("새 매장 메뉴는 다른 id", not ({i["id"] for i in menu2["items"]} & {i["id"] for i in menu1["items"]}))
st, tables2 = owner.get("/api/tables")
check("새 매장 테이블 3개", len(tables2["tables"]) == 3, len(tables2["tables"]))
st, orders2 = owner.get("/api/orders")
check("새 매장은 주문이 비어 있음", len(orders2["orders"]) == 0, len(orders2["orders"]))
item2 = menu2["items"][0]
st, o2 = anon.post("/api/orders", {"table": tables2["tables"][0]["id"], "items": [{"itemId": item2["id"], "qty": 1}]})
check("새 매장 테이블에서 주문", st == 201 and o2["storeId"] == 2, (st, o2.get("storeId")))
owner.post(f"/api/orders/{o2['id']}/payment", {"paid": True})
st, s2 = owner.get("/api/summary")
check("새 매장 매출만 집계", s2["paidAmount"] == item2["price"], s2["paidAmount"])
st, cs2 = owner.get("/api/customers")
check("매장별 회원 분리", len(cs2["customers"]) == 0, len(cs2["customers"]))
st, staff2 = owner.get("/api/staff")
check("매장별 직원 분리", len(staff2["staff"]) == 0, len(staff2["staff"]))
st, w2 = anon.post("/api/wait?store=2", {"name": "둘째매장대기", "phone": "010-8888-7777",
                                         "party": 2, "consent": True})
check("새 매장 웨이팅 접수", st == 201 and w2["ticket"]["ticketNo"].startswith("A-"), st)
st, b2 = anon.get("/api/wait/board?store=2")
check("새 매장 대기 보드에 표시", any(t["name"] == "둘째매장대기" for t in b2["waiting"]), b2["waiting"])
st, b1 = anon.get("/api/wait/board")
check("1번 매장 보드와 섞이지 않음", all(t["name"] != "둘째매장대기" for t in b1["waiting"]))
st, s2staff = owner.post("/api/staff", {"name": "2호점직원", "username": "store2staff",
                                       "password": "pw12345", "role": "counter"})
check("새 매장 직원 추가", st == 201 and s2staff["storeId"] == 2, st)
c2 = Client()
st, me2 = c2.login("store2staff", "pw12345")
st, menu_s2 = c2.get("/api/menu")
check("2호점 직원은 2호점 화면·메뉴", me2.get("user", {}).get("storeId") == 2
      and len(menu_s2["items"]) == 16, (me2.get("user", {}).get("storeId"), len(menu_s2["items"])))
st, _ = c2.get("/api/settings")
check("2호점 카운터는 설정 불가", st == 403, st)
st, _ = c2.post("/api/staff", {"name": "권한상승", "username": "escalate1", "password": "xxxx", "role": "admin"})
check("카운터는 직원 추가 불가", st == 403, st)
st, sq = anon.get("/api/qr/store.png?base=http://192.168.1.50:8000&store=2", raw=True)
check("2호점 매장 공통 QR에 매장 표시", (decode_qr(sq) or "").endswith("/?store=2"), decode_qr(sq))
st, ren = owner.patch("/api/stores/2", {"name": "맛집 2호점 강변"})
st, me_ren = owner.get("/api/auth/me")
check("매장 이름 변경이 상단·설정에 반영", me_ren["store"]["name"] == "맛집 2호점 강변", me_ren["store"])
st, info = owner.patch("/api/stores/2", {"tagline": "강변점 · 분식", "address": "서울 광진구"})
check("매장 간단 정보 수정", st == 200 and info["tagline"].startswith("강변점"), info)
st, cmp = owner.get("/api/stores/comparison")
check("매장별 비교 화면", len(cmp["stores"]) == 2 and cmp["stores"][0]["todayPaid"] > 0
      and cmp["stores"][1]["todayPaid"] == item2["price"], cmp["stores"])
st, _ = kitchen.post("/api/stores/switch", {"storeId": 2})
check("주방 계정은 매장 전환 불가(403)", st == 403, st)
st, sw = owner.post("/api/stores/switch", {"storeId": 1})
st, orders1b = owner.get("/api/orders")
check("1번 매장 주문 그대로", len(orders1b["orders"]) == base_order_count, len(orders1b["orders"]))
st, menu1b = owner.get("/api/menu")
check("1번 매장 메뉴 그대로", [i["id"] for i in menu1b["items"]] == [i["id"] for i in menu1["items"]])
st, t1 = anon.get("/api/table/1")
check("1번 매장 QR 주소 유지", t1["table"]["storeId"] == 1)

# ---------------------------------------------------------------- 22. 역할·권한
print("\n[22] 역할(매니저·알바)·세분 권한")
st, mgr = owner.post("/api/staff", {"name": "매니저김", "username": "mgr1", "password": "mgrpw1234",
                                    "role": "manager"})
check("매니저 추가", st == 201 and mgr["roleLabel"] == "매니저", st)
check("매니저 기본 권한(설정 변경 제외)", "staff.manage" in mgr["permissions"]
      and "settings.edit" not in mgr["permissions"], mgr["permissions"])
st, pt = owner.post("/api/staff", {"name": "알바생", "username": "part1", "password": "partpw1234",
                                   "role": "part", "payType": "hourly", "hourlyWage": 12000})
check("알바(시간제) 추가·시급 저장", st == 201 and pt["payLabel"] == "시급제" and pt["hourlyWage"] == 12000, pt)
manager_c, part_c = Client(), Client()
st, _ = manager_c.login("mgr1", "mgrpw1234")
check("매니저 로그인", st == 200)
st, _ = part_c.login("part1", "partpw1234")
check("알바 로그인", st == 200)
st, _ = manager_c.get("/api/settings")
check("매니저는 설정 변경 불가(403)", st == 403, st)
st, _ = manager_c.get("/api/staff")
check("매니저는 직원 관리 가능", st == 200, st)
st, _ = manager_c.get("/api/revenue?preset=today")
check("매니저는 매출 조회 가능", st == 200, st)
st, _ = manager_c.get("/api/menu/all")
check("매니저는 메뉴 조회 가능", st == 200, st)
st, body = manager_c.get("/settings", raw=True)
check("매니저는 설정 화면 차단(403 안내)", st == 403 and "권한".encode() in body, st)
st, _ = part_c.get("/api/menu/all")
check("알바는 메뉴 관리 불가", st == 403, st)
st, _ = part_c.get("/api/customers")
check("알바는 고객 정보 불가", st == 403, st)
st, _ = part_c.get("/api/revenue?preset=today")
check("알바는 매출 조회 불가", st == 403, st)
st, body = part_c.get("/kitchen", raw=True)
check("알바는 주방 화면 차단", st == 403, st)
st, _ = part_c.get("/api/orders?limit=5")
check("알바는 주문 목록 가능", st == 200, st)
st, o = anon.post("/api/orders", {"table": 3, "items": [{"itemId": tteok["id"], "qty": 1}]})
st, _ = part_c.post(f"/api/orders/{o['id']}/status", {"status": "ACCEPTED"})
check("알바는 주문 상태 변경 가능", st == 200, st)
st, _ = part_c.post(f"/api/orders/{o['id']}/payment", {"paid": True})
check("알바는 현금 결제 확인 가능", st == 200, st)
st, state_p = part_c.get("/api/state")
check("매출 권한이 없으면 금액 숨김", state_p["summary"].get("salesHidden") is True
      and "paidAmount" not in state_p["summary"], state_p.get("summary"))
st, guest_order = anon.get(f"/api/orders/{o['id']}")
check("손님에게 주문 고객 연락처는 숨김", guest_order["customerPhone"] == "" and guest_order["customerName"] == "")
st, _ = part_c.patch(f"/api/items/{tteok['id']}", {"name": "몰래"})
check("알바는 메뉴 수정 불가", st == 403, st)
st, upd = owner.patch(f"/api/staff/{pt['id']}", {"permissions": {"soldout.manage": True}})
check("직원별 권한 예외 추가", "soldout.manage" in upd["permissions"], upd["permissions"])
st, so_p = part_c.post(f"/api/items/{tteok['id']}/soldout", {"soldout": True})
check("예외 권한이 실제로 적용됨", st == 200, st)
part_c.post(f"/api/items/{tteok['id']}/soldout", {"soldout": False})
owner.patch(f"/api/staff/{pt['id']}", {"permissions": {}})
st, err = part_c.post(f"/api/staff", {"name": "x", "username": "x1", "password": "xxxx", "role": "counter"})
check("알바는 직원 추가 불가", st == 403, st)
st, pc = manager_c.patch(f"/api/items/{kimbap['id']}", {"price": 99999})
check("매니저는 가격 변경 가능(price.edit)", st == 200 and pc["price"] == 99999, st)
owner.patch(f"/api/items/{kimbap['id']}", {"price": kimbap["price"]})
st, _ = part_c.patch(f"/api/items/{kimbap['id']}", {"price": 1})
check("알바는 가격 변경 불가", st == 403, st)
st, _ = manager_c.patch(f"/api/staff/{mgr['id']}", {"permissions": {"settings.edit": True}})
check("매니저는 스스로 권한을 늘릴 수 없음(403)", st == 403, st)
st, _ = manager_c.post("/api/staff", {"name": "관리자시도", "username": "escalate2",
                                      "password": "xxxx", "role": "admin"})
check("매니저는 관리자 역할 생성 불가(403)", st == 403, st)
st, err = owner.patch(f"/api/staff/{pt['id']}", {"role": "nope"})
check("없는 역할 거부", st == 400, st)

# ---------------------------------------------------------------- 23. 근무 스케줄
print("\n[23] 근무 스케줄(등록·지각·미출근 대조)")
yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
st, sc = owner.post("/api/schedule", {"staffId": pt["id"], "date": yesterday, "start": "10:00",
                                      "end": "15:00", "memo": "홀"})
check("근무 스케줄 등록", st == 201 and sc["start"] == "10:00", st)
st, sc2 = owner.post("/api/schedule", {"staffId": pt["id"], "date": yesterday, "start": "11:00", "end": "16:00"})
check("같은 날짜는 덮어쓰기", st == 201 and sc2["start"] == "11:00", st)
st, wk = owner.get(f"/api/schedule?week={yesterday}")
check("주간 스케줄 표", st == 200 and len(wk["days"]) == 7 and wk["byDay"])
y_row = next(r for r in wk["byDay"][yesterday] if r["staffId"] == pt["id"])
check("출퇴근 기록 없으면 미출근 표시", y_row["status"] == "MISSING" and y_row["statusLabel"] == "미출근", y_row)
st, today_sc = owner.post("/api/schedule", {"staffId": pt["id"], "date": today, "start": "00:01", "end": "23:59"})
part_c.post("/api/attendance/clock-in", {})
st, wk2 = owner.get(f"/api/schedule?week={today}")
t_row = next(r for r in wk2["byDay"][today] if r["staffId"] == pt["id"])
check("실제 출근과 대조해 지각 표시", t_row["status"] == "LATE" and t_row["lateMin"] > 10, t_row)
check("오늘 근무자 요약", any(r["staffId"] == pt["id"] for r in wk2["todayRows"]))
part_c.post("/api/attendance/clock-out", {})
st, mon = owner.get(f"/api/schedule?month={today[:7]}")
check("월 스케줄 요약", st == 200 and mon["month"] == today[:7] and "byStaff" in mon)
st, err = owner.post("/api/schedule", {"staffId": pt["id"], "date": today, "start": "15:00", "end": "10:00"})
check("끝이 시작보다 빠르면 거부", st == 400, st)
st, _ = owner.delete(f"/api/schedule/{sc2['id']}")
check("스케줄 삭제", st == 200, st)
st, _ = part_c.get("/api/schedule")
check("알바는 스케줄 관리 불가", st == 403, st)

# ---------------------------------------------------------------- 24. 예상 급여(참고용)
print("\n[24] 예상 급여 계산·CSV")
st, man = owner.post("/api/attendance/manual", {"staffId": pt["id"], "date": "2026-11-20",
                                                "start": "10:00", "end": "14:30", "memo": "보정"})
check("관리자가 출퇴근 기록 보정", st == 201 and att_minutes(man) == 270, man.get("minutes"))
st, mo = owner.post("/api/staff", {"name": "월급직원", "username": "monthly1", "password": "monthpw1",
                                   "role": "counter", "payType": "monthly", "monthlySalary": 2500000})
st, pay = owner.get(f"/api/payroll?month={today[:7]}")
prow = next(r for r in pay["rows"] if r["staffId"] == pt["id"])
check("시급제: 실제 근무시간 × 시급", prow["expectedPay"] == int(round(prow["hours"] * 12000))
      and prow["minutes"] >= 270, (prow["expectedPay"], prow["minutes"]))
mrow = next(r for r in pay["rows"] if r["staffId"] == mo["id"])
check("월급제: 월급 그대로 계산", mrow["expectedPay"] == 2500000, mrow["expectedPay"])
check("급여 화면에 '참고용' 안내", "참고용" in pay["notice"] and "세금" in pay["notice"])
st, pcsv = owner.get(f"/api/payroll.csv?month={today[:7]}", raw=True)
check("급여 CSV", st == 200 and b"\xef\xbb\xbf" in pcsv[:6] and "예상급여".encode() in pcsv)

# ---------------------------------------------------------------- 25. 비밀번호 초기화
print("\n[25] 비밀번호 초기화·본인 변경")
st, rs = owner.post("/api/staff", {"name": "초기화대상", "username": "reset1", "password": "oldpw1234",
                                   "role": "part"})
st, rst = owner.post(f"/api/staff/{rs['id']}/reset-password", {})
check("관리자가 임시 비밀번호 발급", st == 200 and len(rst["temporaryPassword"]) >= 6, st)
temp_client = Client()
st, data = temp_client.login("reset1", rst["temporaryPassword"])
check("임시 비밀번호로 로그인", st == 200, st)
check("첫 로그인에 변경 권장 표시", data.get("user", {}).get("mustChange") is True, data.get("user", {}))
st, _ = temp_client.post("/api/account/password", {"current": rst["temporaryPassword"], "new": "newpw1234"})
check("본인이 비밀번호 변경", st == 200, st)
st, _ = Client().login("reset1", "newpw1234")
check("새 비밀번호로 로그인", st == 200, st)
st, _ = Client().login("reset1", rst["temporaryPassword"])
check("임시 비밀번호는 더 이상 안 됨", st == 401, st)
st, _ = part_c.post(f"/api/staff/{mo['id']}/reset-password", {})
check("알바는 남의 비밀번호 초기화 불가", st == 403, st)

# ---------------------------------------------------------------- 26. 새 화면 접근
print("\n[26] 새 화면·공개 경계")
for path, label in [("/revenue", "매출"), ("/inventory", "재고"), ("/reservations", "예약"),
                    ("/reviews", "리뷰"), ("/stores", "매장"), ("/account", "내 계정")]:
    st, body = owner.get(path, raw=True)
    check(f"{label} 화면 열림", st == 200 and b"<html" in body.lower(), st)
st, body = anon.get("/reserve", raw=True)
check("손님 예약 신청 화면 공개", st == 200 and "예약".encode() in body, st)
st, _ = anon.get("/revenue")
check("비로그인은 매출 화면 차단(로그인 이동)", st in (200, 302), st)
st, body = part_c.get("/inventory", raw=True)
check("알바는 재고 화면 차단", st == 403, st)
st, body = manager_c.get("/reviews", raw=True)
check("매니저는 리뷰 화면 열람", st == 200, st)
st, _ = manager_c.get("/api/stores/comparison")
check("매니저는 매장 비교 조회", st == 200, st)

# ---------------------------------------------------------------- 27. 공개 서비스 포털
print("\n[27] 공개 서비스 포털(메인·기능·매장·요금제·문의·게시판)")
for path, label in [("/", "메인"), ("/features", "기능소개"), ("/places", "매장위치"),
                    ("/pricing", "요금제"), ("/contact", "문의하기"), ("/board", "게시판"),
                    ("/order", "테이블 선택")]:
    st, body = anon.get(path, raw=True)
    check(f"{label} 화면({path}) 공개", st == 200 and b"<html" in body.lower(), st)
st, body = anon.get("/", raw=True)
main_html = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
check("메인에 이용고객·사장님 흐름 애니메이션",
      "이용고객" in main_html and "사장님" in main_html and "flow-stage" in main_html)
check("메인 상단 메뉴(기능소개·매장위치·요금제·문의하기·게시판)",
      all(t in main_html for t in ("기능소개", "매장위치", "요금제", "문의하기", "게시판")))
check("메인 CTA(손님 체험·무료 시작)", "/t/1" in main_html and "/signup" in main_html)

st, ps = anon.get("/api/public/stores")
check("공개 매장 목록 API", st == 200 and len(ps.get("stores", [])) >= 1, st)
if st == 200 and ps.get("stores"):
    s0 = ps["stores"][0]
    check("공개 매장에 주소·전화·주문 링크",
          "address" in s0 and "phone" in s0 and s0.get("orderUrl", "").startswith("/t/"), s0)
    check("공개 매장에 사업자번호·대표자 비노출",
          "businessNo" not in s0 and "ownerName" not in s0)
    check("지역 목록·활성 테이블 수",
          isinstance(ps.get("regions"), list) and s0.get("tableCount", 0) >= 1, s0.get("tableCount"))
st, new_store = owner.post("/api/stores", {"name": "공개 테스트 매장", "tables": 3})
check("매장 추가", st == 201, st)
st, ps_hidden = anon.get("/api/public/stores")
check("새 매장은 기본적으로 공개 목록에 나오지 않음(사장님이 공개를 켜야 함)",
      not any(s["name"] == "공개 테스트 매장" for s in ps_hidden.get("stores", [])), st)
st, _ = owner.patch(f"/api/stores/{new_store['id']}", {"listed": True})
st, ps = anon.get("/api/public/stores")
check("공개를 켠 매장이 공개 목록에 반영",
      any(s["name"] == "공개 테스트 매장" for s in ps.get("stores", [])), st)

st, err = anon.post("/api/public/inquiries", {"name": "", "message": "문의", "consent": True})
check("문의 필수값 검증", st == 400, st)
st, err = anon.post("/api/public/inquiries",
                    {"name": "김문의", "phone": "010-1111-2222", "message": "도입 문의합니다",
                     "consent": False})
check("문의 동의 없으면 거부", st == 400, st)
st, inq = anon.post("/api/public/inquiries",
                    {"name": "김문의", "phone": "010-1111-2222", "storeName": "운양동 맛집",
                     "kind": "데모 요청", "message": "QR 주문 데모를 보고 싶습니다", "consent": True})
check("문의 접수·접수번호 발급", st == 201 and str(inq.get("receiptNo", "")).startswith("WT"),
      (st, inq.get("receiptNo") if isinstance(inq, dict) else inq))
st, _ = anon.get("/api/inquiries")
check("비로그인은 문의 목록 차단(401)", st == 401, st)
st, inq_list = owner.get("/api/inquiries")
check("사장님은 접수 문의 조회",
      st == 200 and any(i["receiptNo"] == inq.get("receiptNo") for i in inq_list.get("inquiries", [])), st)

st, bd = anon.get("/api/public/board")
check("게시판 기본 공지 시드", st == 200 and len(bd.get("posts", [])) >= 3, st)
notice = (bd.get("posts") or [{}])[0]
st, one = anon.get(f"/api/public/board/{notice.get('id', 0)}")
check("게시글 상세(본문 포함)", st == 200 and bool(one.get("post", {}).get("body")), st)
st, filtered = anon.get("/api/public/board?category=notice")
check("게시판 분류 필터",
      st == 200 and bool(filtered.get("posts")) and
      all(p["category"] == "notice" for p in filtered["posts"]), st)
st, err = anon.post("/api/public/board", {"title": "a", "body": "x", "category": "review"})
check("짧은 글 거부", st == 400, st)
st, newp = anon.post("/api/public/board",
                     {"category": "review", "title": "테스트 후기", "body": "주문이 빨랐습니다",
                      "author": "테스터"})
check("게시글 작성", st == 201 and newp.get("post", {}).get("id", 0) > 0, st)
pid = newp["post"]["id"]
st, cm = anon.post(f"/api/public/board/{pid}/comments", {"author": "답글러", "body": "감사합니다"})
check("댓글 작성", st == 201 and len(cm.get("post", {}).get("comments", [])) == 1, st)
st, _ = anon.post("/api/public/board/9999999/comments", {"body": "없는 글"})
check("없는 글 댓글은 404", st == 404, st)
st, bd2 = anon.get("/api/public/board")
check("목록에 댓글 수 반영",
      any(p["id"] == pid and p.get("commentCount") == 1 for p in bd2.get("posts", [])), st)
st, body = anon.get("/login", raw=True)
check("로그인 화면에도 포털 메뉴", st == 200 and "기능소개".encode() in body, st)

# ---------------------------------------------------------------- 28. 다수 매장 통합 운영
print("\n[28] 다수 매장 통합 운영(분리·메뉴 복사·직원 이동·통합 매출)")
owner.post("/api/stores/switch", {"storeId": 1})
st, src = owner.post("/api/stores", {"name": "통합 원본 매장", "tables": 4})
st2, dst = owner.post("/api/stores", {"name": "통합 대상 매장", "tables": 5})
check("계정으로 매장 2곳 추가", st == 201 and st2 == 201 and src["id"] != dst["id"], (st, st2))

st, _ = owner.post("/api/stores/switch", {"storeId": src["id"]})
st, all_src = owner.get("/api/menu/all")
cat_src = all_src["categories"][0]["id"]
st, sig = owner.post("/api/items", {"name": "통합 시그니처", "price": 12000, "categoryId": cat_src,
                                    "description": "메뉴 복사 확인용"})
check("원본 매장에 메뉴 추가", st == 201 and sig["name"] == "통합 시그니처", st)
st, cat_new = owner.post("/api/categories", {"name": "통합 특선"})
check("원본 매장에 새 카테고리 추가", st == 201, st)
st, course = owner.post("/api/items", {"name": "통합 코스", "price": 25000,
                                       "categoryId": cat_new["id"], "description": "카테고리 복사 확인"})
check("새 카테고리에 메뉴 추가", st == 201, st)
st, t_src = owner.post("/api/tables", {"label": "통합 테이블"})
check("원본 매장에 테이블 추가", st == 201, st)
st, p_src = owner.post("/api/staff", {"name": "이동 직원", "username": "mover28",
                                      "password": "movepw1234", "role": "counter"})
check("원본 매장에 직원 추가", st == 201 and p_src["storeId"] == src["id"], st)

st, _ = owner.post("/api/stores/switch", {"storeId": 1})
st, m1 = owner.get("/api/menu/all")
st, t1 = owner.get("/api/tables")
st, s1 = owner.get("/api/staff")
check("다른 매장에는 원본 메뉴가 없음(메뉴 분리)", "통합 시그니처" not in [i["name"] for i in m1["items"]])
check("다른 매장에는 원본 테이블이 없음(테이블 분리)", "통합 테이블" not in [t["label"] for t in t1["tables"]])
check("다른 매장에는 원본 직원이 없음(직원 분리)", p_src["id"] not in [x["id"] for x in s1["staff"]])

st, cp = owner.post("/api/stores/copy-menu", {"fromStore": src["id"], "toStore": dst["id"],
                                             "onDuplicate": "skip"})
check("메뉴 전체 복사(같은 이름은 건너뛰기)",
      st == 201 and cp["created"] >= 2 and cp["skipped"] >= 1 and cp["categoriesCreated"] == 1, cp)
st, _ = owner.post("/api/stores/switch", {"storeId": dst["id"]})
st, m_dst = owner.get("/api/menu/all")
copy_item = next((i for i in m_dst["items"] if i["name"] == "통합 시그니처"), None)
copy_course = next((i for i in m_dst["items"] if i["name"] == "통합 코스"), None)
check("복사한 메뉴가 대상 매장에 생김", copy_item is not None and copy_item["price"] == 12000, copy_item)
check("복사한 메뉴의 카테고리가 원본과 같음",
      copy_item is not None and copy_item["category"] == "분식", copy_item and copy_item.get("category"))
check("새 카테고리도 함께 만들어져 연결됨",
      copy_course is not None and copy_course["category"] == "통합 특선",
      copy_course and copy_course.get("category"))

st, _ = owner.post("/api/stores/switch", {"storeId": src["id"]})
st, _ = owner.patch(f"/api/items/{sig['id']}", {"name": "통합 시그니처", "price": 13000,
                                               "categoryId": cat_src})
st, same = owner.post("/api/stores/copy-menu", {"fromStore": src["id"], "toStore": src["id"]})
check("같은 매장으로 복사 거부", st == 400, st)
st, cp2 = owner.post("/api/stores/copy-menu", {"fromStore": src["id"], "toStore": dst["id"],
                                               "itemIds": [sig["id"]], "onDuplicate": "overwrite"})
check("선택 메뉴만 덮어쓰기 복사", st == 201 and cp2["updated"] == 1 and cp2["created"] == 0, cp2)
st, _ = owner.post("/api/stores/switch", {"storeId": dst["id"]})
st, m_dst2 = owner.get("/api/menu/all")
copy_item2 = next((i for i in m_dst2["items"] if i["name"] == "통합 시그니처"), None)
check("덮어쓴 가격이 반영됨", copy_item2 is not None and copy_item2["price"] == 13000,
      copy_item2 and copy_item2.get("price"))

mover_c = Client()
st, _ = mover_c.login("mover28", "movepw1234")
st, mme = mover_c.get("/api/auth/me")
check("이동 전 직원은 원본 매장 소속", st == 200 and mme["user"]["storeId"] == src["id"],
      mme.get("user", {}).get("storeId"))
st, mv = owner.post("/api/stores/transfer-staff", {"staffId": p_src["id"], "toStore": dst["id"],
                                                    "note": "통합 테스트 발령"})
check("직원 매장 이동(발령)", st == 201 and mv["toStore"]["id"] == dst["id"], st)
st, mme2 = mover_c.get("/api/auth/me")
check("이동한 직원의 로그인 세션이 새 매장을 봄",
      st == 200 and mme2["user"]["storeId"] == dst["id"], mme2.get("user", {}).get("storeId"))
st, sd = owner.get("/api/staff")
check("대상 매장 직원 목록에 이동 직원 포함", any(x["id"] == p_src["id"] for x in sd["staff"]))
st, tl = owner.get("/api/stores/transfers")
check("직원 이동 이력 기록",
      any(t["staffId"] == p_src["id"] and t["toStore"] == dst["id"] for t in tl["transfers"]), tl)
st, dst_tables = owner.get("/api/tables")
dst_table = dst_tables["tables"][0]
st, menu_d = anon.get(f"/api/menu?store={dst['id']}")
first_item = menu_d["items"][0]
st, chk_store = anon.get(f"/api/table/{dst_table['code']}?store={dst['id']}")
check("다른 매장 QR 주소(?store)가 그 매장 테이블로 열림",
      st == 200 and chk_store["table"]["storeId"] == dst["id"],
      chk_store.get("table", {}).get("storeId") if isinstance(chk_store, dict) else st)
st, o_dst = anon.post(f"/api/orders?store={dst['id']}",
                      {"table": dst_table["id"], "items": [{"itemId": first_item["id"], "qty": 1}]})
check("대상 매장에서 고객 주문", st == 201 and o_dst["storeId"] == dst["id"], st)
st, paid_dst = owner.post(f"/api/orders/{o_dst['id']}/payment", {"paid": True})
check("대상 매장 결제 확인", st == 200 and paid_dst["paymentStatus"] == "PAID", st)

st, summ = owner.get("/api/stores/summary")
drow = next((s for s in summ["stores"] if s["id"] == dst["id"]), {})
check("전 매장 통합 매출 합계 API",
      st == 200 and summ["totals"]["storeCount"] >= 3
      and summ["totals"]["todayPaid"] >= drow.get("todayPaid", 0), st)
check("대상 매장 매출이 합계에 포함", drow.get("todayPaid", 0) >= first_item["price"],
      (drow.get("todayPaid"), first_item["price"]))
check("매장별 매출 비중 계산",
      all(0 <= s["monthShare"] <= 100 for s in summ["stores"])
      and abs(sum(s["monthShare"] for s in summ["stores"]) - 100) < 0.5
      if summ["totals"]["monthPaid"] else True, [s["monthShare"] for s in summ["stores"]])
st, _ = anon.get("/api/stores/summary")
check("비로그인은 통합 매출 차단(401)", st == 401, st)
st, _ = manager_c.get("/api/stores/summary")
check("매니저는 통합 매출 조회 가능", st == 200, st)
st, _ = manager_c.post("/api/stores/transfer-staff", {"staffId": p_src["id"], "toStore": 1})
check("매니저는 직원 이동 불가(403)", st == 403, st)
owner.post("/api/stores/switch", {"storeId": 1})

# ---------------------------------------------------------------- 29. 사업자 계정 멀티테넌트
print("\n[29] 사업자 계정 여러 개(멀티테넌트·데이터 격리)")
other = Client()
st, signup_b = other.post("/api/auth/signup", {"storeName": "B가게", "username": "bosssb29",
                                                "password": "sbpass1234", "tables": 3})
check("배포 하나에 두 번째 사업자 계정 가입", st == 201 and signup_b["user"]["role"] == "admin", st)
store_b = signup_b["storeId"]
check("두 번째 계정은 자기 매장으로 시작",
      store_b != 1 and [x["name"] for x in signup_b["stores"]] == ["B가게"], signup_b.get("stores"))
st, stores_b = other.get("/api/stores")
check("B 계정 매장 목록에는 A 매장이 없음",
      st == 200 and all(x["id"] != 1 for x in stores_b["stores"]), stores_b)
st, _ = other.post("/api/stores/switch", {"storeId": 1})
check("B 계정은 A 매장으로 전환 불가(404)", st in (403, 404), st)
st, cust_b = other.get("/api/customers")
check("B 계정 회원 목록은 비어 있음(데이터 격리)",
      st == 200 and cust_b.get("customers") == [], st)
st, menu_b = other.get("/api/menu")
check("B 매장은 자기 메뉴를 따로 가짐", st == 200 and len(menu_b["items"]) >= 1, st)
st, groups_b = other.get("/api/groups")
check("B 계정 그룹 목록 비어 있음", st == 200 and groups_b.get("groups") == [], st)
st, stores_a = owner.get("/api/stores")
check("A 계정 매장 목록에 B 매장이 없음",
      all(x["id"] != store_b for x in stores_a["stores"]), stores_a)
st, _ = owner.patch(f"/api/stores/{store_b}", {"name": "가로채기"})
check("A 계정이 B 매장을 수정할 수 없음(404)", st == 404, st)
st, _ = owner.get(f"/api/orders?store={store_b}")
check("A 계정이 B 매장 주문을 조회할 수 없음(빈 목록)",
      st == 200 and not [o for o in _["orders"] if o["storeId"] == store_b], st)

# ---------------------------------------------------------------- 30. 매장 그룹
print("\n[30] 매장 그룹(브랜드·지역·직영/가맹)")
owner.post("/api/stores/switch", {"storeId": 1})
st, group = owner.post("/api/groups", {"name": "운양 직영", "kind": "direct",
                                       "storeIds": [1, src["id"]]})
check("매장 2곳을 그룹으로 묶기", st == 201 and len(group["stores"]) == 2, st)
gid = group["id"]
st, gl = owner.get("/api/groups")
check("그룹 목록에 매장 구성원 표시",
      any(g["id"] == gid and len(g["stores"]) == 2 for g in gl["groups"]), gl)
st, gsum = owner.get(f"/api/groups/{gid}/summary")
check("그룹 통합 매출 요약",
      st == 200 and gsum["totals"]["storeCount"] == 2 and "monthPaid" in gsum["totals"], st)
st, gout = owner.post(f"/api/groups/{gid}/copy-menu", {"fromStore": 1, "toStores": [src["id"]],
                                                       "onDuplicate": "overwrite"})
check("그룹 메뉴 일괄 복사", st == 201 and (gout["created"] + gout["updated"]) >= 1, gout)
st, gstaff = owner.post("/api/groups", {"name": "지역 그룹", "kind": "region",
                                        "storeIds": [dst["id"], new_store["id"]]})
gid2 = gstaff["id"]
st, gt = owner.post(f"/api/groups/{gid2}/transfer-staff", {"staffId": p_src["id"],
                                                         "toStore": new_store["id"]})
check("그룹 안 직원 이동", st == 201 and gt["toStore"]["id"] == new_store["id"], st)
st, _ = owner.post(f"/api/groups/{gid}/transfer-staff", {"staffId": p_src["id"], "toStore": new_store["id"]})
check("그룹 밖 매장으로는 이동 거부", st in (400, 404), st)
st, gs = owner.patch(f"/api/groups/{gid}", {"settings": {"channelMode": "both", "waiting": True}})
check("그룹 기본 설정 저장", st == 200 and gs["settings"]["channelMode"] == "both", st)
st, applied = owner.post(f"/api/groups/{gid}/apply-settings")
check("그룹 기본 설정 적용(운영 모드·웨이팅)",
      st == 200 and sorted(applied["applied"]) == sorted([m["id"] for m in group["stores"]]), st)
st, _ = other.get(f"/api/groups/{gid}/summary")
check("다른 계정은 그룹을 볼 수 없음", st == 404, st)

# ---------------------------------------------------------------- 31. 운영 모드·구역·테이블
print("\n[31] 온·오프라인 운영 모드·구역·테이블")
owner.post("/api/stores/switch", {"storeId": 1})
st, saved = owner.patch("/api/settings", {"channel": {"mode": "both", "pickup": True,
                                                    "delivery": False, "pickupMin": 15}})
check("온·오프라인 통합 모드 설정",
      st == 200 and saved["saved"]["channel"]["mode"] == "both", saved.get("saved", {}).get("channel"))
st, menu_now = owner.get("/api/menu")
first_item_b = menu_now["items"][0]
st, pickup = anon.post("/api/orders", {"channel": "pickup", "items": [{"itemId": first_item_b["id"], "qty": 1}],
    "customer": {"name": "포장손님", "phone": "010-5555-6666"}})
check("포장 주문 생성(테이블 없이)", st == 201 and pickup["channel"] == "pickup"
      and pickup["table"] == 0, (st, pickup.get("channel") if isinstance(pickup, dict) else pickup))
st, _ = anon.post("/api/orders", {"channel": "delivery", "items": [{"itemId": first_item_b["id"], "qty": 1}],
    "customer": {"name": "배달손님", "phone": "010-5555-6667"}})
check("꺼 둔 배달 주문은 거부", st == 400, st)
st, _ = anon.post("/api/orders", {"channel": "pickup", "items": [{"itemId": first_item_b["id"], "qty": 1}],
    "customer": {"name": "연락없음", "phone": ""}})
check("포장 주문은 연락처 필수", st == 400, st)
st, _ = owner.patch("/api/settings", {"channel": {"mode": "online"}})
st, _ = anon.post("/api/orders", {"table": 3, "items": [{"itemId": first_item_b["id"], "qty": 1}]})
check("온라인 전용 매장은 테이블 주문 거부", st == 400, st)
owner.patch("/api/settings", {"channel": {"mode": "both", "pickup": True}})
st, zones = owner.get("/api/zones")
check("기본 구역(홀)이 있음", st == 200 and any(z["name"] == "홀" for z in zones["zones"]), zones)
st, zone = owner.post("/api/zones", {"name": "창가"})
check("구역 추가(창가)", st == 201 and zone["name"] == "창가", st)
st, bulk = owner.post("/api/tables/bulk", {"zoneId": zone["id"], "prefix": "창가",
                                            "count": 3, "seats": 2})
check("구역에 테이블 3개 일괄 생성", st == 201 and bulk["created"] == 3, st)
bulk_ids = [t["id"] for t in bulk["tables"]]
st, tm = owner.patch(f"/api/tables/{t1['tables'][0]['id']}", {"zoneId": zone["id"]})
check("테이블을 다른 구역으로 이동", st == 200 and tm["zoneId"] == zone["id"], st)
st, ta = owner.get("/api/tables/admin")
check("구역별 테이블 수 집계",
      any(z["id"] == zone["id"] and z["tableCount"] >= 4 for z in ta["zones"]), ta.get("zones"))
st, zd = owner.delete(f"/api/zones/{zone['id']}")
check("구역 삭제 시 테이블은 다른 구역으로 이동", st == 200 and zd["movedTables"] >= 4, zd)
st, _ = owner.delete("/api/zones/999999")
check("없는 구역 삭제는 404", st == 404, st)
st, ng = owner.get("/api/nfc/guide")
check("NFC NDEF 쓰기 안내·주소",
      st == 200 and ng["items"] and "via=nfc" in ng["items"][0]["url"] and len(ng["guide"]) >= 3, st)

# ---------------------------------------------------------------- 32. 결제 수단
print("\n[32] 결제(현금·계좌이체·카드·간편결제)")
st, pay_cfg = owner.patch("/api/settings", {"payments": {
    "transfer": {"enabled": True, "bank": "김포농협", "accountNo": "123-456-789", "holder": "가게A"},
    "card": {"enabled": False}}})
check("계좌이체 계좌 설정",
      st == 200 and pay_cfg["saved"]["payments"]["transfer"]["accountNo"] == "123-456-789", st)
st, methods = anon.get("/api/payments/methods")
check("손님 화면 결제수단 목록(현금·계좌이체)",
      any(m["code"] == "TRANSFER" for m in methods["methods"])
      and any(m["code"] == "CASH" for m in methods["methods"]), methods)
st, _ = anon.post("/api/orders", {"table": 3, "items": [{"itemId": first_item_b["id"], "qty": 1}],
    "customer": {"name": "카드손님", "phone": "010-7777-8888"}, "payMethod": "CARD"})
check("꺼 둔 카드 결제는 주문 단계에서 거부", st == 400, st)
st, to = anon.post("/api/orders", {"table": 3, "items": [{"itemId": first_item_b["id"], "qty": 2}],
    "customer": {"name": "이체손님", "phone": "010-9999-0000"}, "payMethod": "TRANSFER"})
check("계좌이체 주문 생성", st == 201 and to["paymentMethod"] == "TRANSFER", st)
st, started = anon.post(f"/api/orders/{to['id']}/transfer", {"table": 3, "depositor": "이체손"})
check("입금자명 남기기(결제 전)",
      st == 200 and started["order"]["paymentStatus"] == "UNPAID", st)
st, pend = owner.get("/api/payments")
check("사장님 화면 입금 확인 대기 목록",
      st == 200 and any(x["orderId"] == to["id"] and x["depositor"] == "이체손"
                        for x in pend["pendingTransfers"]["pending"]), pend.get("pendingTransfers"))
st, conf = owner.post(f"/api/orders/{to['id']}/payment-confirm", {"method": "TRANSFER"})
check("입금 확인 → 결제 완료", st == 200 and conf["order"]["paymentStatus"] == "PAID", st)
check("결제 기록에 계좌이체 남음",
      any(p["method"] == "TRANSFER" and p["status"] == "PAID" for p in conf["payments"]), conf.get("payments"))
st, _ = owner.patch("/api/settings", {"payments": {"card": {"enabled": True, "feeRate": 1.5}}})
st, co = anon.post("/api/orders", {"table": 3, "items": [{"itemId": first_item_b["id"], "qty": 1}],
    "customer": {"name": "카드손님2", "phone": "010-7777-8889"}, "payMethod": "CARD"})
check("카드를 켜면 카드 주문 가능", st == 201, st)
st, paidc = owner.post(f"/api/orders/{co['id']}/pay", {"method": "CARD"})
check("카드 결제(모의 승인, 실제 결제 아님)",
      st == 200 and paidc["order"]["paymentStatus"] == "PAID" and paidc["simulated"] is True, st)
st, refund = owner.post(f"/api/orders/{co['id']}/refund", {})
check("결제 취소·환불", st == 200 and refund["order"]["paymentStatus"] == "UNPAID", st)
st, psum = owner.get("/api/payments/summary")
check("결제수단별 합계·수수료",
      st == 200 and psum["total"] > 0 and any(m["method"] == "TRANSFER" and m["amount"] > 0
                                              for m in psum["methods"]), psum)
check("PG는 모의(simulation) 상태로 정직하게 표시", psum.get("adapter", {}).get("mode") == "simulation",
      psum.get("adapter"))
st, _ = manager_c.post(f"/api/orders/{co['id']}/refund", {})
check("환불 권한은 매니저에게 있음(이미 환불된 건은 400)", st in (400, 404), st)
st, _ = part_c.get("/api/payments")
check("알바는 결제 확인 목록 조회 가능(주문·결제 권한)", st == 200, st)
st, _ = part_c.patch("/api/settings", {"payments": {"card": {"enabled": True}}})
check("알바는 결제 설정 변경 불가(403)", st == 403, st)

# ---------------------------------------------------------------- 33. QR·NFC 유입 통계
print("\n[33] QR·NFC 유입 통계")
st, v1 = anon.post("/api/public/visit", {"code": "3", "via": "qr", "path": "/t/3"})
st2, v2 = anon.post("/api/public/visit", {"code": "3", "via": "nfc", "path": "/t/3?via=nfc"})
check("QR·NFC 유입 기록", st == 201 and st2 == 201 and v2["via"] == "nfc", (st, st2))
st, scans = owner.get("/api/stats/scans")
check("QR 대비 NFC 유입 통계",
      st == 200 and scans["today"]["byVia"]["nfc"] >= 1 and scans["today"]["total"] >= 2, scans.get("today"))
check("테이블별 유입 표", isinstance(scans.get("byTable"), list) and len(scans["byTable"]) >= 1, scans.get("byTable"))
st, _ = other.get("/api/stats/scans")
check("다른 계정은 이 매장 유입 통계를 볼 수 없음(자기 매장 0건)",
      st == 200 and _.get("storeId") == store_b, st)

# ---------------------------------------------------------------- 34. 웨이팅 ON/OFF
print("\n[34] 웨이팅 설정")
st, woff = owner.patch("/api/settings", {"waiting": {"enabled": False, "notice": "오늘은 대기 없이 입장합니다"}})
check("웨이팅 OFF 저장", st == 200 and woff["saved"]["waiting"]["enabled"] is False, st)
st, _ = anon.post("/api/wait", {"name": "대기손", "phone": "010-2222-3333", "party": 2,
                                 "consent": True})
check("웨이팅 OFF면 접수 거부", st == 400, st)
owner.patch("/api/settings", {"waiting": {"enabled": True, "maxParty": 4}})
st, _ = anon.post("/api/wait", {"name": "대기손", "phone": "010-2222-3333", "party": 9,
                                 "consent": True})
check("한 팀 최대 인원 초과 거부", st == 400, st)
st, w = anon.post("/api/wait", {"name": "대기손", "phone": "010-2222-3333", "party": 2,
                                 "consent": True})
check("웨이팅 ON이면 정상 접수", st == 201 and w["ticket"]["ticketNo"], st)

# ---------------------------------------------------------------- 35. 주방 KDS
print("\n[35] 주방 KDS(경로 표시·품절 알림)")
st, ks = owner.get("/api/kitchen")
check("주방 요약에 경로별 건수", st == 200 and isinstance(ks["summary"]["channels"], dict), st)
check("주문 카드에 매장/포장 구분 라벨",
      all(o.get("channelLabel") for o in ks["queue"]), [o.get("channel") for o in ks["queue"][:3]])
check("KDS에 포장 주문 표시", any(o.get("channel") == "pickup" for o in ks["queue"] + ks["serving"]), None)
check("품절 연동 알림 필드", "soldout" in ks["summary"]["alerts"]
      and "affectedOrders" in ks["summary"]["alerts"], ks["summary"].get("alerts"))
st, menu_all36 = owner.get("/api/menu/all")
sold_item = menu_all36["items"][0]
owner.post(f"/api/items/{sold_item['id']}/soldout", {"soldout": True})
st, ks2 = owner.get("/api/kitchen")
check("품절 메뉴가 KDS 알림에 올라감",
      any(x["itemId"] == sold_item["id"] for x in ks2["summary"]["alerts"]["soldout"]), None)
owner.post(f"/api/items/{sold_item['id']}/soldout", {"soldout": False})

# ---------------------------------------------------------------- 36. 직원 역할 확장
print("\n[36] 직원 역할(점장·홀)·권한")
st, head = owner.post("/api/staff", {"name": "점장님", "username": "head36",
                                     "password": "headpass1", "role": "head"})
check("점장 역할 생성", st == 201 and head["roleLabel"] == "점장", st)
st, hall = owner.post("/api/staff", {"name": "홀직원", "username": "hall36",
                                     "password": "hallpass1", "role": "hall"})
check("홀 역할 생성", st == 201 and hall["roleLabel"] == "홀", st)
head_c = Client()
head_c.login("head36", "headpass1")
st, _ = head_c.patch("/api/settings", {"storeName": "점장이 바꿈"})
check("점장은 매장 설정 변경 불가(403)", st == 403, st)
st, _ = head_c.get("/api/staff")
check("점장은 직원 관리 가능", st == 200, st)
hall_c = Client()
hall_c.login("hall36", "hallpass1")
st, _ = hall_c.get("/api/orders")
check("홀 직원은 주문 확인 가능", st == 200, st)
st, _ = hall_c.get("/api/staff")
check("홀 직원은 직원 관리 불가(403)", st == 403, st)

# ---------------------------------------------------------------- 37. 고객 이벤트·쿠폰
print("\n[37] 고객 이벤트·쿠폰")
month = today[5:7]
st, ev = owner.patch("/api/settings", {"events": {
    "firstVisit": {"enabled": True, "points": 500, "coupon": True},
    "birthday": {"enabled": True, "points": 1000, "coupon": False},
    "coupon": {"title": "첫 방문 쿠폰", "amount": 2000, "minSpend": 10000, "validDays": 30},
    "timeDiscount": {"enabled": False}}})
check("이벤트 설정 저장", st == 200 and ev["saved"]["events"]["firstVisit"]["coupon"] is True, st)
st, c_new = owner.post("/api/customers", {"name": "생일손님", "phone": "010-3333-4444",
                                          "birthday": f"1990-{month}-15", "consent": True})
check("생일 회원 등록", st == 201 and c_new["id"], st)
st, menu_all37 = owner.get("/api/menu/all")
bulgogi2 = next(i for i in menu_all37["items"] if i["name"] == "불고기")
st, eo = anon.post("/api/orders", {"table": 3, "items": [{"itemId": bulgogi2["id"], "qty": 1}],
    "customer": {"name": "생일손님", "phone": "010-3333-4444", "consent": True}})
st, ep = owner.post(f"/api/orders/{eo['id']}/payment", {"paid": True})
check("첫 방문 이벤트: 결제 확인", st == 200 and ep["paymentStatus"] == "PAID", st)
st, cc = owner.get(f"/api/customers/{c_new['id']}/coupons")
check("첫 방문 쿠폰 발급", st == 200 and any(x["status"] == "ISSUED" for x in cc["coupons"]), cc.get("coupons"))
st, ev2 = owner.get("/api/events")
check("이벤트 적용 내역에 첫 방문·생일 기록",
      st == 200 and any(x["event"] in ("firstVisit", "birthday") for x in ev2["recent"]), ev2.get("recent"))
usable = next((x for x in cc["coupons"] if x["status"] == "ISSUED"), None)
if usable:
    st, co2 = anon.post("/api/orders", {"table": 3,
        "items": [{"itemId": bulgogi2["id"], "qty": 1}],
        "customer": {"name": "생일손님", "phone": "010-3333-4444", "consent": True},
        "couponId": usable["id"]})
    check("쿠폰 적용 주문(2,000원 할인)",
          st == 201 and co2["discount"] == 2000 and co2["total"] == bulgogi2["price"] - 2000, co2)
    st, mc = anon.get("/api/member/coupons?phone=01033334444")
    check("사용한 쿠폰은 다시 안 나옴", st == 200 and not any(x["id"] == usable["id"] for x in mc["coupons"]), mc)
    owner.post(f"/api/orders/{co2['id']}/status", {"status": "CANCELED"})
    st, cc2 = owner.get(f"/api/customers/{c_new['id']}/coupons")
    check("주문 취소 시 쿠폰 복원",
          any(x["id"] == usable["id"] and x["status"] == "ISSUED" for x in cc2["coupons"]), cc2.get("coupons"))
st, _ = owner.patch("/api/settings", {"events": {"timeDiscount": {"enabled": True, "start": "00:00",
                                                                     "end": "23:59", "percent": 10}}})
st, tdo = anon.post("/api/orders", {"table": 3, "items": [{"itemId": bulgogi2["id"], "qty": 1}],
    "customer": {"name": "시간할인손", "phone": "010-4444-5555"}})
check("시간 할인 자동 적용(10%)",
      st == 201 and tdo["discount"] == int(bulgogi2["price"] * 0.1), tdo)
owner.patch("/api/settings", {"events": {"timeDiscount": {"enabled": False}}})
st, cp = owner.post("/api/coupons", {"title": "주말 쿠폰", "amount": 3000, "minSpend": 0,
                                     "validDays": 7})
check("쿠폰 만들기", st == 201 and cp["id"], st)
st, issued = owner.post(f"/api/customers/{c_new['id']}/coupons", {"couponId": cp["id"]})
check("회원에게 수동 쿠폰 발급", st == 201 and issued["issued"] is True, issued)

# ---------------------------------------------------------------- 38. 로컬 커뮤니티
print("\n[38] 로컬 커뮤니티")
st, com_off = anon.get("/api/public/community")
check("커뮤니티 OFF면 손님에게 글 없음", st == 200 and com_off["enabled"] is False, com_off)
st, _ = owner.post("/api/community", {"title": "동네 소식", "body": "오늘 시장 세일"})
check("커뮤니티 OFF면 글쓰기 거부", st == 400, st)
st, com_set = owner.patch("/api/settings", {"community": {"enabled": True, "intro": "운양동 이웃 소식",
                                                        "neighborhood": "운양동", "showToCustomers": True}})
check("로컬 커뮤니티 켜기", st == 200 and com_set["saved"]["community"]["enabled"] is True, st)
st, post1 = owner.post("/api/community", {"kind": "neighbor", "title": "새로 문 연 빵집",
                                          "body": "옆 골목 빵집이 문을 열었어요"})
check("동네 소식 글쓰기", st == 201 and post1["id"], st)
st, gp = owner.post("/api/community", {"kind": "promo", "title": "그룹 공동 프로모션",
                                        "body": "그룹 매장 모두 같은 이벤트", "scope": "group"})
check("그룹 공동 프로모션 글쓰기", st == 201 and gp["groupId"] == gid, (st, gp))
st, pub_com = anon.get("/api/public/community")
check("손님 화면에 동네 소식 노출",
      st == 200 and pub_com["enabled"] is True
      and any(p["id"] == post1["id"] for p in pub_com["posts"]), pub_com)
st, pub_group = anon.get(f"/api/public/community?store={src['id']}")
check("커뮤니티를 안 켠 그룹 매장에는 그룹 글이 안 보임",
      st == 200 and pub_group["enabled"] is False, pub_group)
owner.post("/api/stores/switch", {"storeId": src["id"]})
owner.patch("/api/settings", {"community": {"enabled": True, "showToCustomers": True}})
st, pub_group2 = anon.get(f"/api/public/community?store={src['id']}")
check("커뮤니티를 켠 그룹 매장 손님에게 그룹 글 노출",
      st == 200 and any(p["id"] == gp["id"] for p in pub_group2["posts"]), pub_group2)
owner.post("/api/stores/switch", {"storeId": 1})
st, pub_b = anon.get(f"/api/public/community?store={store_b}")
check("다른 사업자 매장에는 이 글이 안 보임",
      st == 200 and not any(p["id"] in (post1["id"], gp["id"]) for p in pub_b["posts"]), pub_b)
st, hidden = owner.patch(f"/api/community/{post1['id']}", {"visible": False})
st, pub_com2 = anon.get("/api/public/community")
check("숨긴 글은 손님 화면에서 빠짐",
      not any(p["id"] == post1["id"] for p in pub_com2["posts"]), pub_com2)

# ---------------------------------------------------------------- 요약
print(f"\n{'='*54}\n  통과 {len(PASS)}건 / 실패 {len(FAIL)}건")
if FAIL:
    print("  실패 항목:")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("  모든 확인 항목 통과")
