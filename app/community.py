"""로컬 커뮤니티 모듈.

책임: 매장이 동네 상권·이웃 매장 소식, 단골 공지, 동네 이벤트, 공동 프로모션 글을
올리고 손님 화면에 보여 줄지 정한다.

- 글은 매장(store_id) 또는 같은 사업자 그룹(group_id)에 붙는다.
  그룹 글은 그룹에 속한 모든 매장의 손님 화면에 함께 보인다.
- 매장 설정의 로컬 커뮤니티가 꺼져 있으면 손님 화면에는 아무 글도 나가지 않는다.
- 다른 사업자의 글은 목록에 섞이지 않는다(store/group 소유로만 찾는다).
"""
from . import settings, store, stores

KINDS = {"neighbor": "동네 소식", "notice": "단골 공지",
         "event": "동네 이벤트", "promo": "공동 프로모션"}


def _kind(value):
    kind = (value or "neighbor").strip()
    if kind not in KINDS:
        raise ValueError("글 종류는 동네 소식·단골 공지·동네 이벤트·공동 프로모션 중에서 골라 주세요")
    return kind


def _row(r, store_names=None):
    return {
        "id": r["id"], "kind": r["kind"], "kindLabel": KINDS.get(r["kind"], r["kind"]),
        "title": r["title"], "body": r["body"] or "", "author": r["author"] or "",
        "visible": bool(r["visible"]), "pinned": bool(r["pinned"]),
        "storeId": r["store_id"], "storeName": (store_names or {}).get(r["store_id"], ""),
        "groupId": r["group_id"] or 0, "createdAt": r["created_at"],
    }


def _store_names(conn, ids):
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, name FROM stores WHERE id IN (%s)" % ",".join("?" * len(ids)),
        list(ids)).fetchall()
    return {r["id"]: r["name"] for r in rows}


def list_posts(include_hidden=False):
    """사장님 화면: 지금 매장 + 그 매장의 그룹 글."""
    sid = stores.current()
    group_id = stores.get(sid).get("groupId") or 0
    sql = "SELECT * FROM community_posts WHERE (store_id=?"
    params = [sid]
    if group_id:
        sql += " OR group_id=?"
        params.append(group_id)
    sql += ")"
    if not include_hidden:
        sql += " AND visible=1"
    sql += " ORDER BY pinned DESC, id DESC LIMIT 100"
    with store.read() as conn:
        rows = conn.execute(sql, params).fetchall()
        names = _store_names(conn, {r["store_id"] for r in rows})
    conf = settings.community_conf()
    return {"posts": [_row(r, names) for r in rows], "kinds": [
                {"code": k, "label": v} for k, v in KINDS.items()],
            "config": conf, "groupId": group_id}


def create(data):
    data = data or {}
    conf = settings.community_conf()
    if not conf.get("enabled"):
        raise ValueError("로컬 커뮤니티를 먼저 켜 주세요(설정 → 로컬 커뮤니티)")
    title = (data.get("title") or "").strip()
    if len(title) < 2:
        raise ValueError("제목을 2자 이상 넣어 주세요")
    body = (data.get("body") or "").strip()
    if len(body) < 2:
        raise ValueError("내용을 2자 이상 넣어 주세요")
    sid = stores.current()
    scope = (data.get("scope") or "store").strip()
    group_id = 0
    if scope == "group":
        group_id = stores.get(sid).get("groupId") or 0
        if not group_id:
            raise ValueError("이 매장은 그룹에 속해 있지 않습니다. 매장 관리에서 그룹을 먼저 지어 주세요")
        if not conf.get("jointPromo"):
            raise ValueError("그룹 공동 프로모션 글쓰기가 꺼져 있습니다(설정 → 로컬 커뮤니티)")
    ts = store.now()
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO community_posts(store_id, group_id, kind, title, body, author, visible,"
            " pinned, created_at, updated_at) VALUES(?,?,?,?,?,?,1,?,?,?)",
            (sid, group_id, _kind(data.get("kind")), title[:80], body[:2000],
             (data.get("author") or settings.public()["name"]).strip()[:40],
             1 if data.get("pinned") else 0, ts, ts))
        store.bump(conn)
        pid = cur.lastrowid
    return get(pid)


def get(post_id, include_group=True):
    sid = stores.current()
    group_id = stores.get(sid).get("groupId") or 0
    with store.read() as conn:
        r = conn.execute("SELECT * FROM community_posts WHERE id=?", (int(post_id),)).fetchone()
        if not r:
            raise LookupError("글을 찾을 수 없습니다")
        if not (r["store_id"] == sid or (include_group and group_id and r["group_id"] == group_id)):
            raise LookupError("글을 찾을 수 없습니다")
        names = _store_names(conn, {r["store_id"]})
    return _row(r, names)


def update(post_id, data):
    post = get(post_id)
    data = data or {}
    sets, params = [], []
    if "title" in data:
        title = (data.get("title") or "").strip()
        if len(title) < 2:
            raise ValueError("제목을 2자 이상 넣어 주세요")
        sets.append("title=?")
        params.append(title[:80])
    if "body" in data:
        body = (data.get("body") or "").strip()
        if len(body) < 2:
            raise ValueError("내용을 2자 이상 넣어 주세요")
        sets.append("body=?")
        params.append(body[:2000])
    if "kind" in data:
        sets.append("kind=?")
        params.append(_kind(data.get("kind")))
    for key in ("visible", "pinned"):
        if key in data:
            sets.append(f"{key}=?")
            params.append(1 if data.get(key) else 0)
    if not sets:
        return post
    sets.append("updated_at=?")
    params.append(store.now())
    with store.tx() as conn:
        conn.execute(f"UPDATE community_posts SET {','.join(sets)} WHERE id=?", (*params, post["id"]))
        store.bump(conn)
    return get(post_id)


def delete(post_id):
    post = get(post_id)
    with store.tx() as conn:
        conn.execute("DELETE FROM community_posts WHERE id=? AND store_id=?",
                     (post["id"], stores.current()))
        store.bump(conn)
    return {"deleted": post["id"]}


def public(store_id):
    """손님 화면. 커뮤니티를 켜고 '손님에게 보이기'가 켜져 있을 때만 글을 준다.

    매장 id 로만 찾으므로 다른 사업자 매장의 글은 섞이지 않는다.
    """
    with stores.use(store_id):
        conf = settings.community_conf()
        if not conf.get("enabled") or not conf.get("showToCustomers"):
            return {"enabled": False, "posts": [], "intro": ""}
        group_id = stores.get(store_id).get("groupId") or 0
        sql = "SELECT * FROM community_posts WHERE visible=1 AND (store_id=?"
        params = [store_id]
        if group_id:
            sql += " OR group_id=?"
            params.append(group_id)
        sql += ") ORDER BY pinned DESC, id DESC LIMIT 20"
        with store.read() as conn:
            rows = conn.execute(sql, params).fetchall()
            names = _store_names(conn, {r["store_id"] for r in rows})
        return {"enabled": True, "intro": conf.get("intro", ""),
                "neighborhood": conf.get("neighborhood", ""),
                "posts": [_row(r, names) for r in rows],
                "kinds": [{"code": k, "label": v} for k, v in KINDS.items()]}


def summary():
    """사장님 화면 요약: 글 수·종류별 수·공개 여부."""
    data = list_posts(include_hidden=True)
    counts = {}
    for p in data["posts"]:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
    return {"total": len(data["posts"]), "byKind": counts,
            "enabled": data["config"]["enabled"],
            "visibleToCustomers": data["config"]["showToCustomers"]}
