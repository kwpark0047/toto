"""HTTP JSON API.

각 화면의 요청을 받아 해당 모듈(auth / stores / staff / settings / tables / catalog / orders /
inventory / reservations / reviews / kitchen / stats / customers / waiting / qrs …)을 호출하고
JSON으로 돌려준다. 이 파일에는 업무 로직을 두지 않는다 — 라우팅, 권한 검사, 매장 범위 설정,
응답 형식만 담당한다.

권한은 역할이 아니라 권한 키(config.PERMISSIONS)로 검사하고, 요청마다 stores.use(매장) 안에서 처리한다.
"""
import base64
import json
import os
import re
import time
from urllib.parse import parse_qs

from . import (auth, backup, catalog, config, customers, inventory, kitchen, notifier, oauth,
               orders, portal, reservations, reviews, qrs, recommend, service, settings, staff,
               stand, stats, stores, store, tables, voice_order, waiting)

JSON = "application/json; charset=utf-8"

# 권한 묶음(역할이 아니라 권한 키로 검사한다 — 역할 5종 + 직원별 예외)
ADMIN = {"admin"}                  # 관리자 전용(역할)
FRONT = {"admin", "counter", "manager"}
ALL_STAFF = {"admin", "counter", "kitchen", "manager", "part"}


class Response:
    def __init__(self, body=b"", status=200, content_type=JSON, headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


def json_response(data, status=200, headers=None):
    return Response(json.dumps(data, ensure_ascii=False).encode("utf-8"), status, JSON, headers)


def _query(parsed_query):
    return {k: v[0] for k, v in parsed_query.items()}


ROUTES = []


def route(method, pattern, roles=None, perm=None, login=False):
    """perm=권한키(또는 키 목록 중 하나), login=True(로그인만), roles=역할 집합(옛 방식)."""
    def wrap(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn,
                       {"roles": roles, "perm": perm, "login": login}))
        return fn
    return wrap


# ---------------------------------------------------------------- 계정·로그인

@route("POST", r"/api/auth/login")
def api_login(ctx):
    user, token, expires = auth.login(
        ctx["body"].get("username"), ctx["body"].get("password"),
        ip=ctx["ip"], user_agent=ctx["ua"])
    return json_response(_session_data(user), 200,
                         {"Set-Cookie": auth.cookie_header(token, config.SESSION_HOURS * 3600)})


@route("POST", r"/api/auth/signup")
def api_signup(ctx):
    b = ctx["body"]
    user, token, expires, _ = staff.signup(
        b.get("storeName"), b.get("username"), b.get("password"), b.get("tables"))
    return json_response(_session_data(user), 201,
                         {"Set-Cookie": auth.cookie_header(token, config.SESSION_HOURS * 3600)})


@route("POST", r"/api/auth/logout")
def api_logout(ctx):
    auth.logout(ctx["token"])
    return json_response({"ok": True}, 200,
                         {"Set-Cookie": auth.cookie_header("", 0)})


@route("GET", r"/api/auth/me")
def api_me(ctx):
    user = ctx["user"]
    data = {"user": user, "store": settings.public(), "setup": _setup()}
    if user:
        data["clock"] = staff.clock_state(user["id"])
        data["roleLabels"] = config.ROLE_LABELS
        data["roleHints"] = config.ROLE_HINTS
        data["permissionCatalog"] = [{"code": c, "label": l, "desc": d} for c, l, d in config.PERMISSIONS]
        data["stores"] = stores.list_stores(include_inactive=False)
        data["storeId"] = user.get("storeId") or 1
        data["canSwitchStore"] = user.get("role") == "admin"
    return json_response(data)


def _redirect(location, cookies=None, status=302):
    headers = {"Location": location, "Cache-Control": "no-store"}
    if cookies:
        headers["Set-Cookie"] = cookies if isinstance(cookies, (list, tuple)) else [cookies]
    return Response(b"", status, "text/plain; charset=utf-8", headers)


@route("GET", r"/api/auth/oauth/providers")
def api_oauth_providers(ctx):
    """소셜 로그인 사용 가능 여부. 앱 키가 없으면 configured=false 로 정직하게 알린다."""
    return json_response({
        "providers": oauth.status(),
        "redirectBase": oauth.public_base(ctx["base"]),
        "redirectUris": {name: oauth.redirect_uri(name, ctx["base"]) for name in oauth.PROVIDERS},
    })


@route("GET", r"/api/auth/oauth/(?P<provider>google|kakao)")
def api_oauth_start(ctx):
    provider = ctx["match"]["provider"]
    if not oauth.configured(provider):
        # 키가 없으면 가짜 로그인 없이 로그인 화면에서 안내로 돌려보낸다
        return _redirect(f"/login?oauth=not_configured&provider={provider}",
                         [oauth.clear_state_cookie()])
    state = oauth.new_state()
    url = oauth.authorize_url(provider, ctx["base"], state)
    return _redirect(url, [oauth.state_cookie(provider, state)])


@route("GET", r"/api/auth/oauth/(?P<provider>google|kakao)/callback")
def api_oauth_callback(ctx):
    provider = ctx["match"]["provider"]
    q = ctx["query"]
    fail = lambda code: _redirect(f"/login?oauth={code}&provider={provider}",
                                  [oauth.clear_state_cookie()])
    if q.get("error"):
        return fail("denied")
    if not oauth.check_state(provider, q.get("state") or "",
                             oauth.state_from_cookie(ctx.get("cookies"))):
        return fail("state")
    if not oauth.configured(provider):
        return fail("not_configured")
    code = q.get("code") or ""
    if not code:
        return fail("denied")
    try:
        access_token = oauth.exchange_code(provider, code, ctx["base"])
        profile = oauth.fetch_profile(provider, access_token)
        user, token, expires, created = oauth.login_with_profile(
            profile, provider, ip=ctx["ip"], ua=ctx["ua"], store_name=q.get("store") or "")
    except oauth.OAuthError as e:
        return fail(e.code)
    except Exception:  # 예상하지 못한 오류도 세션 없이 안내로 돌려보낸다
        import traceback
        traceback.print_exc()
        return fail("server")
    cookies = [auth.cookie_header(token, config.SESSION_HOURS * 3600), oauth.clear_state_cookie()]
    return _redirect("/admin?welcome=1" if created else "/admin", cookies)


def _session_data(user):
    data = {"user": user, "store": settings.public(), "setup": _setup(),
            "stores": stores.list_stores(include_inactive=False),
            "storeId": (user or {}).get("storeId") or 1,
            "canSwitchStore": bool(user) and user.get("role") == "admin",
            "permissionCatalog": [{"code": c, "label": l, "desc": d} for c, l, d in config.PERMISSIONS],
            "roleLabels": config.ROLE_LABELS, "roleHints": config.ROLE_HINTS}
    return data


def _setup():
    """첫 화면 안내용 상태. 강요하지 않고 '무엇이 비었는지'만 알려 준다."""
    with store.read() as conn:
        staff_count = conn.execute("SELECT COUNT(*) c FROM staff WHERE active=1 AND store_id=?",
                                   (stores.current(),)).fetchone()["c"]
    tlist = tables.list_tables()
    return {
        "hasOwner": staff.has_owner(),
        "staffCount": staff_count,
        "tableCount": len(tlist),
        "activeTableCount": len([t for t in tlist if t["active"]]),
        "profileEmpty": settings.profile_empty(),
        "pointsRate": settings.points_rate(),
        "gradesText": customers.grade_criteria_text(),
    }


@route("POST", r"/api/account/password", login=True)
def api_account_password(ctx):
    b = ctx["body"]
    auth.change_password(ctx["user"]["id"], b.get("current"), b.get("new"),
                         keep_token=ctx["token"])
    return json_response({"ok": True})


@route("PATCH", r"/api/account", login=True)
def api_account_update(ctx):
    data = {}
    if "username" in ctx["body"]:
        data["username"] = ctx["body"].get("username")
    if "name" in ctx["body"] and ctx["user"]["role"] == "admin":
        data["name"] = ctx["body"].get("name")
    if not data:
        return json_response({"ok": True})
    return json_response({"user": staff.update(ctx["user"]["id"], data, actor=ctx["user"])})


@route("GET", r"/api/account/sessions", login=True)
def api_account_sessions(ctx):
    return json_response({"sessions": auth.sessions_for(ctx["user"]["id"], ctx["token"])})


# ---------------------------------------------------------------- 공개 포털
# 로그인 없이 쓰는 서비스 소개·매장 목록·문의·게시판. 개인정보는 받는 목적만큼만.

@route("GET", r"/api/public/stores")
def api_public_stores(ctx):
    return json_response(portal.public_stores())


@route("POST", r"/api/public/inquiries")
def api_public_inquiry(ctx):
    return json_response(portal.create_inquiry(ctx["body"]), 201)


@route("GET", r"/api/public/board")
def api_public_board(ctx):
    return json_response(portal.list_posts((ctx["query"].get("category") or "").strip()))


@route("POST", r"/api/public/board")
def api_public_board_create(ctx):
    return json_response(portal.create_post(ctx["body"]), 201)


@route("GET", r"/api/public/board/(?P<id>\d+)")
def api_public_board_one(ctx):
    return json_response(portal.get_post(int(ctx["match"]["id"])))


@route("POST", r"/api/public/board/(?P<id>\d+)/comments")
def api_public_board_comment(ctx):
    return json_response(portal.add_comment(int(ctx["match"]["id"]), ctx["body"]), 201)


@route("GET", r"/api/inquiries", perm="settings.edit")
def api_inquiries(ctx):
    return json_response(portal.list_inquiries())


# ---------------------------------------------------------------- 매장·설정

@route("GET", r"/api/store")
def api_store(ctx):
    return json_response({
        "store": settings.public(),
        "serverTime": store.now(),
        "today": store.today(),
        "statusLabels": config.STATUS_LABELS,
        "paymentLabels": config.PAYMENT_LABELS,
    })


@route("GET", r"/api/settings", perm="settings.edit")
def api_settings(ctx):
    data = settings.summary_for_admin()
    data["sessions"] = auth.sessions_for(ctx["user"]["id"], ctx["token"])
    data["staff"] = staff.list_staff()
    data["tables"] = tables.stats_for_admin()
    data["notifications"] = notifier.overview()
    data["user"] = ctx["user"]
    return json_response(data)


@route("PATCH", r"/api/settings", perm="settings.edit")
def api_settings_save(ctx):
    saved = settings.save(ctx["body"])
    data = settings.summary_for_admin()
    data["saved"] = saved
    return json_response(data)


# ---------------------------------------------------------------- 메뉴

@route("GET", r"/api/menu")
def api_menu(ctx):
    code = ctx["query"].get("code")
    if code:
        t = tables.by_code(code)
        if t:
            with stores.use(t["storeId"]):
                return _menu_payload(ctx)
    return _menu_payload(ctx)


def _menu_payload(ctx):
    data = catalog.customer_menu()
    lang = (ctx["query"].get("lang") or "").lower()
    if lang in catalog.LANGS:
        for it in data["items"]:
            tr = (it.get("i18n") or {}).get(lang)
            if tr:
                it["name"] = tr.get("name") or it["name"]
                it["description"] = tr.get("description") or it["description"]
            it["nameOriginal"] = it.get("nameOriginal") or it["name"]
    data["store"] = settings.public()
    data["rev"] = store.rev()
    data["pointsRate"] = settings.points_rate()
    data["featured"] = catalog.featured()
    return json_response(data)


@route("GET", r"/api/menu/all", perm=("menu.edit", "price.edit", "soldout.manage"))
def api_menu_all(ctx):
    return json_response({
        "categories": catalog.categories(),
        "items": catalog.items(),
        "rev": store.rev(),
    })


@route("GET", r"/api/state", perm="order.manage")
def api_state(ctx):
    """화면 폴링용 묶음 응답."""
    q = ctx["query"]
    date = q.get("date") or store.today()
    with store.read() as conn:
        r = store.rev(conn)
    st = stats.summary(date)
    if not auth.has_perm(ctx["user"], "sales.view"):
        # 매출 조회 권한이 없으면 금액은 빼고 건수만 준다
        keep = ("date", "orderCount", "activeCount", "doneCount", "servedCount",
                "unpaidCount", "canceledCount")
        st = {k: st[k] for k in keep}
        st["salesHidden"] = True
    return json_response({
        "rev": r,
        "today": store.today(),
        "orders": orders.list_orders(date=date, limit=100),
        "tables": kitchen.tables(),
        "counts": kitchen.counts(),
        "summary": st,
        "waiting": waiting.board() if ctx["user"]["role"] in ("admin", "counter") else None,
        "calls": service.open_calls(),
    })


@route("GET", r"/api/orders/(?P<id>\d+)")
def api_order_get(ctx):
    data = orders.get(int(ctx["match"]["id"]))
    if not ctx["user"]:
        # 손님에게는 주문 확인에 필요한 것만(이름·연락처는 돌려주지 않는다)
        data["customerName"] = ""
        data["customerPhone"] = ""
    return json_response(data)


@route("GET", r"/api/orders", perm=("order.manage", "kitchen.view", "order.status"))
def api_orders(ctx):
    q = ctx["query"]
    ids = q.get("ids")
    parsed_ids = [int(i) for i in ids.split(",") if i.strip().isdigit()] if ids else None
    if ids is not None and not parsed_ids:
        return json_response({"orders": []})
    rows = orders.list_orders(
        date=q.get("date"),
        status=q.get("status"),
        table=q.get("table"),
        ids=parsed_ids,
        unpaid=q.get("unpaid") == "1",
        limit=min(int(q.get("limit", 200) or 200), 500),
    )
    return json_response({"orders": rows})


@route("GET", r"/api/kitchen", perm="kitchen.view")
def api_kitchen(ctx):
    return json_response({
        "queue": kitchen.queue(),
        "serving": kitchen.serving(),
        "counts": kitchen.counts(),
        "tables": kitchen.tables(),
        "rev": store.rev(),
        "serverTime": store.now(),
        "calls": service.open_calls(),
    })


@route("GET", r"/api/summary", perm="sales.view")
def api_summary(ctx):
    return json_response(stats.summary(ctx["query"].get("date")))


# ---------------------------------------------------------------- 주문

@route("POST", r"/api/orders")
def api_order_create(ctx):
    b = ctx["body"]
    return json_response(orders.create(
        b.get("table"), b.get("items") or [], b.get("customer") or {}, b.get("note", ""),
        b.get("pointsUsed", 0), b.get("preorderToken"), b.get("receipt")
    ), 201)


@route("POST", r"/api/orders/(?P<id>\d+)/cancel")
def api_order_cancel_customer(ctx):
    """손님 주문 취소(조리 시작 전만). 테이블 번호가 맞아야 한다."""
    order_id = int(ctx["match"]["id"])
    table = ctx["body"].get("table")
    o = orders.get(order_id)
    if table is not None and str(o["table"]) != str(table):
        raise ValueError("주문 정보가 맞지 않습니다")
    with stores.use(o.get("storeId") or 1):
        return json_response(orders.cancel_by_customer(order_id, ctx["body"].get("reason", "")))


@route("POST", r"/api/orders/(?P<id>\d+)/status", perm="order.status")
def api_order_status(ctx):
    status = ctx["body"].get("status", "")
    if status == "CANCELED" and not auth.has_perm(ctx["user"], "order.cancel"):
        return json_response({"error": "주문 취소 권한이 없습니다"}, 403)
    return json_response(orders.set_status(int(ctx["match"]["id"]), status))


@route("POST", r"/api/orders/(?P<id>\d+)/receipt", perm="order.manage")
def api_order_receipt(ctx):
    """현금영수증 발급 완료 표시(실제 국세청 발급은 하지 않는다)."""
    return json_response(orders.set_receipt_issued(int(ctx["match"]["id"]),
                                                   bool(ctx["body"].get("issued", True))))


@route("POST", r"/api/orders/(?P<id>\d+)/payment", perm="order.manage")
def api_order_payment(ctx):
    paid = bool(ctx["body"].get("paid"))
    if not paid and not auth.has_perm(ctx["user"], "order.cancel"):
        return json_response({"error": "결제 취소(환불) 권한이 없습니다"}, 403)
    return json_response(orders.set_payment(int(ctx["match"]["id"]), paid))


# ---------------------------------------------------------------- 메뉴 관리 (사장님)

@route("GET", r"/api/categories", login=True)
def api_categories(ctx):
    return json_response({"categories": catalog.categories()})


@route("POST", r"/api/categories", perm="menu.edit")
def api_category_create(ctx):
    return json_response(catalog.create_category(ctx["body"].get("name")), 201)


@route("PATCH", r"/api/categories/(?P<id>\d+)", perm="menu.edit")
def api_category_update(ctx):
    return json_response({"categories": catalog.rename_category(int(ctx["match"]["id"]), ctx["body"].get("name"))})


@route("DELETE", r"/api/categories/(?P<id>\d+)", perm="menu.edit")
def api_category_delete(ctx):
    catalog.delete_category(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("POST", r"/api/categories/(?P<id>\d+)/move", perm="menu.edit")
def api_category_move(ctx):
    return json_response({"categories": catalog.move_category(int(ctx["match"]["id"]), ctx["body"].get("dir", "up"))})


@route("POST", r"/api/items", perm="menu.edit")
def api_item_create(ctx):
    return json_response(catalog.create_item(ctx["body"]), 201)


@route("PATCH", r"/api/items/(?P<id>\d+)", perm=("menu.edit", "price.edit", "soldout.manage"))
def api_item_update(ctx):
    item_id = int(ctx["match"]["id"])
    body = ctx["body"]
    current = catalog.get_item(item_id)
    if "price" in body:
        try:
            new_price = int(body.get("price"))
        except (TypeError, ValueError):
            raise ValueError("가격은 숫자로 입력해 주세요")
        if new_price != current["price"] and not auth.has_perm(ctx["user"], "price.edit"):
            return json_response({"error": "가격 변경 권한이 없습니다"}, 403)
    other = {k: v for k, v in body.items() if k != "price"}
    if other and not auth.has_perm(ctx["user"], "menu.edit"):
        # 품절만 바꾸는 경우는 soldout.manage 로 허용
        if not (set(other) <= {"soldout"} and auth.has_perm(ctx["user"], "soldout.manage")):
            return json_response({"error": "메뉴 수정 권한이 없습니다"}, 403)
    return json_response(catalog.update_item(item_id, body))


@route("DELETE", r"/api/items/(?P<id>\d+)", perm="menu.edit")
def api_item_delete(ctx):
    catalog.delete_item(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("POST", r"/api/items/(?P<id>\d+)/soldout", perm=("soldout.manage", "menu.edit"))
def api_item_soldout(ctx):
    return json_response(catalog.set_soldout(int(ctx["match"]["id"]), bool(ctx["body"].get("soldout"))))


@route("POST", r"/api/items/(?P<id>\d+)/featured", perm="menu.edit")
def api_item_featured(ctx):
    b = ctx["body"]
    return json_response(catalog.set_featured(
        int(ctx["match"]["id"]), bool(b.get("featured", True)), b.get("note"),
        b.get("sort")))


@route("POST", r"/api/items/(?P<id>\d+)/featured/move", perm="menu.edit")
def api_item_featured_move(ctx):
    return json_response(catalog.move_featured(int(ctx["match"]["id"]), ctx["body"].get("dir", "up")))


@route("POST", r"/api/items/(?P<id>\d+)/move", perm="menu.edit")
def api_item_move(ctx):
    items = catalog.move_item(int(ctx["match"]["id"]), ctx["body"].get("dir", "up"))
    return json_response({"items": items})


@route("POST", r"/api/items/(?P<id>\d+)/photo", perm="menu.edit")
def api_item_photo(ctx):
    item_id = int(ctx["match"]["id"])
    data_url = (ctx["body"].get("dataUrl") or "")
    if not data_url.startswith("data:image/"):
        raise ValueError("사진 파일을 선택해 주세요")
    head, _, payload = data_url.partition(",")
    mime = head[5:].split(";")[0].lower()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime)
    if not ext:
        raise ValueError("JPG·PNG·WEBP 사진만 올릴 수 있습니다")
    raw = base64.b64decode(payload, validate=False)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("사진이 너무 큽니다(4MB 이하). 브라우저에서 자동으로 줄이지만, 다시 시도해 주세요")
    folder = os.path.join(config.PUBLIC_DIR, "images", "uploads")
    os.makedirs(folder, exist_ok=True)
    name = f"item-{item_id}-{int(time.time())}.{ext}"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(raw)
    return json_response(catalog.set_image(item_id, f"/images/uploads/{name}"))


# ---------------------------------------------------------------- 테이블

@route("GET", r"/api/tables", perm=("order.manage", "settings.edit", "kitchen.view"))
def api_tables(ctx):
    return json_response({"tables": tables.list_tables()})


@route("GET", r"/api/tables/admin", perm="settings.edit")
def api_tables_admin(ctx):
    return json_response(tables.stats_for_admin())


@route("POST", r"/api/tables", perm="settings.edit")
def api_table_create(ctx):
    b = ctx["body"]
    return json_response(tables.create(b.get("label"), b.get("seats", 0), b.get("active", True)), 201)


@route("PATCH", r"/api/tables/(?P<id>\d+)", perm="settings.edit")
def api_table_update(ctx):
    return json_response(tables.update(int(ctx["match"]["id"]), ctx["body"]))


@route("DELETE", r"/api/tables/(?P<id>\d+)", perm="settings.edit")
def api_table_delete(ctx):
    tables.delete(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("POST", r"/api/tables/(?P<id>\d+)/move", perm="settings.edit")
def api_table_move(ctx):
    return json_response({"tables": tables.move(int(ctx["match"]["id"]), ctx["body"].get("dir", "up"))})


@route("GET", r"/api/recommend")
def api_recommend(ctx):
    q = ctx["query"]
    table = q.get("table") if str(q.get("table") or "").isdigit() else None
    ids = [i for i in (q.get("items") or "").split(",") if i.isdigit()]
    if table:
        try:
            with stores.use(tables.get_any(int(table))["storeId"]):
                return json_response(recommend.for_customer(table, ids))
        except LookupError:
            pass
    return json_response(recommend.for_customer(table, ids))


@route("GET", r"/api/table/(?P<code>[A-Za-z0-9_-]+)")
def api_table_by_code(ctx):
    t = tables.by_code(ctx["match"]["code"])
    if not t:
        raise LookupError("없는 테이블 주소입니다")
    with stores.use(t["storeId"]):
        return json_response({
            "table": t, "store": settings.public(),
            "pointsRate": settings.points_rate(),
            "paymentNote": settings.get()["paymentNote"],
        })


# ---------------------------------------------------------------- 직원·출퇴근

@route("GET", r"/api/staff", perm="staff.manage")
def api_staff(ctx):
    q = ctx["query"]
    data = staff.list_staff(q.get("q", ""), q.get("sort", "name"), q.get("month"))
    data["summary"] = staff.month_summary(q.get("month"))
    data["roles"] = config.ROLE_LABELS
    return json_response(data)


@route("POST", r"/api/staff", perm="staff.manage")
def api_staff_create(ctx):
    body = dict(ctx["body"])
    if ctx["user"]["role"] != "admin":
        # 관리자가 아닌 사람은 관리자 역할·권한 예외를 줄 수 없다(권한 상승 방지)
        if body.get("role") == "admin":
            return json_response({"error": "관리자 역할은 관리자만 만들 수 있습니다"}, 403)
        body["permissions"] = {}
    return json_response(staff.create(body, actor=ctx["user"]), 201)


@route("PATCH", r"/api/staff/(?P<id>\d+)", perm="staff.manage")
def api_staff_update(ctx):
    body = dict(ctx["body"])
    if ctx["user"]["role"] != "admin" and ("role" in body or "permissions" in body):
        return json_response({"error": "역할·권한 변경은 관리자만 할 수 있습니다"}, 403)
    return json_response(staff.update(int(ctx["match"]["id"]), body, actor=ctx["user"]))


@route("GET", r"/api/staff/attendance", perm="staff.manage")
def api_staff_attendance(ctx):
    q = ctx["query"]
    staff_id = int(q["staffId"]) if q.get("staffId", "").isdigit() else None
    data = staff.attendance_list(staff_id, q.get("month"))
    data["summary"] = staff.month_summary(q.get("month"))
    return json_response(data)


@route("GET", r"/api/staff/attendance\.csv", perm="staff.manage")
def api_staff_attendance_csv(ctx):
    q = ctx["query"]
    staff_id = int(q["staffId"]) if q.get("staffId", "").isdigit() else None
    body, month = staff.month_csv(q.get("month"), staff_id)
    return Response(body, 200, "text/csv; charset=utf-8", {
        "Content-Disposition": f'attachment; filename="attendance-{month}.csv"'})


@route("GET", r"/api/me/clock", login=True)
def api_me_clock(ctx):
    return json_response(staff.clock_state(ctx["user"]["id"]))


@route("POST", r"/api/attendance/clock-in", login=True)
def api_clock_in(ctx):
    rec = staff.clock_in(ctx["user"]["id"])
    return json_response({"record": rec, "clock": staff.clock_state(ctx["user"]["id"])})


@route("POST", r"/api/attendance/manual", perm="staff.manage")
def api_attendance_manual(ctx):
    b = ctx["body"]
    return json_response(staff.add_attendance_manual(
        b.get("staffId"), b.get("date"), b.get("start"), b.get("end"), b.get("memo", "")), 201)


@route("POST", r"/api/attendance/clock-out", login=True)
def api_clock_out(ctx):
    rec = staff.clock_out(ctx["user"]["id"])
    return json_response({"record": rec, "clock": staff.clock_state(ctx["user"]["id"])})


# ---------------------------------------------------------------- 회원

@route("GET", r"/api/customers", perm="customer.view")
def api_customers(ctx):
    q = ctx["query"]
    rows = customers.list_customers(q.get("q", ""), q.get("sort", "recent"), q.get("grade", ""))
    return json_response({"customers": rows, "counts": customers.counts(rows)})


@route("GET", r"/api/customers\.csv", perm="customer.view")
def api_customers_csv(ctx):
    q = ctx["query"]
    rows = customers.list_customers(q.get("q", ""), q.get("sort", "recent"), q.get("grade", ""))
    body = customers.to_csv(rows)
    return Response(body, 200, "text/csv; charset=utf-8", {
        "Content-Disposition": 'attachment; filename="members.csv"'})


@route("POST", r"/api/customers", perm="customer.view")
def api_customer_create(ctx):
    return json_response(customers.create_member(ctx["body"]), 201)


@route("GET", r"/api/customers/(?P<id>\d+)", perm="customer.view")
def api_customer_get(ctx):
    return json_response(customers.get_member(int(ctx["match"]["id"])))


@route("PATCH", r"/api/customers/(?P<id>\d+)", perm="customer.view")
def api_customer_update(ctx):
    return json_response(customers.update(int(ctx["match"]["id"]), ctx["body"]))


@route("DELETE", r"/api/customers/(?P<id>\d+)", perm="customer.view")
def api_customer_delete(ctx):
    customers.delete(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("POST", r"/api/customers/(?P<id>\d+)/grade", perm="customer.view")
def api_customer_grade(ctx):
    return json_response(customers.set_grade(int(ctx["match"]["id"]), ctx["body"].get("grade")))


@route("POST", r"/api/customers/(?P<id>\d+)/merge", perm="customer.view")
def api_customer_merge(ctx):
    return json_response(customers.merge(int(ctx["match"]["id"]), ctx["body"].get("ids") or []))


@route("GET", r"/api/member/lookup")
def api_member_lookup(ctx):
    """주문서에서 보유 포인트만 확인(이름·이력은 돌려주지 않는다)."""
    return json_response(customers.lookup(ctx["query"].get("phone", "")))


# ---------------------------------------------------------------- 웨이팅

@route("POST", r"/api/wait")
def api_wait_create(ctx):
    b = ctx["body"]
    data = waiting.create(b.get("name"), b.get("phone"), b.get("party"), b.get("consent"),
                          b.get("note", ""))
    data["channels"] = notifier.channels()
    return json_response(data, 201)


@route("GET", r"/api/wait/t/(?P<token>[A-Za-z0-9_-]+)")
def api_wait_ticket(ctx):
    return json_response({"ticket": waiting.by_token(ctx["match"]["token"])})


@route("GET", r"/api/wait/find")
def api_wait_find(ctx):
    return json_response({"ticket": waiting.by_phone(ctx["query"].get("phone", ""))})


@route("GET", r"/api/wait/board")
def api_wait_board(ctx):
    data = waiting.board()
    data["store"] = settings.public()
    return json_response(data)


@route("GET", r"/api/wait/admin", perm="order.manage")
def api_wait_admin(ctx):
    data = waiting.admin_list()
    data["tickets"] = data.get("tickets") or []
    data["notifications"] = notifier.overview()
    data["tables"] = tables.list_tables(include_inactive=False)
    return json_response(data)


@route("POST", r"/api/wait/(?P<id>\d+)/call", perm="order.manage")
def api_wait_call(ctx):
    return json_response(waiting.call(int(ctx["match"]["id"])))


@route("POST", r"/api/wait/(?P<id>\d+)/start", perm="order.manage")
def api_wait_start(ctx):
    """미리 주문을 직원이 먼저 주방으로 넘긴다(입장 처리 없이)."""
    started = orders.start_reserved(int(ctx["match"]["id"]), ctx["body"].get("tableId"))
    return json_response({"started": started})


@route("POST", r"/api/wait/(?P<id>\d+)/seat", perm="order.manage")
def api_wait_seat(ctx):
    return json_response(waiting.seat(int(ctx["match"]["id"]), ctx["body"].get("tableId")))


@route("POST", r"/api/wait/(?P<id>\d+)/(?P<act>cancel|noshow)", perm="order.manage")
def api_wait_close(ctx):
    act = ctx["match"]["act"]
    return json_response(waiting.close(int(ctx["match"]["id"]), "CANCELED" if act == "cancel" else "NOSHOW"))


@route("POST", r"/api/wait/t/(?P<token>[A-Za-z0-9_-]+)/notified")
def api_wait_notified(ctx):
    """대기 화면이 브라우저 알림을 띄운 사실을 기록한다(실제 발송은 브라우저가 한다)."""
    ticket = waiting.by_token(ctx["match"]["token"])
    b = ctx["body"]
    return json_response(notifier.record_browser(
        ticket, b.get("event", "called"), b.get("status", "sent"),
        b.get("detail") or "브라우저 화면에서 표시"))


# ---------------------------------------------------------------- 알림

@route("GET", r"/api/notifications", perm="order.manage")
def api_notifications(ctx):
    return json_response(notifier.overview(ctx["query"].get("date")))


@route("POST", r"/api/notifications/send", perm="order.manage")
def api_notifications_send(ctx):
    """대기 1건에 대해 한 채널로 보낸다. 문자·카카오는 실제 전송 없이 '미연결' 기록만 남는다."""
    b = ctx["body"]
    ticket_id = b.get("ticketId")
    if not str(ticket_id or "").isdigit():
        raise ValueError("대기를 골라 주세요")
    data = waiting.admin_list()
    ticket = next((t for t in data["tickets"] if t["id"] == int(ticket_id)), None)
    if not ticket:
        raise LookupError("대기 정보를 찾을 수 없습니다")
    return json_response(notifier.send(b.get("channel", "sms"), b.get("event", "called"), ticket))


@route("POST", r"/api/notifications/test", perm="settings.edit")
def api_notifications_test(ctx):
    """설정 화면의 미리보기/테스트. 본인 앞으로 한 건 기록한다."""
    b = ctx["body"]
    user = ctx["user"]
    fake = {"id": None, "ticketNo": "TEST", "name": user["name"], "phone": "010-0000-0000",
            "consent": True, "partySize": 2, "ahead": 2}
    return json_response(notifier.send(b.get("channel", "browser"), b.get("event", "soon"), fake))


@route("POST", r"/api/notifications/push-subscribe")
def api_push_subscribe(ctx):
    return json_response(notifier.save_push_subscription(ctx["body"]))


# ---------------------------------------------------------------- 직원 호출

@route("POST", r"/api/calls")
def api_call_create(ctx):
    b = ctx["body"]
    if not str(b.get("table") or "").isdigit():
        raise ValueError("테이블 정보가 없습니다. QR을 다시 찍어 주세요")
    t = tables.get_any(int(b.get("table")))
    with stores.use(t["storeId"]):
        return json_response(service.call(int(b.get("table")), b.get("note", "")), 201)


@route("GET", r"/api/calls")
def api_calls_public(ctx):
    """손님 화면: 이 테이블의 열린 호출 상태."""
    q = ctx["query"]
    if not str(q.get("table") or "").isdigit():
        return json_response({"calls": []})
    try:
        t = tables.get_any(int(q.get("table")))
    except LookupError:
        return json_response({"calls": []})
    with stores.use(t["storeId"]):
        return json_response({"calls": service.open_calls(int(q.get("table")))})


@route("GET", r"/api/calls/admin", perm=("order.manage", "order.status", "kitchen.view"))
def api_calls_admin(ctx):
    return json_response({"calls": service.open_calls(), "summary": service.today_summary()})


@route("POST", r"/api/calls/(?P<id>\d+)/done", perm=("order.manage", "order.status", "kitchen.view"))
def api_call_done(ctx):
    return json_response(service.done(int(ctx["match"]["id"]), ctx["user"]["id"]))


# ---------------------------------------------------------------- 백업·복원

@route("GET", r"/api/backup", perm="settings.edit")
def api_backup_list(ctx):
    return json_response({"backups": backup.list_backups(), "keep": backup.KEEP,
                          "dbPath": os.path.basename(config.DB_PATH)})


@route("POST", r"/api/backup", perm="settings.edit")
def api_backup_create(ctx):
    return json_response(backup.create("manual"), 201)


@route("GET", r"/api/backup/download", perm="settings.edit")
def api_backup_download(ctx):
    data = backup.export_bytes()
    name = f"mangjip-backup-{store.today().replace('-', '')}.db"
    return Response(data, 200, "application/octet-stream", {
        "Content-Disposition": f'attachment; filename="{name}"'})


@route("POST", r"/api/backup/restore", perm="settings.edit")
def api_backup_restore(ctx):
    b = ctx["body"]
    return json_response(backup.restore(b.get("name"), b.get("confirm")))


# ---------------------------------------------------------------- 음성 주문

@route("GET", r"/api/voice/menu")
def api_voice_menu(ctx):
    """음성 주문 화면이 쓰는 최소 메뉴 목록(이름·가격·옵션·품절)."""
    return json_response({
        "items": [{"id": i["id"], "name": i["name"], "price": i["price"],
                   "soldout": bool(i["soldout"]), "options": i["options"]} for i in catalog.items()],
        "saveText": bool((settings.get().get("voice") or {}).get("saveText", True)),
    })


@route("POST", r"/api/voice/parse")
def api_voice_parse(ctx):
    """문장 → 담을 항목/뺠 항목/후보. 음성 파일은 오지 않는다(브라우저에서 인식한 텍스트만)."""
    text = (ctx["body"].get("text") or "").strip()
    if not text:
        raise ValueError("말한 내용이 비어 있습니다")
    return json_response(voice_order.parse(text[:200]))


@route("GET", r"/api/voice/log", perm="settings.edit")
def api_voice_log(ctx):
    return json_response({"logs": voice_order.log(int(ctx["query"].get("limit", 50)))})


# ---------------------------------------------------------------- QR·NFC·인쇄물

def _table_for(code):
    t = tables.by_code(code)
    if not t:
        raise LookupError("없는 테이블 코드입니다")
    return t


@route("GET", r"/api/qr/(?P<code>[A-Za-z0-9_-]+)\.png")
def api_qr_png(ctx):
    base = ctx["query"].get("base") or ctx["base"]
    if ctx["match"]["code"] in ("store", "wait"):
        label = "매장 공통" if ctx["match"]["code"] == "store" else "대기 접수"
        data, info = qrs.png(ctx["match"]["code"], base, px=int(ctx["query"].get("px", 12)),
                             label=label, store_name=settings.public()["name"] or "맛집")
        return Response(data, 200, "image/png", {"Cache-Control": "no-store"})
    t = _table_for(ctx["match"]["code"])
    with stores.use(t["storeId"]):
        data, info = qrs.png(t["code"], base, px=int(ctx["query"].get("px", 12)),
                             label=t["label"], store_name=settings.public()["name"] or "맛집",
                             design=ctx["query"].get("design") != "0")
    return Response(data, 200, "image/png",
                    {"Cache-Control": "no-store", "X-QR-Url": info.get("url", "")})


@route("GET", r"/api/qr/(?P<code>[A-Za-z0-9_-]+)\.svg")
def api_qr_svg(ctx):
    base = ctx["query"].get("base") or ctx["base"]
    if ctx["match"]["code"] in ("store", "wait"):
        label = "매장 공통" if ctx["match"]["code"] == "store" else "대기 접수"
        data = qrs.svg(ctx["match"]["code"], base, px=int(ctx["query"].get("px", 8)), label=label,
                       store_name=settings.public()["name"] or "맛집")
        return Response(data, 200, "image/svg+xml; charset=utf-8", {"Cache-Control": "no-store"})
    t = _table_for(ctx["match"]["code"])
    with stores.use(t["storeId"]):
        data = qrs.svg(t["code"], base, px=int(ctx["query"].get("px", 8)), label=t["label"],
                       store_name=settings.public()["name"] or "맛집")
    return Response(data, 200, "image/svg+xml; charset=utf-8", {"Cache-Control": "no-store"})


@route("GET", r"/api/qr/store\.png")
def api_qr_store_png(ctx):
    base = ctx["query"].get("base") or ctx["base"]
    data, info = qrs.png("store", base, px=int(ctx["query"].get("px", 12)), label="매장 공통",
                         store_name=settings.public()["name"] or "맛집")
    return Response(data, 200, "image/png", {"Cache-Control": "no-store"})


@route("GET", r"/api/qr/store\.svg")
def api_qr_store_svg(ctx):
    base = ctx["query"].get("base") or ctx["base"]
    data = qrs.svg("store", base, px=int(ctx["query"].get("px", 8)), label="매장 공통",
                   store_name=settings.public()["name"] or "맛집")
    return Response(data, 200, "image/svg+xml; charset=utf-8", {"Cache-Control": "no-store"})


@route("GET", r"/api/qr/config", perm="settings.edit")
def api_qr_config(ctx):
    st = settings.get()
    return json_response({
        "options": qrs.design_options(),
        "stand": st.get("stand") or {},
        "sizes": list(stand.SIZES),
        "layouts": list(stand.LAYOUTS),
        "tables": tables.list_tables(),
        "store": settings.public(),
        "nfc": [{"code": t["code"], "label": t["label"],
                 "url": qrs.table_url(ctx["base"], t["code"]), "active": t["active"]}
                for t in tables.list_tables()],
        "storeUrl": qrs.store_url(ctx["base"]),
    })


@route("PATCH", r"/api/qr/config", perm="settings.edit")
def api_qr_config_save(ctx):
    b = ctx["body"]
    patch = {}
    if "options" in b:
        patch["qr"] = b["options"]
    if "stand" in b:
        patch["stand"] = b["stand"]
    settings.save(patch)
    return json_response({"options": qrs.design_options(), "stand": settings.get().get("stand")})


@route("POST", r"/api/qr/badge", perm="settings.edit")
def api_qr_badge(ctx):
    data_url = ctx["body"].get("dataUrl") or ""
    if not data_url.startswith("data:image/"):
        raise ValueError("배지로 쓸 이미지 파일을 선택해 주세요")
    head, _, payload = data_url.partition(",")
    mime = head[5:].split(";")[0].lower()
    ext = {"image/jpeg": "jpg", "image/png": "png"}.get(mime)
    if not ext:
        raise ValueError("PNG·JPG 이미지만 배지로 쓸 수 있습니다")
    raw = base64.b64decode(payload, validate=False)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("배지 이미지는 2MB 이하로 올려 주세요")
    folder = os.path.join(config.PUBLIC_DIR, "images")
    os.makedirs(folder, exist_ok=True)
    name = f"qr-badge-{int(time.time())}.{ext}"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(raw)
    settings.save({"qr": {**qrs.design_options(), "badge": "logo",
                          "badgeImage": f"/images/{name}"}})
    return json_response({"options": qrs.design_options()})


@route("GET", r"/api/qr/verify", perm="settings.edit")
def api_qr_verify(ctx):
    q = ctx["query"]
    code = q.get("code") or "store"
    base = q.get("base") or ctx["base"]
    label = "매장 공통"
    if code != "store":
        t = _table_for(code)
        label = t["label"]
        with stores.use(t["storeId"]):
            data, info = qrs.png(code, base, px=int(q.get("px", 12)), label=label,
                                 store_name=settings.public()["name"] or "맛집")
    else:
        data, info = qrs.png(code, base, px=int(q.get("px", 12)), label=label,
                             store_name=settings.public()["name"] or "맛집")
    return json_response({"ok": info.get("verified"), "url": info.get("url"),
                          "designed": info.get("designed"), "badgeRatio": info.get("badgeRatio"),
                          "fallback": info.get("fallback")})


# ---------------------------------------------------------------- 메뉴판 인쇄물

@route("GET", r"/api/print/stands\.pdf", perm="settings.edit")
def api_print_pdf(ctx):
    q = ctx["query"]
    kind = "wait" if q.get("kind") == "wait" else "table"
    data, name = stand.build_pdf(ctx["base"], q.get("size", "B4" if kind == "wait" else "A5"),
                                 q.get("layout", 1), kind=kind)
    return Response(data, 200, "application/pdf", {
        "Content-Disposition": f'attachment; filename="{name}"'})


@route("GET", r"/api/print/wait\.png", perm="settings.edit")
def api_print_wait_png(ctx):
    data, info = stand.poster_image(ctx["base"], ctx["query"].get("size", "B4"))
    return Response(data, 200, "image/jpeg", {"Cache-Control": "no-store"})


@route("GET", r"/api/print/stand\.png", perm="settings.edit")
def api_print_stand_png(ctx):
    q = ctx["query"]
    t = _table_for(q.get("code") or "1")
    with stores.use(t["storeId"]):
        data, info = stand.stand_image(t, ctx["base"], q.get("size", "A5"))
    return Response(data, 200, "image/jpeg", {"Cache-Control": "no-store"})


@route("GET", r"/api/print/stands", perm="settings.edit")
def api_print_stands(ctx):
    q = ctx["query"]
    return json_response(stand.stands_for_print(ctx["base"], q.get("size", "A5"),
                                               q.get("layout", 1), q.get("kind", "table")))


@route("GET", r"/api/tables/public")
def api_tables_public(ctx):
    """매장 공통 QR(/)에서 손님이 테이블을 고를 때 쓰는 목록. 활성 테이블만."""
    return json_response({
        "store": settings.public(),
        "tables": [{"code": t["code"], "label": t["label"], "seats": t["seats"]}
                   for t in tables.list_tables(include_inactive=False)],
    })


@route("GET", r"/api/server-info", perm="settings.edit")
def api_server_info(ctx):
    return json_response({
        "base": ctx["base"],
        "host": ctx["host"],
        "port": config.PORT,
        "lanIps": _lan_ips(),
        "store": settings.public(),
        "tables": tables.list_tables(),
        "waitUrl": f"{ctx['base']}/wait",
    })


def _lan_ips():
    import socket
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips



# ---------------------------------------------------------------- 매출·정산
@route("GET", r"/api/dashboard", perm="sales.view")
def api_dashboard(ctx):
    return json_response(stats.dashboard(ctx["query"].get("date")))


def _period_args(ctx):
    q = ctx["query"]
    return stats.resolve_period(q.get("preset", "today"), q.get("start"), q.get("end"))


@route("GET", r"/api/revenue", perm="sales.view")
def api_revenue(ctx):
    start, end = _period_args(ctx)
    data = stats.period(start, end)
    data["preset"] = ctx["query"].get("preset", "today")
    return json_response(data)


@route("GET", r"/api/revenue\.csv", perm="sales.view")
def api_revenue_csv(ctx):
    start, end = _period_args(ctx)
    body, name = stats.revenue_csv(start, end)
    return Response(body, 200, "text/csv; charset=utf-8", {
        "Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- 재고·재료
INVENTORY_PERMS = ("menu.edit", "soldout.manage")


@route("GET", r"/api/inventory", perm=INVENTORY_PERMS)
def api_inventory(ctx):
    return json_response({
        "ingredients": inventory.list_ingredients(),
        "warnings": inventory.warnings(),
        "suggestions": inventory.suggestions(),
        "logs": inventory.logs(60),
        "recipes": inventory.recipes(),
        "summary": inventory.summary(),
        "menu": [{"id": i["id"], "name": i["name"], "soldout": i["soldout"],
                  "category": i.get("category")} for i in catalog.items()],
    })


@route("POST", r"/api/inventory/ingredients", perm="menu.edit")
def api_ingredient_create(ctx):
    return json_response(inventory.create_ingredient(ctx["body"]), 201)


@route("PATCH", r"/api/inventory/ingredients/(?P<id>\d+)", perm="menu.edit")
def api_ingredient_update(ctx):
    return json_response(inventory.update_ingredient(int(ctx["match"]["id"]), ctx["body"]))


@route("DELETE", r"/api/inventory/ingredients/(?P<id>\d+)", perm="menu.edit")
def api_ingredient_delete(ctx):
    inventory.delete_ingredient(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("POST", r"/api/inventory/ingredients/(?P<id>\d+)/in", perm="menu.edit")
def api_ingredient_in(ctx):
    b = ctx["body"]
    return json_response(inventory.stock_in(int(ctx["match"]["id"]), b.get("qty"), b.get("memo", "")))


@route("POST", r"/api/inventory/ingredients/(?P<id>\d+)/adjust", perm="menu.edit")
def api_ingredient_adjust(ctx):
    b = ctx["body"]
    return json_response(inventory.adjust(int(ctx["match"]["id"]), b.get("stock"), b.get("memo", "")))


@route("GET", r"/api/inventory/logs", perm=INVENTORY_PERMS)
def api_ingredient_logs(ctx):
    q = ctx["query"]
    iid = int(q["ingredientId"]) if str(q.get("ingredientId") or "").isdigit() else None
    return json_response({"logs": inventory.logs(int(q.get("limit", 100) or 100), iid)})


@route("GET", r"/api/inventory/recipes", perm=INVENTORY_PERMS)
def api_recipes(ctx):
    q = ctx["query"]
    iid = int(q["itemId"]) if str(q.get("itemId") or "").isdigit() else None
    return json_response({"recipes": inventory.recipes(iid)})


@route("POST", r"/api/inventory/recipes", perm="menu.edit")
def api_recipe_save(ctx):
    b = ctx["body"]
    return json_response({"recipes": inventory.set_recipe(b.get("menuItemId"), b.get("lines") or [])})


@route("POST", r"/api/inventory/suggestions/(?P<id>\d+)/soldout", perm=("soldout.manage", "menu.edit"))
def api_suggestion_soldout(ctx):
    return json_response(catalog.set_soldout(int(ctx["match"]["id"]), True))


# ---------------------------------------------------------------- 예약
@route("GET", r"/api/reservations", perm="order.manage")
def api_reservations(ctx):
    q = ctx["query"]
    return json_response({
        "reservations": reservations.list_reservations(q.get("date"), q.get("month"), q.get("status")),
        "calendar": reservations.calendar(q.get("month")),
        "today": reservations.today(),
        "upcoming": reservations.upcoming(7),
        "tables": tables.list_tables(include_inactive=False),
        "statuses": reservations.STATUSES,
    })


@route("GET", r"/api/reservations/summary", perm="order.manage")
def api_reservations_today(ctx):
    return json_response(reservations.today())


@route("POST", r"/api/reservations", perm="order.manage")
def api_reservation_create(ctx):
    b = ctx["body"]
    data = reservations.create(
        b.get("date"), b.get("time"), b.get("party"), b.get("name"), b.get("phone"),
        b.get("memo", ""), consent=True, table_id=b.get("tableId"),
        status=b.get("status") or "CONFIRMED", public=False)
    return json_response(data, 201)


@route("POST", r"/api/reservations/(?P<id>\d+)/status", perm="order.manage")
def api_reservation_status(ctx):
    return json_response(reservations.set_status(int(ctx["match"]["id"]),
                                                 ctx["body"].get("status", "")))


@route("POST", r"/api/reservations/(?P<id>\d+)/table", perm="order.manage")
def api_reservation_table(ctx):
    return json_response(reservations.assign_table(int(ctx["match"]["id"]),
                                                   ctx["body"].get("tableId")))


@route("POST", r"/api/reservations/public")
def api_reservation_public(ctx):
    b = ctx["body"]
    data = reservations.create(
        b.get("date"), b.get("time"), b.get("party"), b.get("name"), b.get("phone"),
        b.get("memo", ""), consent=b.get("consent"), public=True)
    data["store"] = settings.public()
    return json_response(data, 201)


@route("GET", r"/api/reservations/t/(?P<token>[A-Za-z0-9_-]+)")
def api_reservation_token(ctx):
    data = reservations.by_token(ctx["match"]["token"])
    return json_response({"reservation": data, "store": settings.public()})


# ---------------------------------------------------------------- 리뷰
REVIEW_PERMS = ("customer.view", "settings.edit")


@route("POST", r"/api/reviews")
def api_review_create(ctx):
    b = ctx["body"]
    order = orders.get(b.get("orderId"))       # 주문으로 매장을 찾아 그 매장에서 저장한다
    with stores.use(order.get("storeId") or 1):
        data = reviews.create(order["id"], b.get("rating"), b.get("comment", ""))
        return json_response(data, 201)


@route("GET", r"/api/reviews/order/(?P<id>\d+)")
def api_review_for_order(ctx):
    """손님 화면: 이 주문에 리뷰를 남겼는지, 남길 수 있는지."""
    order = orders.get(int(ctx["match"]["id"]))
    review = reviews.for_order(order["id"])
    can = (order["status"] in ("DONE", "SERVED") or order["paymentStatus"] == "PAID")         and order["status"] != "CANCELED"
    return json_response({"review": review, "canReview": bool(can and not review)})


@route("GET", r"/api/reviews", perm=REVIEW_PERMS)
def api_reviews(ctx):
    q = ctx["query"]
    return json_response({
        "reviews": reviews.list_reviews(int(q.get("limit", 200) or 200)),
        "summary": reviews.summary(7),
    })


@route("GET", r"/api/reviews/summary", perm=REVIEW_PERMS)
def api_reviews_summary(ctx):
    return json_response(reviews.summary(int(ctx["query"].get("days", 7) or 7)))


@route("POST", r"/api/reviews/(?P<id>\d+)/reply", perm=REVIEW_PERMS)
def api_review_reply(ctx):
    return json_response(reviews.reply(int(ctx["match"]["id"]), ctx["body"].get("reply", "")))


@route("POST", r"/api/reviews/(?P<id>\d+)/hidden", perm=REVIEW_PERMS)
def api_review_hidden(ctx):
    return json_response(reviews.set_hidden(int(ctx["match"]["id"]),
                                            bool(ctx["body"].get("hidden", True))))


# ---------------------------------------------------------------- 매장(다점포)
@route("GET", r"/api/stores", login=True)
def api_stores(ctx):
    return json_response({"stores": stores.list_stores(),
                          "current": stores.current(),
                          "canSwitch": ctx["user"]["role"] == "admin"})


@route("POST", r"/api/stores", perm="settings.edit")
def api_store_create(ctx):
    b = ctx["body"]
    data = stores.create(b.get("name"), b.get("tables", 8), copy_from=b.get("copyFrom"))
    return json_response(data, 201)


@route("PATCH", r"/api/stores/(?P<id>\d+)", perm="settings.edit")
def api_store_update(ctx):
    return json_response(stores.update(int(ctx["match"]["id"]), ctx["body"]))


@route("POST", r"/api/stores/switch", login=True)
def api_store_switch(ctx):
    user = auth.switch_store(ctx["user"], ctx["token"], ctx["body"].get("storeId"))
    with stores.use(user["storeId"]):
        return json_response(_session_data(user))


@route("GET", r"/api/stores/comparison", perm="sales.view")
def api_store_comparison(ctx):
    return json_response(stores.comparison(ctx["query"].get("date")))


@route("GET", r"/api/stores/summary", perm="sales.view")
def api_store_summary(ctx):
    """모든 매장의 오늘·이번 달·누적 매출 합계와 매장별 비중."""
    return json_response(stores.summary(ctx["query"].get("date")))


@route("GET", r"/api/stores/menu", perm="settings.edit")
def api_store_menu(ctx):
    """복사할 원본 매장의 메뉴 목록."""
    sid = ctx["query"].get("store") or ctx["query"].get("storeId") or stores.current()
    return json_response(stores.store_menu(sid))


@route("POST", r"/api/stores/copy-menu", perm="settings.edit")
def api_store_copy_menu(ctx):
    b = ctx["body"]
    return json_response(stores.copy_menu(b.get("fromStore"), b.get("toStore"),
                                          b.get("itemIds"), b.get("onDuplicate")), 201)


@route("GET", r"/api/stores/staff", perm="settings.edit")
def api_store_staff(ctx):
    return json_response(stores.all_staff())


@route("POST", r"/api/stores/transfer-staff", perm="settings.edit")
def api_store_transfer_staff(ctx):
    b = ctx["body"]
    return json_response(stores.transfer_staff(b.get("staffId"), b.get("toStore"),
                                               actor=ctx["user"], note=b.get("note")), 201)


@route("GET", r"/api/stores/transfers", perm="settings.edit")
def api_store_transfers(ctx):
    q = ctx["query"].get("staff")
    return json_response(stores.transfers(int(q) if str(q or "").isdigit() else None))


# ---------------------------------------------------------------- 직원 권한·스케줄·급여
@route("GET", r"/api/staff/permissions", perm="staff.manage")
def api_staff_permissions(ctx):
    return json_response({
        "catalog": [{"code": c, "label": l, "desc": d} for c, l, d in config.PERMISSIONS],
        "roles": [{"code": r, "label": config.ROLE_LABELS[r], "hint": config.ROLE_HINTS.get(r, ""),
                   "permissions": config.ROLE_PERMISSIONS.get(r, [])} for r in config.ROLE_ORDER],
        "partRole": config.PART_TIME_ROLE,
    })


@route("POST", r"/api/staff/(?P<id>\d+)/reset-password", perm="staff.manage")
def api_staff_reset_password(ctx):
    target = staff.get(int(ctx["match"]["id"]))
    if target["role"] == "admin" and ctx["user"]["role"] != "admin":
        return json_response({"error": "관리자 계정의 비밀번호는 관리자만 초기화할 수 있습니다"}, 403)
    temp = staff.reset_password(int(ctx["match"]["id"]))
    return json_response({"temporaryPassword": temp,
                          "notice": "직원에게 알려 주세요. 첫 로그인 뒤 본인이 바꾸는 것을 권합니다."})


@route("GET", r"/api/schedule", perm="staff.manage")
def api_schedule(ctx):
    q = ctx["query"]
    if q.get("month"):
        return json_response(staff.schedule_month(q.get("month")))
    return json_response(staff.schedule_week(q.get("week")))


@route("POST", r"/api/schedule", perm="staff.manage")
def api_schedule_save(ctx):
    b = ctx["body"]
    return json_response(staff.set_schedule(b.get("staffId"), b.get("date"), b.get("start"),
                                            b.get("end"), b.get("memo", "")), 201)


@route("DELETE", r"/api/schedule/(?P<id>\d+)", perm="staff.manage")
def api_schedule_delete(ctx):
    staff.delete_schedule(int(ctx["match"]["id"]))
    return json_response({"ok": True})


@route("GET", r"/api/payroll", perm="staff.manage")
def api_payroll(ctx):
    return json_response(staff.payroll(ctx["query"].get("month")))


@route("GET", r"/api/payroll\.csv", perm="staff.manage")
def api_payroll_csv(ctx):
    body, month = staff.payroll_csv(ctx["query"].get("month"))
    return Response(body, 200, "text/csv; charset=utf-8", {
        "Content-Disposition": f'attachment; filename="payroll-{month}.csv"'})


# ---------------------------------------------------------------- 디스패치

def handle(method, path, query, body, base, host, user=None, token=None, ip="", ua="", cookies=""):
    # 지금 일하는 매장: 로그인 사용자는 세션의 매장, 손님은 ?store= 또는 기본 매장(1)
    sid = (user or {}).get("storeId")
    if not sid:
        raw = (query or {}).get("store")
        sid = int(raw) if str(raw or "").isdigit() else 1
    with stores.use(sid):
        return _dispatch(method, path, query, body, base, host, user, token, ip, ua, cookies)


def _dispatch(method, path, query, body, base, host, user, token, ip, ua, cookies=""):
    for m, rx, fn, guard in ROUTES:
        if m != method:
            continue
        mm = rx.match(path)
        if not mm:
            continue
        roles, perm, login_only = guard["roles"], guard["perm"], guard["login"]
        if perm is not None or login_only or roles is not None:
            if not user:
                return json_response({"error": "로그인이 필요합니다", "loginRequired": True}, 401)
        if perm is not None:
            codes = perm if isinstance(perm, (list, tuple, set)) else [perm]
            if not any(auth.has_perm(user, c) for c in codes):
                return json_response({"error": "이 기능을 쓸 권한이 없습니다",
                                      "neededPermissions": list(codes)}, 403)
        if roles is not None and user["role"] not in roles:
            return json_response({"error": "이 기능을 쓸 권한이 없습니다"}, 403)
        ctx = {"match": mm.groupdict(), "query": query, "body": body or {},
               "base": base, "host": host, "user": user, "token": token, "ip": ip, "ua": ua,
               "cookies": cookies}
        try:
            return fn(ctx)
        except auth.AuthError as e:
            return json_response({"error": str(e)}, e.status)
        except ValueError as e:
            return json_response({"error": str(e)}, 400)
        except LookupError as e:
            return json_response({"error": str(e)}, 404)
        except Exception as e:  # 예상하지 못한 오류도 화면에 이유를 보여 준다
            import traceback
            traceback.print_exc()
            return json_response({"error": f"서버 오류: {e}"}, 500)
    return json_response({"error": "없는 주소입니다"}, 404)
