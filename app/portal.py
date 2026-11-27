"""공개 서비스 포털 — 매장 목록·도입 문의·게시판.

고객/방문자가 로그인 없이 쓰는 공개 데이터만 다룬다.
- 매장 목록: 활성 매장의 공개 정보(이름·한 줄 소개·주소·전화·영업시간·활성 테이블 수)만.
  사업자등록번호·대표자 이름은 내보내지 않는다.
- 문의: 접수번호를 발급해 저장한다(문자·메일 발송은 하지 않는다).
- 게시판: 공지·업데이트·매장 후기 글과 댓글. 숨긴 글은 목록에서 빠진다.
"""
import re

from . import settings, store, stores, tables

BOARD_CATEGORIES = {"notice": "공지", "update": "업데이트", "review": "매장 후기"}
INQUIRY_KINDS = ("도입 문의", "데모 요청", "가맹·제휴", "기타")
COMMENT_LIMIT = 50


def _text(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _region(address):
    parts = [p for p in str(address or "").split() if p]
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else "기타"


# ---------------------------------------------------------------- 매장 목록
def public_stores():
    out = []
    regions = set()
    for s in stores.list_stores(include_inactive=False):
        if not s.get("listed"):
            # 공개 목록은 사장님이 공개를 켠 매장만 보여 준다(다른 사업자 매장 보호)
            continue
        with stores.use(s["id"]):
            info = settings.public()
            active_tables = tables.active_tables()
        region = _region(info.get("address") or s.get("address") or "")
        first_code = active_tables[0]["code"] if active_tables else "1"
        q = f"?store={s['id']}" if s["id"] != 1 else ""
        out.append({
            "id": s["id"],
            "name": info.get("name") or s["name"],
            "tagline": info.get("tagline") or s.get("tagline") or "",
            "address": info.get("address") or s.get("address") or "",
            "phone": info.get("phone") or s.get("phone") or "",
            "hours": info.get("hours") or "",
            "region": region,
            "tableCount": len(active_tables),
            "orderUrl": f"/t/{first_code}{q}",
            "onlineUrl": f"/order{q}",
            "online": info.get("channel", {}).get("mode") in ("online", "both"),
            "waitUrl": f"/wait{q}",
            "reserveUrl": f"/reserve{q}",
        })
        regions.add(region)
    return {"stores": out, "regions": sorted(regions),
            "categories": [{"code": k, "label": v} for k, v in BOARD_CATEGORIES.items()]}


# ---------------------------------------------------------------- 도입 문의
def _receipt_no():
    day = store.today().replace("-", "")
    with store.read() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM inquiries WHERE receipt_no LIKE ?",
                         (f"WT{day}-%",)).fetchone()["c"]
    while True:
        n += 1
        candidate = f"WT{day}-{n:04d}"
        with store.read() as conn:
            if not conn.execute("SELECT 1 FROM inquiries WHERE receipt_no=?",
                                (candidate,)).fetchone():
                return candidate


def create_inquiry(data):
    name = _text(data.get("name"), 40)
    phone = _text(data.get("phone"), 30)
    email = _text(data.get("email"), 120)
    store_name = _text(data.get("storeName") or data.get("store_name"), 60)
    message = str(data.get("message") or "").strip()[:2000]
    kind = data.get("kind") if data.get("kind") in INQUIRY_KINDS else INQUIRY_KINDS[0]
    consent = bool(data.get("consent"))
    if not name:
        raise ValueError("이름을 넣어 주세요")
    if not phone and not email:
        raise ValueError("연락받을 전화번호 또는 이메일을 넣어 주세요")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("이메일 형식을 확인해 주세요")
    if len(message) < 5:
        raise ValueError("문의 내용을 5자 이상 넣어 주세요")
    if not consent:
        raise ValueError("개인정보 수집·이용에 동의해 주세요")

    receipt = _receipt_no()
    ts = store.now()
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO inquiries(receipt_no, store_name, name, phone, email, kind, message,"
            " consent, status, created_at) VALUES(?,?,?,?,?,?,?,1,'NEW',?)",
            (receipt, store_name, name, phone, email, kind, message, ts))
        store.bump(conn)
    return {"receiptNo": receipt, "kind": kind, "createdAt": ts,
            "notice": "문의가 접수되었습니다. 영업일 기준 1~2일 안에 연락드립니다."}


def list_inquiries(limit=100):
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM inquiries ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return {"inquiries": [{
        "id": r["id"], "receiptNo": r["receipt_no"], "storeName": r["store_name"],
        "name": r["name"], "phone": r["phone"], "email": r["email"], "kind": r["kind"],
        "message": r["message"], "status": r["status"], "createdAt": r["created_at"],
    } for r in rows]}


# ---------------------------------------------------------------- 게시판
def list_posts(category="", limit=60):
    where, params = ["hidden=0"], []
    if category in BOARD_CATEGORIES:
        where.append("category=?")
        params.append(category)
    sql = ("SELECT p.*, (SELECT COUNT(*) FROM board_comments c"
           " WHERE c.post_id=p.id AND c.hidden=0) AS comments"
           " FROM board_posts p WHERE " + " AND ".join(where) +
           " ORDER BY p.id DESC LIMIT ?")
    params.append(int(limit))
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"categories": [{"code": k, "label": v} for k, v in BOARD_CATEGORIES.items()],
            "posts": [_post_row(r) for r in rows]}


def _post_row(r, body=False):
    data = {
        "id": r["id"], "category": r["category"],
        "categoryLabel": BOARD_CATEGORIES.get(r["category"], r["category"]),
        "title": r["title"], "author": r["author"] or "손님",
        "createdAt": r["created_at"],
        "commentCount": r["comments"] if "comments" in r.keys() else 0,
    }
    if body:
        data["body"] = r["body"]
    return data


def get_post(post_id):
    with store.read() as conn:
        row = conn.execute("SELECT * FROM board_posts WHERE id=? AND hidden=0",
                           (int(post_id),)).fetchone()
        if not row:
            raise LookupError("글을 찾을 수 없습니다")
        rows = conn.execute(
            "SELECT * FROM board_comments WHERE post_id=? AND hidden=0 ORDER BY id LIMIT ?",
            (int(post_id), COMMENT_LIMIT)).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) c FROM board_comments WHERE post_id=? AND hidden=0",
            (int(post_id),)).fetchone()["c"]
    post = _post_row(row, body=True)
    post["commentCount"] = count
    post["comments"] = [{
        "id": c["id"], "author": c["author"] or "손님", "body": c["body"],
        "createdAt": c["created_at"],
    } for c in rows]
    return {"post": post}


def create_post(data):
    title = _text(data.get("title"), 80)
    body = str(data.get("body") or "").strip()[:5000]
    author = _text(data.get("author"), 20) or "손님"
    category = data.get("category") if data.get("category") in BOARD_CATEGORIES else "review"
    if len(title) < 2:
        raise ValueError("제목을 2자 이상 넣어 주세요")
    if len(body) < 5:
        raise ValueError("내용을 5자 이상 넣어 주세요")
    ts = store.now()
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO board_posts(category, title, body, author, hidden, created_at)"
            " VALUES(?,?,?,?,0,?)", (category, title, body, author, ts))
        post_id = cur.lastrowid
        store.bump(conn)
    return get_post(post_id)


def add_comment(post_id, data):
    body = str(data.get("body") or "").strip()[:1000]
    author = _text(data.get("author"), 20) or "손님"
    if len(body) < 1:
        raise ValueError("댓글 내용을 넣어 주세요")
    with store.read() as conn:
        exists = conn.execute("SELECT 1 FROM board_posts WHERE id=? AND hidden=0",
                              (int(post_id),)).fetchone()
    if not exists:
        raise LookupError("글을 찾을 수 없습니다")
    ts = store.now()
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO board_comments(post_id, author, body, hidden, created_at)"
            " VALUES(?,?,?,0,?)", (int(post_id), author, body, ts))
        store.bump(conn)
    return get_post(post_id)
