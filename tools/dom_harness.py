#!/usr/bin/env python3
"""화면 JS 를 실제 데이터로 실행해 보는 점검 도구 (개발용).

브라우저가 없는 환경이라, 작은 DOM 흉내를 quickjs 로 만들어 각 화면의 초기 렌더링을
실제 서버 응답으로 돌린다. 흰 화면이 되는 런타임 오류나 'undefined'/'NaN' 표시를 잡는다.
권한이 필요한 화면은 로그인 쿠키를 붙여 실제 응답을 받아 쓴다.

    python3 server.py --port 8040 &
    MENU_TEST_USER=owner MENU_TEST_PW=mangjip1234 python3 tools/dom_harness.py http://127.0.0.1:8040
"""
import json
import os
import sys
import urllib.error
import urllib.request
import http.cookiejar

import quickjs

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USER = os.environ.get("MENU_TEST_USER", "owner")
PW = os.environ.get("MENU_TEST_PW", "mangjip1234")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "public", "assets")

PRELUDE = r"""
const __els = {};
function __mk(id) {
  const cls = new Set();
  return {
    id, _html: "", textContent: "", value: "", checked: false, disabled: false,
    dataset: {}, style: {}, files: [], options: [], classList: {
      add(...c) { c.forEach((x) => cls.add(x)); },
      remove(...c) { c.forEach((x) => cls.delete(x)); },
      toggle(c, f) { const on = f === undefined ? !cls.has(c) : !!f; on ? cls.add(c) : cls.delete(c); return on; },
      contains(c) { return cls.has(c); },
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, append() {},
    remove() {}, focus() {}, select() {}, click() {}, animate() {}, scrollIntoView() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, setAttribute() {}, getAttribute() { return null; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
    toDataURL() { return ""; },
  };
}
globalThis.document = {
  getElementById(id) { return __els[id] || (__els[id] = __mk(id)); },
  querySelector(sel) {
    const id = String(sel).startsWith("#") ? String(sel).slice(1) : String(sel);
    return __els[id] || (__els[id] = __mk(id));
  },
  querySelectorAll() { return []; },
  createElement(tag) { return __mk("el:" + tag); },
  addEventListener() {},
  head: { appendChild() {} },
  body: { appendChild() {}, animate() {}, classList: __mk("body").classList, dataset: {} },
  visibilityState: "visible",
  title: "",
};
globalThis.window = {
  addEventListener() {}, scrollTo() {}, print() {}, open() { return null; },
  matchMedia() { return { matches: false, addEventListener() {} }; },
  isSecureContext: true, speechSynthesis: undefined,
};
globalThis.location = {
  pathname: "/t/3", origin: "http://127.0.0.1:8080", hostname: "127.0.0.1",
  port: "8080", search: "", hash: "", protocol: "http:", reload() {}, href: "",
};
globalThis.navigator = {
  permissions: { query() { return Promise.resolve({ state: "prompt", onchange: null }); } },
  clipboard: { writeText() { return Promise.resolve(); } },
  serviceWorker: { register() { return Promise.resolve({}); }, ready: Promise.resolve({ showNotification() { return Promise.resolve(); } }) },
};
globalThis.Notification = function () {};
Notification.permission = "default";
Notification.requestPermission = () => Promise.resolve("granted");
globalThis.localStorage = {
  _d: {}, getItem(k) { return this._d[k] === undefined ? null : this._d[k]; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
globalThis.URLSearchParams = class {
  constructor(s) {
    this._m = new Map();
    String(s || "").replace(/^\?/, "").split("&").filter(Boolean).forEach((kv) => {
      const i = kv.indexOf("=");
      const k = i < 0 ? kv : kv.slice(0, i);
      const v = i < 0 ? "" : kv.slice(i + 1);
      this._m.set(decodeURIComponent(k), decodeURIComponent(v));
    });
  }
  get(k) { const kk = String(k); return this._m.has(kk) ? this._m.get(kk) : null; }
  set(k, v) { this._m.set(String(k), String(v)); }
  append(k, v) { this._m.set(String(k), String(v)); }
  delete(k) { this._m.delete(String(k)); }
  has(k) { return this._m.has(String(k)); }
  toString() {
    return Array.from(this._m.entries())
      .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
  }
};
Number.prototype.toLocaleString = function () {
  const s = String(this);
  const [i, f] = s.split(".");
  return i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (f ? "." + f : "");
};
globalThis.requestAnimationFrame = () => 0;
globalThis.setTimeout = () => 0;
globalThis.setInterval = () => 0;
globalThis.clearTimeout = () => 0;
globalThis.clearInterval = () => 0;
globalThis.confirm = () => true;
globalThis.prompt = () => "";
globalThis.alert = () => {};
globalThis.URL = { createObjectURL: () => "", revokeObjectURL() {} };
globalThis.Blob = function () {};
globalThis.Image = function () { this.onload = null; this.onerror = null; };
globalThis.AudioContext = function () { return {}; };
globalThis.__DATA = __DATA_JSON__;
globalThis.fetch = (path, opts) => {
  const key = String(path).split("?")[0];
  const body = __DATA[key];
  if (body === undefined) return Promise.reject(new Error("stub 없음: " + path));
  return Promise.resolve({
    ok: true, status: 200,
    headers: { get: () => "application/json; charset=utf-8" },
    json: () => Promise.resolve(JSON.parse(JSON.stringify(body))),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
};
"""


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=40) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw.decode() or "{}")
                except ValueError:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw.decode())
            except ValueError:
                return e.code, raw

    def get(self, path):
        return self.call("GET", path)[1]

    def post(self, path, body=None):
        return self.call("POST", path, body or {})


def login():
    st, data = client.call("POST", "/api/auth/login", {"username": USER, "password": PW})
    if st != 200:
        raise SystemExit(f"로그인 실패({st}): 서버와 계정({USER})을 확인해 주세요")


def run(page_js, data, checks, path="/t/3", extra_setup=""):
    ctx = quickjs.Context()
    prelude = PRELUDE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    ctx.eval(prelude.replace('pathname: "/t/3"', f'pathname: "{path}"') + extra_setup)
    for name in ("util.js", "nav.js", page_js):
        file_path = os.path.join(ASSETS, name)
        if not os.path.exists(file_path):
            continue
        ctx.eval(open(file_path, encoding="utf-8").read())
    for _ in range(6):
        while ctx.execute_pending_job():
            pass
    ok = True
    for el_id, needles, banned in checks:
        html = ctx.eval(f"__els[{json.dumps(el_id)}] ? __els[{json.dumps(el_id)}]._html : ''") or ""
        text = ctx.eval(f"__els[{json.dumps(el_id)}] ? (__els[{json.dumps(el_id)}].textContent || '') : ''") or ""
        html = html + " " + text
        for needle in needles:
            if needle not in html:
                print(f"  ❌ #{el_id} 에 '{needle}' 가 없습니다")
                ok = False
        for bad in banned + ["undefined", "NaN", "[object Object]"]:
            if bad and bad in html:
                print(f"  ❌ #{el_id} 에 '{bad}' 가 찍혔습니다")
                ok = False
    return ok


def main():
    login()
    me = client.get("/api/auth/me")
    menu = client.get("/api/menu")
    menu_all = client.get("/api/menu/all")
    state = client.get("/api/state")
    kitchen = client.get("/api/kitchen")
    members = client.get("/api/customers")
    qr_cfg = client.get("/api/qr/config")
    staff = client.get("/api/staff")
    tables_admin = client.get("/api/tables/admin")
    settings_data = client.get("/api/settings")
    wait_admin = client.get("/api/wait/admin")
    board = client.get("/api/wait/board")
    table = client.get("/api/table/3")
    recommend = client.get("/api/recommend?table=3")
    calls = client.get("/api/calls?table=3")
    order_id = state["orders"][0]["id"] if state["orders"] else 0
    revenue = client.get("/api/revenue?preset=today")
    inventory_data = client.get("/api/inventory")
    reservations = client.get("/api/reservations")
    reviews_data = client.get("/api/reviews")
    stores_data = client.get("/api/stores")
    comparison = client.get("/api/stores/comparison")
    store_summary = client.get("/api/stores/summary")
    store_staff = client.get("/api/stores/staff")
    store_transfers = client.get("/api/stores/transfers")
    sessions = client.get("/api/account/sessions")
    staff_meta = client.get("/api/staff/permissions")
    schedule = client.get("/api/schedule")

    results = []

    results.append(("고객 메뉴", run("customer.js", {
        "/api/menu": menu, "/api/table/3": table, "/api/recommend": recommend,
        "/api/orders": {"orders": state["orders"][:3]}, "/api/calls": calls,
        "/api/auth/me": me,
        f"/api/orders/{order_id}": state["orders"][0] if order_id else {},
    }, [("menuList", ["mcard", "김밥", "3,500", "/images/kimbap.jpg", "원산지"], []),
        ("tabs", ["분식", "한식", "사이드", "음료"], []),
        ("cartbar", [], []),
        ("featuredWrap", [], ["undefined"]),
        ("estimateLine", [], ["undefined"]),
        ("orderList", [], [])])))

    results.append(("로그인 화면", run("login.js", {"/api/auth/me": me},
                                       [("msg", [], ["undefined"])], path="/login")))

    results.append(("사장님 주문", run("admin.js", {
        "/api/auth/me": me, "/api/state": state,
        f"/api/orders/{order_id}": state["orders"][0] if order_id else {},
    }, [("stats", ["오늘 주문", "결제 확인 매출", "미수금"], []),
        ("orderList", ["결제", "상세"], ["undefined"]),
        ("tables", ["1", "8"], []),
        ("callsBox", ["호출"], []),
        ("topItems", [], []),
        ("todayLabel", [], [])])))

    results.append(("주방 화면", run("kitchen.js", {"/api/auth/me": me, "/api/kitchen": kitchen},
                                     [("queue", ["번", "김밥"], ["undefined"]),
                                      ("counts", ["새 주문"], []),
                                      ("tstrip", [], [])])))

    results.append(("메뉴 관리", run("menu.js", {"/api/auth/me": me, "/api/menu/all": menu_all},
                                     [("menuSections", ["김밥", "3,500", "수정", "품절"], ["undefined"]),
                                      ("catChips", ["분식"], [])])))

    results.append(("회원 관리", run("customers.js", {"/api/auth/me": me, "/api/customers": members,
                                                     f"/api/customers/{(members['customers'] or [{}])[0].get('id', 0)}": (members["customers"] or [{}])[0]},
                                     [("custList", ["방문", "누적 결제", "포인트"], ["undefined"]),
                                      ("gradeStats", ["전체 회원"], []),
                                      ("countBadge", [], [])])))

    results.append(("QR·인쇄", run("qr.js", {"/api/auth/me": me, "/api/server-info": client.get("/api/server-info"),
                                              "/api/qr/config": qr_cfg},
                                   [("qgrid", ["/api/qr/8.png", "PNG"], ["undefined"]),
                                    ("nfcList", ["NFC"], []),
                                    ("baseInput", [], [])])))

    results.append(("직원 관리", run("staff.js", {"/api/auth/me": me, "/api/staff": staff,
                                              "/api/staff/permissions": staff_meta,
                                              "/api/schedule": schedule, "/api/payroll": client.get("/api/payroll")},
                                     [("staffList", ["근태", "급여"], ["undefined"]),
                                      ("monthSummary", [], []),
                                      ("countBadge", ["명"], [])], path="/staff")))

    results.append(("매출·정산", run("revenue.js", {"/api/auth/me": me, "/api/revenue": revenue},
                                    [("totals", ["결제 확인 매출", "미수금", "할인"], ["undefined"]),
                                     ("days", ["매출"], []),
                                     ("methods", ["현금", "미연동"], []),
                                     ("items", [], [])], path="/revenue")))

    results.append(("재고·재료", run("inventory.js", {"/api/auth/me": me, "/api/inventory": inventory_data},
                                    [("stats", ["등록 재료", "안전재고"], ["undefined"]),
                                     ("ingList", ["입고", "조정"], []),
                                     ("suggestList", [], [])], path="/inventory")))

    results.append(("예약 관리", run("reservations.js", {"/api/auth/me": me, "/api/reservations": reservations},
                                    [("stats", ["오늘 예약"], ["undefined"]),
                                     ("cal", [], []),
                                     ("dayList", [], [])], path="/reservations")))

    results.append(("리뷰", run("reviews.js", {"/api/auth/me": me, "/api/reviews": reviews_data},
                                [("stats", ["평균 별점"], ["undefined"]),
                                 ("trend", [], []),
                                 ("reviewList", [], [])], path="/reviews")))

    results.append(("매장 관리", run("stores.js", {"/api/auth/me": me, "/api/stores": stores_data,
                                              "/api/stores/comparison": comparison,
                                              "/api/stores/summary": store_summary,
                                              "/api/stores/staff": store_staff,
                                              "/api/stores/transfers": store_transfers},
                                    [("compare", ["오늘 매출"], ["undefined"]),
                                     ("summaryStats", ["오늘 통합 매출", "누적 매출"], []),
                                     ("shareBox", [], ["undefined"]),
                                     ("storeList", ["매장"], []),
                                     ("transferLog", [], ["undefined"])], path="/stores")))

    results.append(("내 계정", run("account.js", {"/api/auth/me": me, "/api/account/sessions": sessions},
                                  [("who", ["아이디"], ["undefined"]),
                                   ("sessions", ["기기"], [])], path="/account")))

    results.append(("예약 신청(손님)", run("reserve.js", {"/api/store": client.get("/api/store")},
                                         [("shopName", ["맛집"], ["undefined"])], path="/reserve")))

    results.append(("테이블 관리", run("tables.js", {"/api/auth/me": me, "/api/tables/admin": tables_admin},
                                       [("tableList", ["창가", "/t/"], ["undefined"]),
                                        ("totalBadge", ["테이블"], [])], path="/tables")))

    results.append(("매장 설정", run("settings.js", {"/api/auth/me": me, "/api/settings": settings_data},
                                     [("storeName", [], ["undefined"]),
                                      ("channelBox", ["브라우저", "문자"], []),
                                      ("tplBox", ["곧 순서", "호출"], []),
                                      ("staffBox", [], [])], path="/settings")))

    results.append(("웨이팅 관리", run("wait-admin.js", {"/api/auth/me": me, "/api/wait/admin": wait_admin},
                                       [("waitList", ["번호"], ["undefined"]),
                                        ("stats", ["대기 중", "호출 중"], []),
                                        ("notifyHistory", [], [])], path="/wait/admin")))

    results.append(("대기 보드", run("wait-board.js", {"/api/wait/board": board},
                                     [("calls", [], ["undefined"]),
                                      ("numbers", [], ["undefined"]),
                                      ("estimate", [], [])], path="/wait/board")))

    results.append(("대기 접수", run("wait.js", {"/api/auth/me": me, "/api/wait/board": board},
                                     [("wstore", ["맛집"], [])], path="/wait")))

    results.append(("테이블 선택(/order)", run("order.js", {"/api/tables/public": client.get("/api/tables/public")},
                                             [("tableRow", ["/t/"], ["undefined"])], path="/order")))

    results.append(("매장위치", run("places.js", {"/api/public/stores": client.get("/api/public/stores")},
                                     [("placeGrid", ["운양동", "/t/"], ["undefined"]),
                                      ("placeCount", ["곳"], [])], path="/places")))

    results.append(("게시판", run("board.js", {"/api/public/board": client.get("/api/public/board")},
                                    [("postList", ["시작합니다", "공지"], ["undefined"]),
                                     ("postCount", ["건"], [])], path="/board")))

    results.append(("요금제 계산", run("pricing.js", {},
                                     [("simTotal", ["20,000"], ["undefined"]),
                                      ("simRate", ["20원"], []),
                                      ("simVat", ["22,000원"], [])], path="/pricing")))

    print()
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    if not all(ok for _, ok in results):
        sys.exit(1)
    print("\n화면 렌더링 점검 통과")


if __name__ == "__main__":
    client = Client()
    main()
