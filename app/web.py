"""정적 화면 서빙.

public/ 아래의 HTML·CSS·JS·사진을 그대로 보낸다.
화면 주소 ↔ 파일 대응과, 화면별로 '로그인·역할이 필요한지'만 담당한다.

화면 권한
- 공개: 고객 주문(`/t/<코드>`), 웨이팅 접수/개인 링크/보드(`/wait`, `/wait/t/<토큰>`, `/wait/board`),
        로그인·가입(`/login`, `/signup`), 시작 화면(`/`), 정적 파일
- 사장님·카운터: `/admin`, `/customers`, `/wait/admin`
- 사장님·주방: `/kitchen`
- 사장님만: `/menu`, `/qr`, `/staff`, `/tables`, `/settings`
"""
import mimetypes
import os
import re

from . import config

PAGES = {
    "": "index.html",
    "/": "index.html",
    # 공개 서비스 포털
    "/features": "features.html",
    "/places": "places.html",
    "/pricing": "pricing.html",
    "/contact": "contact.html",
    "/board": "board.html",
    "/order": "order.html",
    "/online": "online.html",
    "/login": "login.html",
    "/signup": "signup.html",
    "/admin": "admin.html",
    "/kitchen": "kitchen.html",
    "/menu": "menu.html",
    "/customers": "customers.html",
    "/qr": "qr.html",
    "/staff": "staff.html",
    "/tables": "tables.html",
    "/settings": "settings.html",
    "/wait": "wait.html",
    "/wait/board": "wait-board.html",
    "/wait/admin": "wait-admin.html",
    "/print": "print.html",
    "/privacy": "privacy.html",
    "/revenue": "revenue.html",
    "/inventory": "inventory.html",
    "/reservations": "reservations.html",
    "/reviews": "reviews.html",
    "/stores": "stores.html",
    "/community": "community.html",
    "/account": "account.html",
    "/reserve": "reserve.html",
}

DYNAMIC = [
    (re.compile(r"^/t/[A-Za-z0-9_-]+$"), "customer.html"),
    (re.compile(r"^/wait/t/[A-Za-z0-9_-]+$"), "wait.html"),
]

# 화면 접근은 '권한 키'로 검사한다(역할 5종 + 직원별 예외). 빈 튜플()은 로그인만 필요.
PERMS = {
    "/admin": ("order.manage",),
    "/customers": ("customer.view",),
    "/wait/admin": ("order.manage",),
    "/print": ("settings.edit",),
    "/kitchen": ("kitchen.view",),
    "/menu": ("menu.edit", "price.edit", "soldout.manage"),
    "/qr": ("settings.edit",),
    "/staff": ("staff.manage",),
    "/tables": ("settings.edit",),
    "/settings": ("settings.edit",),
    "/revenue": ("sales.view",),
    "/inventory": ("menu.edit", "soldout.manage"),
    "/reservations": ("order.manage",),
    "/reviews": ("customer.view", "settings.edit"),
    "/stores": ("settings.edit",),
    "/community": ("settings.edit", "order.manage"),
    "/account": (),
}
GUEST_ONLY = ("/login", "/signup")

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


class NotFound(Exception):
    pass


def required_perms(path):
    """이 화면에 필요한 권한 키 목록(하나라도 있으면 통과). 공개 화면이면 None, 로그인만이면 ()."""
    return PERMS.get(path)


def required_roles(path):  # 옛 이름(다른 곳에서 부를 수 있어 남겨 둔다)
    return required_perms(path)


def guest_only(path):
    return path in GUEST_ONLY


def page_file(path):
    if path in PAGES:
        return PAGES[path]
    for rx, name in DYNAMIC:
        if rx.match(path):
            return name
    return None


def _safe_join(rel):
    path = os.path.normpath(os.path.join(config.PUBLIC_DIR, rel.lstrip("/")))
    if not path.startswith(config.PUBLIC_DIR):
        raise NotFound("잘못된 경로")
    return path


def resolve(path):
    """요청 경로 → (파일 경로, content-type). 없으면 NotFound."""
    page = page_file(path)
    if page:
        file_path = _safe_join(page)
    else:
        file_path = _safe_join(path)
    if not os.path.isfile(file_path):
        raise NotFound(path)
    ext = os.path.splitext(file_path)[1].lower()
    ctype = TYPES.get(ext) or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return file_path, ctype


def read_file(file_path):
    with open(file_path, "rb") as f:
        return f.read()
