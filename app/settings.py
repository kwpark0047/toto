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


def get():
    """저장된 설정 + 기본값(지금 매장)."""
    with store.read() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_key(),)).fetchone()
    data = _row_value(row["value"] if row else "")
    out = dict(DEFAULTS)
    out.update({k: v for k, v in data.items() if v is not None})
    if not isinstance(out.get("grades"), list) or not out["grades"]:
        out["grades"] = [dict(g) for g in config.MEMBER_GRADES]
    return out


def public():
    """고객 화면·QR·영수증에 보여 줄 값. 빈 값은 빈 문자열 그대로 두고 화면이 감춘다."""
    s = get()
    return {
        "name": s["storeName"],
        "tagline": s["tagline"],
        "address": s["address"],
        "phone": s["phone"],
        "hours": s["hours"],
        "paymentNote": s["paymentNote"],
        "businessNo": s["businessNo"],
        "ownerName": s["ownerName"],
    }


def points_rate():
    try:
        return max(0.0, min(10.0, float(get()["pointsRate"])))
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


def profile_empty():
    """사업자 정보가 아직 비어 있는지(첫 화면 안내용)."""
    s = get()
    return not (s["businessNo"] or s["ownerName"] or s["address"] or s["phone"])


def summary_for_admin():
    s = get()
    return {
        "store": public(),
        "pointsRate": points_rate(),
        "grades": grades(),
        "baseGrade": base_grade(),
        "profileEmpty": profile_empty(),
        "env": {"ownerId": config.OWNER_USERNAME},
    }
