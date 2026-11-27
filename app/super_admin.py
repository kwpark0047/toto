"""최고관리자(플랫폼 운영자) — 권한 확인과 전체 현황 대시보드.

- 최고관리자는 코드에 고정된 이메일(`kwpark0047@gmail.com`)을 가진
  **사업자(admin) 계정**만 된다. 직원 계정·일반 사업자 계정은 최고관리자가 될 수 없다.
- 최고관리자 플래그(`staff.is_super_admin`)는 화면에서 직접 켤 수 없고, 아래 세 가지
  경로로만 켜진다.
    1) 구글 소셜 로그인에서 확인된 이메일(email_verified)이 최고관리자 이메일일 때
    2) 운영자가 환경변수 SUPER_ADMIN_EMAILS 로 지정한 이메일일 때
    3) 코드에 고정된 이메일을 배포의 원래(첫) 사업자 계정이 직접 등록할 때
  (3)을 '원래 계정'으로 제한하는 이유: 아무나 회원가입 화면에 그 이메일을 적어 넣고
  전체 사업자의 데이터를 보는 일을 막기 위해서다.
- 최고관리자여도 **읽기**가 기본이고, 바꿀 수 있는 것은 매장 공개 여부와
  로컬 커뮤니티 글의 공개/숨김뿐이다. 매장 정보·주문·회원·매출은 건드리지 않는다.
- 모든 변경은 super_admin_log 에 남긴다(누가·언제·무엇을).
"""
from . import config, store

TYPE_LABELS = {"account": "사업자 계정", "store": "매장", "group": "매장 그룹"}
GROUP_KIND_LABELS = {"brand": "브랜드", "region": "지역", "direct": "직영", "franchise": "가맹"}


# ============================================================================
# 권한
# ============================================================================

def is_super(user):
    """이 로그인 사용자가 최고관리자인가.

    저장된 플래그와 이메일이 **모두** 맞아야 한다(플래그만·이메일만으로는 안 된다).
    """
    if not user or user.get("role") != "admin":
        return False
    if not user.get("isSuperAdmin"):
        return False
    return config.is_super_admin_email(user.get("email"))


def require(user):
    from . import auth
    if not user:
        raise auth.AuthError("로그인이 필요합니다")
    if not is_super(user):
        raise auth.ForbiddenError("최고관리자만 볼 수 있습니다")
    return True


def original_account_id():
    """이 배포의 원래 사업자 계정(첫 매장 id=1 의 주인). 없으면 0."""
    with store.read() as conn:
        row = conn.execute("SELECT owner_id FROM stores WHERE id=1").fetchone()
    return (row["owner_id"] if row else 0) or 0


def claim_allowed(email, account_id=None, verified=False):
    """이 이메일로 최고관리자 권한을 줄 수 있는가.

    verified=True 는 구글 등 제공자가 이메일 소유를 확인해 준 경우다.
    """
    email = (email or "").strip().lower()
    if not config.is_super_admin_email(email):
        return False
    if verified:
        return True
    # 운영자가 환경변수로 '추가' 지정한 이메일은 그 자체로 신뢰한다(운영자만 설정할 수 있다).
    # 코드 고정 이메일은 여기서 빼 둔다 — 환경변수에 같이 적혀 있어도 아무나 선점하지 못하게.
    if email != config.SUPER_ADMIN_EMAIL.lower() and email in config.operator_super_admin_emails():
        return True
    # 코드에 고정된 이메일은 이 배포의 원래 사업자 계정에서만 인정한다.
    return bool(account_id) and int(account_id) == original_account_id()


def _granted(row, verified=False):
    if not row or row["role"] != "admin":
        return False
    return claim_allowed(row["email"] if "email" in row.keys() else "",
                         row["account_id"] if "account_id" in row.keys() else 0,
                         verified=verified)


def ensure_flag(staff_id):
    """저장된 이메일·계정으로 최고관리자 플래그를 맞춘다. 바뀌면 True."""
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id=?", (int(staff_id),)).fetchone()
    if not row:
        return False
    want = 1 if _granted(row) else 0
    have = int(row["is_super_admin"] or 0) if "is_super_admin" in row.keys() else 0
    if want == have:
        return False
    with store.tx() as conn:
        conn.execute("UPDATE staff SET is_super_admin=?, updated_at=? WHERE id=?",
                     (want, store.now(), int(staff_id)))
    return True


def grant_verified_email(staff_id, email, verified=False):
    """소셜 로그인 프로필의 이메일을 계정에 반영하고, 자격이 되면 플래그를 켠다.

    구글처럼 제공자가 이메일을 확인해 준 경우(verified)는 어느 계정이든 인정한다.
    확인되지 않은 이메일은 원래 계정 규칙(claim_allowed)을 따른다.
    """
    email = (email or "").strip().lower()[:120]
    if "@" not in email:
        return False
    with store.read() as conn:
        row = conn.execute("SELECT * FROM staff WHERE id=?", (int(staff_id),)).fetchone()
        if not row:
            return False
        taken = conn.execute("SELECT id FROM staff WHERE lower(email)=? AND id<>?",
                             (email, int(staff_id))).fetchone()
    if taken:
        # 다른 계정이 이미 쓰는 이메일이면 덮어쓰지 않는다(계정 탈취 방지)
        return False
    account_id = (row["account_id"] if "account_id" in row.keys() else 0) or 0
    want = 1 if (row["role"] == "admin" and claim_allowed(email, account_id, verified)) else 0
    have = int(row["is_super_admin"] or 0) if "is_super_admin" in row.keys() else 0
    old_email = (row["email"] if "email" in row.keys() else "") or ""
    if want == have and email == old_email:
        return False
    with store.tx() as conn:
        conn.execute("UPDATE staff SET email=?, is_super_admin=?, updated_at=? WHERE id=?",
                     (email, want, store.now(), int(staff_id)))
    return bool(want)


def validate_email(email):
    """이메일 형식 검사(빈 값은 허용). 소문자로 돌려준다."""
    email = (email or "").strip().lower()
    if not email:
        return ""
    local, _, domain = email.partition("@")
    if (len(email) > 120 or not local or "@" in domain or " " in email
            or "." not in domain or domain.startswith(".") or domain.endswith(".")):
        raise ValueError("이메일 주소를 다시 확인해 주세요")
    return email


def set_account_email(user, email):
    """내 계정에 이메일을 등록한다. 최고관리자 자격이 되면 플래그도 함께 켠다.

    - 이메일을 바꿀 수 있는 것은 사업자(admin) 계정뿐이다.
    - 최고관리자 이메일은 자격이 있는 계정만 쓸 수 있다(먼저 선점해 잠그는 것 방지).
    """
    from . import auth
    if not user:
        raise auth.AuthError("로그인이 필요합니다")
    if user.get("role") != "admin":
        raise auth.ForbiddenError("이메일은 사업자(관리자) 계정에서만 등록할 수 있습니다")
    email = validate_email(email)
    account_id = user.get("accountId") or 0
    if email and config.is_super_admin_email(email) and not claim_allowed(email, account_id):
        raise ValueError("이 이메일은 이 배포의 최고관리자 계정에서만 등록할 수 있습니다")
    with store.read() as conn:
        taken = conn.execute("SELECT id FROM staff WHERE lower(email)=? AND id<>?",
                             (email, user["id"])).fetchone() if email else None
    if taken:
        raise ValueError("다른 계정이 이미 쓰는 이메일입니다")
    want = 1 if (email and claim_allowed(email, account_id)) else 0
    with store.tx() as conn:
        conn.execute("UPDATE staff SET email=?, is_super_admin=?, updated_at=? WHERE id=?",
                     (email, want, store.now(), user["id"]))
        store.bump(conn)
    return {"email": email, "isSuperAdmin": bool(want)}


# ============================================================================
# 대시보드 — 플랫폼 전체 집계
# ============================================================================

def _money(row, key, default=0):
    try:
        return int(row[key] or default)
    except (TypeError, IndexError, ValueError):
        return default


def overview(date=None):
    """플랫폼 전체 KPI. 매장·사업자 구분 없이 모든 데이터를 센다(읽기 전용)."""
    date = date or store.today()
    today_start = date + " 00:00:00"
    today_end = date + " 24:00:00"
    with store.read() as conn:
        acc = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(active),0) a,"
            " COALESCE(SUM(CASE WHEN is_super_admin=1 THEN 1 ELSE 0 END),0) s"
            " FROM staff WHERE role='admin'").fetchone()
        st = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(active),0) a, COALESCE(SUM(listed),0) p"
            " FROM stores").fetchone()
        gr = conn.execute("SELECT COUNT(*) c FROM store_groups").fetchone()
        stf = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(active),0) a FROM staff").fetchone()
        cust = conn.execute("SELECT COUNT(*) c FROM customers").fetchone()
        menu = conn.execute("SELECT COUNT(*) c FROM menu_items").fetchone()
        tbl = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(active),0) a FROM dining_tables").fetchone()
        orders_all = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(total),0) t,"
            " COALESCE(SUM(CASE WHEN payment_status='PAID' THEN total ELSE 0 END),0) paid,"
            " COALESCE(SUM(CASE WHEN payment_status='PAID' THEN 1 ELSE 0 END),0) paid_c,"
            " COALESCE(SUM(CASE WHEN payment_status<>'PAID' AND status<>'CANCELED' THEN total ELSE 0 END),0) unpaid,"
            " COALESCE(SUM(CASE WHEN payment_status<>'PAID' AND status<>'CANCELED' THEN 1 ELSE 0 END),0) unpaid_c,"
            " COALESCE(SUM(CASE WHEN status='CANCELED' THEN 1 ELSE 0 END),0) canceled_c"
            " FROM orders").fetchone()
        orders_today = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(total),0) t,"
            " COALESCE(SUM(CASE WHEN payment_status='PAID' THEN total ELSE 0 END),0) paid"
            " FROM orders WHERE created_at>=? AND created_at<?", (today_start, today_end)).fetchone()
        month_start = date[:7] + "-01 00:00:00"
        orders_month = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(CASE WHEN payment_status='PAID' THEN total ELSE 0 END),0) paid"
            " FROM orders WHERE created_at>=? AND created_at<?", (month_start, today_end)).fetchone()
        methods = conn.execute(
            "SELECT payment_method m, COUNT(*) c, COALESCE(SUM(total),0) t FROM orders"
            " WHERE payment_status='PAID' GROUP BY payment_method").fetchall()
        visits = conn.execute("SELECT COUNT(*) c FROM visit_events").fetchone()
        visits_today = conn.execute(
            "SELECT COUNT(*) c FROM visit_events WHERE created_at>=? AND created_at<?",
            (today_start, today_end)).fetchone()
        visits_by = conn.execute(
            "SELECT via, COUNT(*) c FROM visit_events GROUP BY via").fetchall()
        visits_today_by = conn.execute(
            "SELECT via, COUNT(*) c FROM visit_events WHERE created_at>=? AND created_at<?"
            " GROUP BY via", (today_start, today_end)).fetchall()
        posts = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(visible),0) v FROM community_posts").fetchone()
        posts_today = conn.execute(
            "SELECT COUNT(*) c FROM community_posts WHERE created_at>=? AND created_at<?",
            (today_start, today_end)).fetchone()
        reviews = conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()
        recent_orders = conn.execute(
            "SELECT o.id, o.order_no, o.total, o.payment_status, o.payment_method, o.status,"
            " o.channel, o.created_at, o.store_id, s.name AS store_name"
            " FROM orders o LEFT JOIN stores s ON s.id=o.store_id"
            " ORDER BY o.id DESC LIMIT 6").fetchall()
        recent_posts = conn.execute(
            "SELECT p.id, p.title, p.kind, p.visible, p.created_at, p.store_id, s.name AS store_name"
            " FROM community_posts p LEFT JOIN stores s ON s.id=p.store_id"
            " ORDER BY p.id DESC LIMIT 5").fetchall()
        recent_log = conn.execute(
            "SELECT l.*, st.name AS staff_name FROM super_admin_log l"
            " LEFT JOIN staff st ON st.id=l.staff_id ORDER BY l.id DESC LIMIT 20").fetchall()

    by_method = []
    seen = set()
    for r in methods:
        code = r["m"] or "CASH"
        seen.add(code)
        by_method.append({"method": code,
                          "label": config.PAYMENT_METHOD_LABELS.get(code, code),
                          "count": _money(r, "c"), "amount": r["t"] or 0})
    for code, label, _d in config.PAYMENT_METHODS:
        if code not in seen:
            by_method.append({"method": code, "label": label, "count": 0, "amount": 0})

    def _by_via(rows):
        out = {"qr": 0, "nfc": 0, "direct": 0}
        for r in rows:
            out[r["via"] or "direct"] = out.get(r["via"] or "direct", 0) + _money(r, "c")
        out["total"] = sum(v for k, v in out.items() if k != "total")
        return out

    return {
        "date": date,
        "backend": store.backend(),
        "accounts": {"total": _money(acc, "c"), "active": _money(acc, "a"),
                     "inactive": _money(acc, "c") - _money(acc, "a"),
                     "superAdmins": _money(acc, "s")},
        "stores": {"total": _money(st, "c"), "active": _money(st, "a"),
                   "inactive": _money(st, "c") - _money(st, "a"),
                   "public": _money(st, "p"), "private": _money(st, "c") - _money(st, "p")},
        "groups": {"total": _money(gr, "c")},
        "staff": {"total": _money(stf, "c"), "active": _money(stf, "a")},
        "customers": {"total": _money(cust, "c")},
        "menuItems": {"total": _money(menu, "c")},
        "tables": {"total": _money(tbl, "c"), "active": _money(tbl, "a")},
        "orders": {
            "allTime": {"count": _money(orders_all, "c"), "amount": orders_all["t"] or 0,
                        "paidCount": _money(orders_all, "paid_c"), "paidAmount": orders_all["paid"] or 0,
                        "unpaidCount": _money(orders_all, "unpaid_c"),
                        "unpaidAmount": orders_all["unpaid"] or 0,
                        "canceledCount": _money(orders_all, "canceled_c")},
            "today": {"count": _money(orders_today, "c"), "amount": orders_today["t"] or 0,
                      "paidAmount": orders_today["paid"] or 0},
            "month": {"paidAmount": orders_month["paid"] or 0, "count": _money(orders_month, "c")},
        },
        "payments": {"methods": by_method,
                     "totalAmount": sum(m["amount"] for m in by_method),
                     "totalCount": sum(m["count"] for m in by_method)},
        "scans": {"total": _money(visits, "c"), "today": _money(visits_today, "c"),
                  "byVia": _by_via(visits_by), "todayByVia": _by_via(visits_today_by)},
        "community": {"total": _money(posts, "c"), "visible": _money(posts, "v"),
                      "hidden": _money(posts, "c") - _money(posts, "v"),
                      "today": _money(posts_today, "c")},
        "reviews": {"total": _money(reviews, "c")},
        "recentOrders": [_order_row(r) for r in recent_orders],
        "recentPosts": [_post_row(r) for r in recent_posts],
        "recentActions": [_log_row(r) for r in recent_log],
    }


def _order_row(r):
    return {
        "id": r["id"], "orderNo": r["order_no"], "storeId": r["store_id"],
        "storeName": r["store_name"] or "(삭제된 매장)",
        "total": r["total"] or 0, "status": r["status"], "channel": r["channel"] or "table",
        "paymentStatus": r["payment_status"], "paymentMethod": r["payment_method"],
        "paymentLabel": config.PAYMENT_METHOD_LABELS.get(r["payment_method"], r["payment_method"]),
        "statusLabel": config.STATUS_LABELS.get(r["status"], r["status"]),
        "createdAt": r["created_at"],
    }


def _post_row(r):
    return {
        "id": r["id"], "title": r["title"], "kind": r["kind"],
        "kindLabel": {"neighbor": "동네 소식", "notice": "단골 공지", "event": "동네 이벤트",
                      "promo": "공동 프로모션"}.get(r["kind"], r["kind"]),
        "author": (r["author"] if "author" in r.keys() else "") or "",
        "visible": bool(r["visible"]), "storeId": r["store_id"],
        "storeName": r["store_name"] or "(삭제된 매장)",
        "createdAt": r["created_at"],
    }


def _log_row(r):
    return {
        "id": r["id"], "staffName": (r["staff_name"] if "staff_name" in r.keys() else "") or "최고관리자",
        "action": r["action"], "target": r["target"], "detail": r["detail"],
        "createdAt": r["created_at"],
    }


# ============================================================================
# 통합 목록 — 사업자 계정 · 매장 · 그룹
# ============================================================================

def entities(q="", kind="all", state="all"):
    """플랫폼 전체 사업자 계정·매장·그룹을 한 목록으로 돌려준다(검색·필터)."""
    q = (q or "").strip().lower()
    kind = (kind or "all").strip()
    state = (state or "all").strip()
    if kind not in ("all", "account", "store", "group"):
        raise ValueError("목록 종류는 전체·계정·매장·그룹 중에서 골라 주세요")
    if state not in ("all", "public", "private", "active", "inactive", "super"):
        raise ValueError("상태 필터를 다시 골라 주세요")

    with store.read() as conn:
        admins = conn.execute(
            "SELECT id, username, name, email, is_super_admin, active, created_at, last_login_at,"
            " account_id FROM staff WHERE role='admin' ORDER BY id").fetchall()
        stores = conn.execute("SELECT * FROM stores ORDER BY id").fetchall()
        groups = conn.execute("SELECT * FROM store_groups ORDER BY id").fetchall()
        order_agg = {r["store_id"]: r for r in conn.execute(
            "SELECT store_id, COUNT(*) c, COALESCE(SUM(CASE WHEN payment_status='PAID' THEN total ELSE 0 END),0) paid,"
            " MAX(created_at) last FROM orders GROUP BY store_id").fetchall()}
        staff_agg = {r["store_id"]: r["c"] for r in conn.execute(
            "SELECT store_id, COUNT(*) c FROM staff WHERE active=1 GROUP BY store_id").fetchall()}
        table_agg = {r["store_id"]: r["c"] for r in conn.execute(
            "SELECT store_id, COUNT(*) c FROM dining_tables WHERE active=1 GROUP BY store_id").fetchall()}
        post_agg = {r["store_id"]: r["c"] for r in conn.execute(
            "SELECT store_id, COUNT(*) c FROM community_posts GROUP BY store_id").fetchall()}

    store_rows = []
    for s in stores:
        sid = s["id"]
        agg = order_agg.get(sid)
        store_rows.append({
            "type": "store", "id": sid, "name": s["name"],
            "ownerId": (s["owner_id"] if "owner_id" in s.keys() else 0) or 0,
            "groupId": (s["group_id"] if "group_id" in s.keys() else 0) or 0,
            "listed": bool(s["listed"]) if "listed" in s.keys() else False,
            "active": bool(s["active"]),
            "createdAt": s["created_at"],
            "orderCount": _money(agg, "c") if agg else 0,
            "paidTotal": (agg["paid"] if agg else 0) or 0,
            "lastOrderAt": (agg["last"] if agg else "") or "",
            "staffCount": staff_agg.get(sid, 0),
            "tableCount": table_agg.get(sid, 0),
            "postCount": post_agg.get(sid, 0),
        })
    store_by_id = {r["id"]: r for r in store_rows}
    group_name = {g["id"]: g["name"] for g in groups}
    owner_label = {}
    for a in admins:
        owner_label[a["id"]] = a["username"]
    for r in store_rows:
        r["ownerUsername"] = owner_label.get(r["ownerId"], "")
        r["groupName"] = group_name.get(r["groupId"], "")

    group_rows = []
    for g in groups:
        members = [r for r in store_rows if r["groupId"] == g["id"]]
        group_rows.append({
            "type": "group", "id": g["id"], "name": g["name"],
            "kind": g["kind"], "kindLabel": GROUP_KIND_LABELS.get(g["kind"], g["kind"]),
            "ownerId": (g["owner_id"] if "owner_id" in g.keys() else 0) or 0,
            "ownerUsername": owner_label.get((g["owner_id"] if "owner_id" in g.keys() else 0) or 0, ""),
            "storeCount": len(members), "publicCount": len([r for r in members if r["listed"]]),
            "createdAt": g["created_at"],
            "storeNames": [r["name"] for r in members],
        })

    account_rows = []
    orig = original_account_id()
    for a in admins:
        mine = [r for r in store_rows if r["ownerId"] == a["id"]]
        aid = (a["account_id"] if "account_id" in a.keys() else 0) or 0
        # 최고관리자 플래그는 화면에 그대로 보여 주되, 이메일이 최고관리자 이메일인지도 함께 본다
        account_rows.append({
            "type": "account", "id": a["id"], "username": a["username"],
            "email": (a["email"] if "email" in a.keys() else "") or "",
            "active": bool(a["active"]),
            "isSuperAdmin": bool(a["is_super_admin"] if "is_super_admin" in a.keys() else 0)
                             and config.is_super_admin_email(a["email"] if "email" in a.keys() else ""),
            "storeCount": len(mine), "publicStoreCount": len([r for r in mine if r["listed"]]),
            "storeNames": [r["name"] for r in mine],
            "orderCount": sum(r["orderCount"] for r in mine),
            "paidTotal": sum(r["paidTotal"] for r in mine),
            "createdAt": a["created_at"], "lastLoginAt": a["last_login_at"],
            "original": bool(aid) and aid == orig,
        })

    def _match(text):
        return not q or q in (text or "").lower()

    items = []
    if kind in ("all", "account"):
        for a in account_rows:
            if state == "active" and not a["active"]:
                continue
            if state == "inactive" and a["active"]:
                continue
            if state == "super" and not a["isSuperAdmin"]:
                continue
            if state in ("public", "private"):
                continue
            hay = " ".join([a["username"], a["email"]] + a["storeNames"])
            if _match(hay):
                items.append(a)
    if kind in ("all", "store"):
        for r in store_rows:
            if state == "public" and not r["listed"]:
                continue
            if state == "private" and r["listed"]:
                continue
            if state == "active" and not r["active"]:
                continue
            if state == "inactive" and r["active"]:
                continue
            if state == "super":
                continue
            if _match(" ".join([r["name"], r["ownerUsername"], r["groupName"]])):
                items.append(r)
    if kind in ("all", "group"):
        for g in group_rows:
            if state in ("public", "private", "active", "inactive", "super"):
                continue
            if _match(" ".join([g["name"], g["ownerUsername"], " ".join(g["storeNames"])])):
                items.append(g)

    return {
        "items": items,
        "counts": {"accounts": len(account_rows), "stores": len(store_rows),
                   "groups": len(group_rows), "items": len(items)},
        "totals": {
            "publicStores": len([r for r in store_rows if r["listed"]]),
            "privateStores": len([r for r in store_rows if not r["listed"]]),
            "inactiveStores": len([r for r in store_rows if not r["active"]]),
            "orders": sum(r["orderCount"] for r in store_rows),
            "paid": sum(r["paidTotal"] for r in store_rows),
        },
        "query": {"q": q, "kind": kind, "state": state},
        "typeLabels": TYPE_LABELS,
    }


# ============================================================================
# 최근 주문·커뮤니티 모니터링
# ============================================================================

def recent_orders(limit=50, q="", payment="all", limit_max=200):
    try:
        limit = max(1, min(int(limit or 50), limit_max))
    except (TypeError, ValueError):
        limit = 50
    payment = (payment or "all").strip()
    sql = ("SELECT o.id, o.order_no, o.total, o.payment_status, o.payment_method, o.status,"
           " o.channel, o.created_at, o.store_id, s.name AS store_name"
           " FROM orders o LEFT JOIN stores s ON s.id=o.store_id")
    where, params = [], []
    if payment == "paid":
        where.append("o.payment_status='PAID'")
    elif payment == "unpaid":
        where.append("o.payment_status<>'PAID'")
    elif payment != "all":
        raise ValueError("결제 필터는 전체·결제 완료·결제 전 중에서 골라 주세요")
    q = (q or "").strip()
    if q:
        where.append("(o.order_no LIKE ? OR s.name LIKE ? OR o.customer_name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY o.id DESC LIMIT ?"
    params.append(limit)
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"orders": [_order_row(r) for r in rows], "limit": limit,
            "payment": payment, "query": q}


def posts(limit=50, q="", state="all"):
    try:
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    state = (state or "all").strip()
    sql = ("SELECT p.*, s.name AS store_name, g.name AS group_name"
           " FROM community_posts p LEFT JOIN stores s ON s.id=p.store_id"
           " LEFT JOIN store_groups g ON g.id=p.group_id")
    where, params = [], []
    if state == "visible":
        where.append("p.visible=1")
    elif state == "hidden":
        where.append("p.visible=0")
    elif state != "all":
        raise ValueError("글 상태 필터는 전체·공개·숨김 중에서 골라 주세요")
    q = (q or "").strip()
    if q:
        where.append("(p.title LIKE ? OR p.body LIKE ? OR s.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.id DESC LIMIT ?"
    params.append(limit)
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        item = _post_row(r)
        item["body"] = (r["body"] or "")[:300]
        item["pinned"] = bool(r["pinned"])
        item["groupName"] = (r["group_name"] if "group_name" in r.keys() else "") or ""
        out.append(item)
    return {"posts": out, "limit": limit, "state": state, "query": q}


# ============================================================================
# 최고관리자 조치 — 매장 공개 여부 · 커뮤니티 글 공개/숨김만
# ============================================================================

def _log(conn, actor, action, target, detail):
    conn.execute(
        "INSERT INTO super_admin_log(staff_id, action, target, detail, created_at)"
        " VALUES(?,?,?,?,?)",
        ((actor or {}).get("id") or 0, action, str(target)[:60], (detail or "")[:200], store.now()))


def set_store_listed(store_id, listed, actor=None):
    """매장을 서비스 소개(동네 매장 찾기)에 공개할지 바꾼다. 다른 필드는 건드리지 않는다."""
    require(actor)
    try:
        sid = int(store_id)
    except (TypeError, ValueError):
        raise ValueError("매장을 골라 주세요")
    value = 1 if listed else 0
    with store.read() as conn:
        row = conn.execute("SELECT id, name, listed FROM stores WHERE id=?", (sid,)).fetchone()
    if not row:
        raise LookupError("매장을 찾을 수 없습니다")
    with store.tx() as conn:
        conn.execute("UPDATE stores SET listed=?, updated_at=? WHERE id=?",
                     (value, store.now(), sid))
        _log(conn, actor, "store.listed", f"store:{sid}",
             f"{row['name']} → {'공개' if value else '비공개'}")
        store.bump(conn)
    return {"store": {"id": sid, "name": row["name"], "listed": bool(value)},
            "changed": bool(row["listed"]) != bool(value)}


def set_post_visible(post_id, visible, actor=None):
    """로컬 커뮤니티 글을 손님 화면에 보일지/숨길지 바꾼다. 글 내용은 건드리지 않는다."""
    require(actor)
    try:
        pid = int(post_id)
    except (TypeError, ValueError):
        raise ValueError("글을 골라 주세요")
    value = 1 if visible else 0
    with store.read() as conn:
        row = conn.execute("SELECT id, title, visible, store_id FROM community_posts"
                           " WHERE id=?", (pid,)).fetchone()
    if not row:
        raise LookupError("글을 찾을 수 없습니다")
    with store.tx() as conn:
        conn.execute("UPDATE community_posts SET visible=?, updated_at=? WHERE id=?",
                     (value, store.now(), pid))
        _log(conn, actor, "community.visible" if value else "community.hidden",
             f"post:{pid}", f"{row['title'][:40]} → {'공개' if value else '숨김'}")
        store.bump(conn)
    return {"post": {"id": pid, "title": row["title"], "visible": bool(value),
                     "storeId": row["store_id"]},
            "changed": bool(row["visible"]) != bool(value)}
