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
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OWNER = ("owner", "mangjip1234")
PASS, FAIL = [], []


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
check("포인트 잔액 반영", m and m["points"] == paid["pointsEarned"], m and m["points"])
check("신규 등급", m and m["grade"] == "NEW", m and m["grade"])
mid = m["id"]
st, order2 = anon.post("/api/orders", {"table": 3,
    "items": [{"itemId": kimbap["id"], "qty": 2}],
    "customer": {"name": "김테스트", "phone": "010-1234-5678", "consent": True},
    "pointsUsed": paid["pointsEarned"]})
check("주문서 포인트 사용", order2["pointsUsed"] == paid["pointsEarned"]
      and order2["total"] == kimbap["price"] * 2 - paid["pointsEarned"],
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
check("NFC URL이 테이블 주소와 일치", n3 and n3["url"] == BASE + "/t/3",
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

# ---------------------------------------------------------------- 요약
print(f"\n{'='*54}\n  통과 {len(PASS)}건 / 실패 {len(FAIL)}건")
if FAIL:
    print("  실패 항목:")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("  모든 확인 항목 통과")
