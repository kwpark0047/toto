"""매장 설정 모듈.

책임: 매장 정보(이름·사업자 정보·영업시간·안내 문구)와 회원 등급/포인트 적립률 같은
'사장님이 직접 바꾸는 값'을 보관한다. 값은 DB(settings 테이블)에 JSON 으로 남는다.
비어 있는 값은 기본 문구로 대체하고, 빈 값 때문에 화면이나 주문이 멈추지 않는다.

저장 위치: data/mangjip.db 의 settings 테이블 (key = 'store')
실제 운영에서는 사업자등록번호 진위확인·본인인증을 외부 기관으로 확인해야 한다(시제품은 형식 검사만).
"""
import json
import re

from . import config, stores, store

KEY = "store"          # 기본 매장(1)은 기존 키를 그대로 쓴다


def _key():
    """매장별 설정 키. 1번 매장은 이전 버전과 같은 'store' 키를 쓴다."""
    sid = stores.current()
    return KEY if sid == 1 else f"{KEY}:{sid}"

DEFAULTS = {
    "storeName": config.STORE.get("name") or "맛집",
    "tagline": config.STORE.get("tagline") or "",
    "businessNo": "",      # 000-00-00000 형식만 검사 (진위확인 안 함)
    "ownerName": "",
    "address": "",
    "phone": "",
    "hours": "",           # 예: 매일 10:00~21:00 (브레이크 15:00~17:00)
    "paymentNote": "현금 결제 · 계산대에서 결제해 주세요",
    "pointsRate": config.POINTS_RATE,
    "grades": [dict(g) for g in config.MEMBER_GRADES],
    "notify": {
        "channels": {"browser": True, "sms": False, "kakao": False},
        "templates": {},
    },
    "qr": {
        "dot": "rounded", "eye": "rounded", "fg": "#1f2a44", "bg": "#fdf3e3",
        "badge": "initial", "caption": "auto", "border": 4, "badgeImage": "",
    },
    "voice": {"saveText": True},
    # 온·오프라인 운영 모드 — 기본은 지금처럼 테이블 QR(오프라인)이다.
    "channel": {
        "mode": "offline",              # offline | online | both
        "pickup": False,                 # 포장 주문 받기
        "delivery": False,               # 배달 주문 받기
        "preorder": True,                # 대기 중 미리 주문
        "pickupMin": 20,                 # 포장 준비 안내(분)
        "deliveryFee": 0,
        "onlineNote": "",
    },
    # 결제수단. 현금은 언제나 쓸 수 있고, 나머지는 사장님이 켜고 끈다.
    "payments": {
        "cash": {"enabled": True, "feeRate": 0.0, "note": "계산대에서 현금으로 결제해 주세요"},
        "transfer": {"enabled": True, "feeRate": 0.0, "note": "입금 후 입금자명을 남겨 주세요",
                     "bank": "", "accountNo": "", "holder": ""},
        "card": {"enabled": False, "feeRate": 1.5, "note": "카드 단말기에서 결제해 주세요",
                 "provider": "none"},
        "quick": {"enabled": False, "feeRate": 2.0, "note": "간편결제는 카운터에서 확인해 드립니다",
                  "provider": "none"},
    },
    "waiting": {"enabled": True, "notice": "", "maxParty": 8},
    # 고객 이벤트·쿠폰
    "events": {
        "firstVisit": {"enabled": True, "points": 500, "coupon": False},
        "revisit": {"enabled": True, "days": 7, "points": 300},
        "birthday": {"enabled": True, "points": 1000, "coupon": True},
        "timeDiscount": {"enabled": False, "start": "14:00", "end": "17:00", "percent": 10},
        "coupon": {"enabled": True, "title": "단골 감사 쿠폰", "amount": 2000,
                    "minSpend": 10000, "validDays": 30},
    },
    # 로컬 커뮤니티(동네 소식·공동 프로모션)
    "community": {
        "enabled": False, "intro": "", "showToCustomers": True,
        "neighborhood": "", "jointPromo": True,
    },
    "stand": {
        "title": "메뉴 보기 · 주문", "subtitle": "휴대폰으로 찍어 주문하세요",
        "steps": "1. 카메라로 QR 찍기|2. 메뉴 고르기|3. 장바구니로 주문",
        "nfc": "NFC 태그에 휴대폰을 대도 열립니다",
        "footer": "직원을 부르면 도와 드립니다",
        "accent": "#d9480f",
    },
}

BIZ_RE = re.compile(r"^\d{3}-\d{2}-\d{5}$")


def _row_value(raw):
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _merged(raw=""):
    """저장된 JSON + 기본값을 합진 설정 사전."""
    data = _row_value(raw)
    out = dict(DEFAULTS)
    out.update({k: v for k, v in data.items() if v is not None})
    if not isinstance(out.get("grades"), list) or not out["grades"]:
        out["grades"] = [dict(g) for g in config.MEMBER_GRADES]
    return out


def get(conn=None):
    """저장된 설정 + 기본값(지금 매장). conn 을 주면 그 연결로 읽는다(왕복 절약)."""
    sql = "SELECT value FROM settings WHERE key=?"
    if conn is not None:
        row = conn.execute(sql, (_key(),)).fetchone()
    else:
        with store.read() as c:
            row = c.execute(sql, (_key(),)).fetchone()
    return _merged(row["value"] if row else "")


def public(conn=None, merged=None):
    """고객 화면·QR·영수증에 보여 줄 값. 빈 값은 빈 문자열 그대로 두고 화면이 감춘다."""
    s = merged if merged is not None else get(conn)
    ch = s["channel"]
    pays = s["payments"]
    return {
        "name": s["storeName"],
        "tagline": s["tagline"],
        "address": s["address"],
        "phone": s["phone"],
        "hours": s["hours"],
        "paymentNote": s["paymentNote"],
        "businessNo": s["businessNo"],
        "ownerName": s["ownerName"],
        "channel": {
            "mode": ch["mode"], "pickup": bool(ch["pickup"]), "delivery": bool(ch["delivery"]),
            "preorder": bool(ch["preorder"]), "pickupMin": ch["pickupMin"],
            "deliveryFee": ch["deliveryFee"], "onlineNote": ch["onlineNote"],
        },
        # 손님에게는 수수료·PG 설정 없이 '어떻게 결제하면 되는지'만 알려 준다
        "payments": {
            code: {"enabled": bool(pays.get(code, {}).get("enabled")),
                   "note": pays.get(code, {}).get("note", ""),
                   "bank": pays.get(code, {}).get("bank", ""),
                   "accountNo": pays.get(code, {}).get("accountNo", ""),
                   "holder": pays.get(code, {}).get("holder", "")}
            for code in ("cash", "transfer", "card", "quick")
        },
        "waiting": {"enabled": bool(s["waiting"]["enabled"]), "notice": s["waiting"]["notice"],
                    "maxParty": s["waiting"]["maxParty"]},
        "community": {"enabled": bool(s["community"]["enabled"]),
                      "intro": s["community"]["intro"]},
    }


def channel():
    return get()["channel"]


def payments():
    return get()["payments"]


def waiting_conf():
    return get()["waiting"]


def events_conf():
    return get()["events"]


def community_conf():
    return get()["community"]


def online_on():
    """온라인(포장·배달·사전주문) 주문을 받는 상태인지."""
    return channel()["mode"] in ("online", "both")


def offline_on():
    """매장 테이블 주문을 받는 상태인지."""
    return channel()["mode"] in ("offline", "both")


def points_rate(conn=None, merged=None):
    try:
        value = (merged if merged is not None else get(conn))["pointsRate"]
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return config.POINTS_RATE


def grades():
    """등급 기준(높은 등급부터)."""
    out = []
    for g in get()["grades"]:
        try:
            out.append({
                "code": str(g.get("code") or "").upper(),
                "label": str(g.get("label") or g.get("code") or ""),
                "minVisits": int(g.get("minVisits") or 0),
                "minSpend": int(g.get("minSpend") or 0),
            })
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda g: (g["minVisits"], g["minSpend"]), reverse=True)
    return out or [dict(g) for g in config.MEMBER_GRADES]


def base_grade():
    return dict(config.MEMBER_BASE_GRADE)


def grade_codes():
    return [g["code"] for g in grades()]


def _norm_biz_no(value):
    digits = re.sub(r"[^0-9]", "", value or "")
    if not digits:
        return ""
    if len(digits) != 10:
        raise ValueError("사업자등록번호는 숫자 10자리(000-00-00000)로 넣어 주세요")
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def _clean_text(value, limit=200):
    return (value or "").strip()[:limit]


def save(patch):
    """넘어온 항목만 검사해서 저장한다. 없는 항목은 그대로 둔다."""
    current = get()
    data = {k: current[k] for k in DEFAULTS}
    if "storeName" in patch:
        name = _clean_text(patch.get("storeName"), 40) or DEFAULTS["storeName"]
        data["storeName"] = name
    if "tagline" in patch:
        data["tagline"] = _clean_text(patch.get("tagline"), 80)
    if "businessNo" in patch:
        data["businessNo"] = _norm_biz_no(patch.get("businessNo"))
    if "ownerName" in patch:
        data["ownerName"] = _clean_text(patch.get("ownerName"), 40)
    if "address" in patch:
        data["address"] = _clean_text(patch.get("address"), 120)
    if "phone" in patch:
        data["phone"] = _clean_text(patch.get("phone"), 30)
    if "hours" in patch:
        data["hours"] = _clean_text(patch.get("hours"), 120)
    if "paymentNote" in patch:
        data["paymentNote"] = _clean_text(patch.get("paymentNote"), 160)
    if "pointsRate" in patch:
        try:
            rate = float(patch.get("pointsRate"))
        except (TypeError, ValueError):
            raise ValueError("포인트 적립률은 숫자로 넣어 주세요 (예: 1 = 1%)")
        if not (0 <= rate <= 10):
            raise ValueError("포인트 적립률은 0~10% 사이로 넣어 주세요")
        data["pointsRate"] = round(rate, 2)
    if "grades" in patch:
        grades = _clean_grades(patch.get("grades"))
        if grades:
            data["grades"] = grades
    if "notify" in patch:
        data["notify"] = _clean_notify(patch.get("notify"))
    if "voice" in patch:
        v = patch.get("voice") or {}
        data["voice"] = {"saveText": bool(v.get("saveText", True))}
    if "qr" in patch:
        data["qr"] = _clean_qr(patch.get("qr"))
    if "stand" in patch:
        data["stand"] = _clean_stand(patch.get("stand"))
    if "channel" in patch:
        data["channel"] = _clean_channel(patch.get("channel"))
    if "payments" in patch:
        data["payments"] = _clean_payments(patch.get("payments"))
    if "waiting" in patch:
        data["waiting"] = _clean_waiting(patch.get("waiting"))
    if "events" in patch:
        data["events"] = _clean_events(patch.get("events"))
    if "community" in patch:
        data["community"] = _clean_community(patch.get("community"))

    sid = stores.current()
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_key(), json.dumps(data, ensure_ascii=False)),
        )
        # 매장 목록에 보이는 이름도 같이 맞춘다
        conn.execute("UPDATE stores SET name=?, updated_at=? WHERE id=?",
                     (data["storeName"], store.now(), sid))
        store.bump(conn)
    return get()


def _clean_grades(raw):
    if not isinstance(raw, list):
        raise ValueError("등급 기준 형식이 올바르지 않습니다")
    out = []
    for g in raw:
        if not isinstance(g, dict):
            continue
        code = str(g.get("code") or "").upper()
        if not code:
            continue
        try:
            visits = max(0, int(g.get("minVisits") or 0))
            spend = max(0, int(g.get("minSpend") or 0))
        except (TypeError, ValueError):
            raise ValueError("등급 기준(방문 횟수·누적 금액)은 숫자로 넣어 주세요")
        out.append({"code": code, "label": _clean_text(g.get("label") or code, 20),
                    "minVisits": visits, "minSpend": spend})
    if not out:
        raise ValueError("등급 기준이 비었습니다")
    # VIP 기준이 단골 기준보다 낮으면 화면이 거꾸로 보인다 → 정리해서 저장
    out.sort(key=lambda g: (g["minVisits"], g["minSpend"]), reverse=True)
    return out


def _clean_notify(raw):
    """알림 설정: 켜기/끄기 + 상황별 문구. 연결되지 않은 채널은 켤 수 없다."""
    if not isinstance(raw, dict):
        raise ValueError("알림 설정 형식이 올바르지 않습니다")
    current = get().get("notify") or {}
    channels = dict((current.get("channels") or {"browser": True, "sms": False, "kakao": False}))
    templates = dict(current.get("templates") or {})
    incoming = raw.get("channels") or {}
    unconnected = {"sms": "문자", "kakao": "카카오 알림톡"}
    for code, name in unconnected.items():
        if incoming.get(code) and not channels.get(code):
            raise ValueError(f"{name} 채널은 대행사 계정 연결이 필요합니다. 지금은 켤 수 없습니다")
    for code in ("browser", "sms", "kakao"):
        if code in incoming:
            channels[code] = bool(incoming[code])
    tpl_in = raw.get("templates") or {}
    for code in ("soon", "called", "seated"):
        if code in tpl_in:
            templates[code] = _clean_text(tpl_in.get(code), 120)
    return {"channels": channels, "templates": templates}


def _clean_qr(raw):
    from . import qrdesign
    if not isinstance(raw, dict):
        raise ValueError("QR 디자인 설정 형식이 올바르지 않습니다")
    merged = dict(DEFAULTS["qr"])
    merged.update({k: v for k, v in get().get("qr", {}).items() if v is not None})
    merged.update({k: v for k, v in raw.items() if v is not None})
    try:
        norm = qrdesign.normalize(merged)
    except ValueError as e:
        raise ValueError(str(e))
    keep = dict(DEFAULTS["qr"])
    keep.update(norm)
    return keep


def _clean_stand(raw):
    if not isinstance(raw, dict):
        raise ValueError("인쇄물 설정 형식이 올바르지 않습니다")
    out = dict(DEFAULTS["stand"])
    out.update({k: v for k, v in get().get("stand", {}).items() if v is not None})
    for key in ("title", "subtitle", "steps", "nfc", "footer"):
        if key in raw:
            out[key] = _clean_text(raw.get(key), 120) or DEFAULTS["stand"][key]
    if "accent" in raw:
        from . import qrdesign
        out["accent"] = qrdesign._hex(raw.get("accent"), DEFAULTS["stand"]["accent"])
    return out


def _int_in(value, label, low=0, high=1000000):
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{label}은(는) 숫자로 넣어 주세요")
    if not (low <= n <= high):
        raise ValueError(f"{label}은(는) {low}~{high} 사이로 넣어 주세요")
    return n


def _clean_channel(raw):
    """온·오프라인 운영 모드. 모드와 받을 주문 종류를 함께 맞춘다."""
    if not isinstance(raw, dict):
        raise ValueError("운영 모드 설정 형식이 올바르지 않습니다")
    out = dict(DEFAULTS["channel"])
    out.update({k: v for k, v in get().get("channel", {}).items() if v is not None})
    if "mode" in raw:
        mode = str(raw.get("mode") or "").strip()
        if mode not in config.CHANNEL_MODES:
            raise ValueError("운영 모드는 오프라인·온라인·통합 중에서 골라 주세요")
        out["mode"] = mode
    for key in ("pickup", "delivery", "preorder"):
        if key in raw:
            out[key] = bool(raw.get(key))
    if "pickupMin" in raw:
        out["pickupMin"] = _int_in(raw.get("pickupMin"), "포장 준비 시간(분)", 0, 180)
    if "deliveryFee" in raw:
        out["deliveryFee"] = _int_in(raw.get("deliveryFee"), "배달료", 0, 50000)
    if "onlineNote" in raw:
        out["onlineNote"] = _clean_text(raw.get("onlineNote"), 160)
    if out["mode"] == "offline":
        # 오프라인 전용 매장이면 온라인 주문을 받지 않는다(화면에도 안 나온다)
        out["pickup"] = out["delivery"] = False
    if out["mode"] == "online":
        out["preorder"] = False
    return out


def _clean_payments(raw):
    """결제수단 설정(켜기/끄기·수수료·안내·계좌). 현금은 끌 수 없다."""
    if not isinstance(raw, dict):
        raise ValueError("결제 설정 형식이 올바르지 않습니다")
    cur = get().get("payments") or {}
    out = {code: dict(DEFAULTS["payments"][code]) for code in DEFAULTS["payments"]}
    for code in out:
        out[code].update({k: v for k, v in (cur.get(code) or {}).items() if v is not None})
    for code, incoming in raw.items():
        if code not in out or not isinstance(incoming, dict):
            continue
        item = out[code]
        if "enabled" in incoming:
            item["enabled"] = bool(incoming.get("enabled"))
        if "feeRate" in incoming:
            try:
                fee = float(incoming.get("feeRate") or 0)
            except (TypeError, ValueError):
                raise ValueError("결제 수수료율은 숫자로 넣어 주세요 (예: 1.5 = 1.5%)")
            if not (0 <= fee <= 20):
                raise ValueError("결제 수수료율은 0~20% 사이로 넣어 주세요")
            item["feeRate"] = round(fee, 2)
        for key in ("note", "bank", "accountNo", "holder", "provider"):
            if key in incoming:
                item[key] = _clean_text(incoming.get(key), 80)
    out["cash"]["enabled"] = True      # 현금은 기본 결제수단이라 끌 수 없다
    tr = out["transfer"]
    if tr["enabled"] and (tr["accountNo"] or tr["bank"]) and not (tr["accountNo"] and tr["bank"]):
        raise ValueError("계좌이체를 쓰려면 은행과 계좌번호를 함께 넣어 주세요")
    return out


def _clean_waiting(raw):
    if not isinstance(raw, dict):
        raise ValueError("웨이팅 설정 형식이 올바르지 않습니다")
    out = dict(DEFAULTS["waiting"])
    out.update({k: v for k, v in get().get("waiting", {}).items() if v is not None})
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    if "notice" in raw:
        out["notice"] = _clean_text(raw.get("notice"), 160)
    if "maxParty" in raw:
        out["maxParty"] = _int_in(raw.get("maxParty"), "한 팀 최대 인원", 1, 30)
    return out


def _clean_events(raw):
    """이벤트·쿠폰 설정. 각 이벤트는 켜기/끄기와 조건만 받는다."""
    if not isinstance(raw, dict):
        raise ValueError("이벤트 설정 형식이 올바르지 않습니다")
    cur = get().get("events") or {}
    out = {k: dict(v) for k, v in DEFAULTS["events"].items()}
    for key in out:
        out[key].update({k: v for k, v in (cur.get(key) or {}).items() if v is not None})
    for key, incoming in raw.items():
        if key not in out or not isinstance(incoming, dict):
            continue
        item = out[key]
        if "enabled" in incoming:
            item["enabled"] = bool(incoming.get("enabled"))
        for flag in ("coupon", "couponOn"):
            if flag in incoming:
                item["coupon"] = bool(incoming.get(flag))
        if "points" in incoming:
            item["points"] = _int_in(incoming.get("points"), "지급 포인트", 0, 100000)
        if "days" in incoming:
            item["days"] = _int_in(incoming.get("days"), "재방문 기준(일)", 1, 365)
        if "percent" in incoming:
            item["percent"] = _int_in(incoming.get("percent"), "할인율(%)", 1, 90)
        for key2, label in (("start", "시작 시각"), ("end", "끝 시각")):
            if key2 in incoming:
                val = str(incoming.get(key2) or "").strip()
                if not re.match(r"^\d{1,2}:\d{2}$", val):
                    raise ValueError(f"시간 할인의 {label}은 14:00 형식으로 넣어 주세요")
                item[key2] = val.zfill(5) if len(val) == 4 else val
        if "title" in incoming:
            item["title"] = _clean_text(incoming.get("title"), 40) or DEFAULTS["events"]["coupon"]["title"]
        if "amount" in incoming:
            item["amount"] = _int_in(incoming.get("amount"), "쿠폰 금액", 0, 100000)
        if "minSpend" in incoming:
            item["minSpend"] = _int_in(incoming.get("minSpend"), "쿠폰 최소 주문 금액", 0, 1000000)
        if "validDays" in incoming:
            item["validDays"] = _int_in(incoming.get("validDays"), "쿠폰 유효 기간(일)", 1, 365)
    td = out["timeDiscount"]
    if td["enabled"] and td["start"] >= td["end"]:
        raise ValueError("시간 할인은 시작 시각이 끝 시각보다 빨라야 합니다")
    return out


def _clean_community(raw):
    if not isinstance(raw, dict):
        raise ValueError("로컬 커뮤니티 설정 형식이 올바르지 않습니다")
    out = dict(DEFAULTS["community"])
    out.update({k: v for k, v in get().get("community", {}).items() if v is not None})
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    if "showToCustomers" in raw:
        out["showToCustomers"] = bool(raw.get("showToCustomers"))
    if "jointPromo" in raw:
        out["jointPromo"] = bool(raw.get("jointPromo"))
    for key in ("intro", "neighborhood"):
        if key in raw:
            out[key] = _clean_text(raw.get(key), 200 if key == "intro" else 60)
    return out


def profile_empty():
    """사업자 정보가 아직 비어 있는지(첫 화면 안내용)."""
    s = get()
    return not (s["businessNo"] or s["ownerName"] or s["address"] or s["phone"])


def summary_for_admin():
    s = get()
    pays = s["payments"]
    # 손님 화면에 실제로 나가는 결제수단과, 켰지만 빠진 조건을 함께 알려 준다.
    available, issues = [], {}
    if pays.get("cash", {}).get("enabled", True):
        available.append("CASH")
    tr = pays.get("transfer", {})
    if tr.get("enabled"):
        if tr.get("bank") and tr.get("accountNo"):
            available.append("TRANSFER")
        else:
            issues["transfer"] = "계좌이체를 켰지만 은행·계좌번호가 비어 있어 손님 화면에 나오지 않습니다."
    for code, key in (("CARD", "card"), ("PAY", "quick")):
        if pays.get(key, {}).get("enabled"):
            available.append(code)
    if not pays.get("cash", {}).get("enabled", True):
        issues["cash"] = "현금 결제는 항상 켜져 있습니다(끕 수 없음)."
    return {
        "store": public(merged=s),
        "pointsRate": points_rate(merged=s),
        "grades": grades(),
        "baseGrade": base_grade(),
        "profileEmpty": profile_empty(),
        "channel": s["channel"],
        "payments": pays,
        "paymentsAvailable": available,
        "paymentIssues": issues,
        "waiting": s["waiting"],
        "events": s["events"],
        "community": s["community"],
        "channelLabels": config.CHANNEL_MODES,
        "paymentMethods": [{"code": c, "label": l, "desc": d} for c, l, d in config.PAYMENT_METHODS],
        "env": {"ownerId": config.OWNER_USERNAME},
    }
