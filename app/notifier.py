"""알림 모듈 — 채널 구조.

책임: '언제·누구에게·어떤 상황'의 알림을 채널별로 보내고, 보낸 기록을 남긴다.
채널은 같은 인터페이스(send)를 쓰므로 새 채널은 CHANNELS 에 하나 더하면 끝난다.

- browser: 지금 실제로 동작한다. 서버는 '화면에서 알림을 띄우라'는 판단만 하고,
  실제 표시는 대기 화면(wait.js)이 서비스 워커로 한다. 표시 후 결과를 기록한다.
- sms(문자): 미연결 스텁. 문자 대행사 계정을 붙여야 실제 발송된다.
- kakao(알림톡): 미연결 스텁. 카카오 비즈니스 채널·템플릿 심사가 필요하다.

규칙:
- 문자·카카오는 수신 동의가 있는 대상에게만 보낸다(동의 없으면 기록만 '차단').
- 문자·카카오는 야간(21:00~08:00)에 보내지 않는다. 브라우저 알림은 예외.
- 실제 외부 전송은 어떤 경로로도 하지 않는다(표준 라이브러리만, 네트워크 호출 없음).
"""
from datetime import datetime

from . import settings, stores, store

CHANNELS = {
    "browser": {"code": "browser", "label": "브라우저 알림", "connected": True,
                "consentRequired": False, "nightBlocked": False,
                "need": "탭이 열려 있으면 동작(브라우저를 닫으면 오지 않음)"},
    "sms": {"code": "sms", "label": "문자(SMS)", "connected": False,
            "consentRequired": True, "nightBlocked": True,
            "need": "문자 대행사 계정(발신번호 등록) 연결"},
    "kakao": {"code": "kakao", "label": "카카오 알림톡", "connected": False,
              "consentRequired": True, "nightBlocked": True,
              "need": "카카오 비즈니스 채널 + 알림톡 템플릿 심사"},
}

EVENTS = {
    "soon": {"code": "soon", "label": "곧 순서",
             "default": "{name}님, 곧 순서입니다 · 앞에 {ahead}팀"},
    "called": {"code": "called", "label": "호출",
               "default": "{ticket}번 {name}님, 입장해 주세요"},
    "seated": {"code": "seated", "label": "입장 완료",
               "default": "{name}님, 입장 처리되었습니다. 즐거운 식사 되세요"},
}

NIGHT_START, NIGHT_END = 21, 8


class Channel:
    """채널 공통 인터페이스. 실제 전송을 붙일 때는 send() 만 바꾸면 된다."""
    code = "base"
    label = ""
    connected = False

    def send(self, target, event, message):
        raise NotImplementedError

    def meta(self):
        base = dict(CHANNELS[self.code])
        base["enabled"] = _channels_on().get(self.code, False)
        return base


class BrowserChannel(Channel):
    code = "browser"

    def send(self, target, event, message):
        # 실제 표시는 브라우저 화면이 한다. 서버는 보낼 준비가 되었음을 알려 준다.
        return {"sent": True, "status": "sent", "detail": "브라우저 화면에서 표시"}


class StubChannel(Channel):
    """문자·카카오 자리. 실제 전송 없이 '미연결' 기록만 남긴다."""

    def __init__(self, code):
        self.code = code

    def send(self, target, event, message):
        return {"sent": False, "status": "stub",
                "detail": f"{CHANNELS[self.code]['label']} 미연결 — {CHANNELS[self.code]['need']}"}


BROWSER = BrowserChannel()
SMS = StubChannel("sms")
KAKAO = StubChannel("kakao")
INSTANCES = {"browser": BROWSER, "sms": SMS, "kakao": KAKAO}


def _channels_on():
    conf = settings.get().get("notify") or {}
    ch = conf.get("channels") or {}
    out = {}
    for code, info in CHANNELS.items():
        default = bool(ch.get(code, code == "browser"))
        # 연결되지 않은 채널은 켜져 있어도 실제로는 보내지 않는다(스텁이 '미연결' 기록)
        out[code] = default
    return out


def channels():
    return [INSTANCES[c].meta() for c in ("browser", "sms", "kakao")]


def templates():
    conf = settings.get().get("notify") or {}
    tpl = conf.get("templates") or {}
    out = {}
    for code, info in EVENTS.items():
        text = (tpl.get(code) or "").strip() or info["default"]
        out[code] = {"code": code, "label": info["label"], "text": text}
    return out


def render_message(event, ticket):
    tpl = templates().get(event, {}).get("text") or ""
    values = {
        "name": (ticket.get("name") or "고객")[:20],
        "ticket": ticket.get("ticketNo") or "",
        "ahead": ticket.get("ahead", 0) if ticket.get("ahead") is not None else 0,
        "party": ticket.get("partySize") or 1,
        "store": settings.public()["name"],
    }
    try:
        return tpl.format(**values)
    except (KeyError, ValueError, IndexError):
        return EVENTS.get(event, {}).get("default", "").format(**values)


def _mask(phone):
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 8 else ""


def _night(now=None):
    hour = (now or datetime.now(store.TZ)).hour
    return hour >= NIGHT_START or hour < NIGHT_END


def send(channel, event, ticket, reason=""):
    """한 채널로 알림을 시도하고 기록한다. 실제 외부 전송은 없다."""
    if channel not in INSTANCES:
        raise ValueError("알 수 없는 알림 채널입니다")
    if event not in EVENTS:
        raise ValueError("알 수 없는 알림 상황입니다")
    info = CHANNELS[channel]
    message = render_message(event, ticket)
    status, sent, detail = "failed", False, ""
    if not _channels_on().get(channel):
        status, detail = "disabled", "설정에서 꺼져 있음"
    elif info["consentRequired"] and not ticket.get("consent"):
        status, detail = "blocked_no_consent", "수신 동의가 없어 보내지 않았습니다"
    elif info["nightBlocked"] and _night():
        status, detail = "blocked_night", "야간(21~08시)에는 보내지 않습니다"
    else:
        res = INSTANCES[channel].send(ticket, event, message)
        sent, status, detail = res["sent"], res["status"], res["detail"]
    log_id = _log(channel, event, ticket, status, detail, message, reason)
    return {"channel": channel, "event": event, "message": message, "sent": sent,
            "status": status, "detail": detail, "logId": log_id}


def _log(channel, event, ticket, status, detail, message, reason=""):
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO notifier_log(store_id, channel, event, ticket_id, ticket_no, recipient, status,"
            " detail, message, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (stores.current(), channel, event, ticket.get("id"), ticket.get("ticketNo") or "",
             _mask(ticket.get("phone")), status, detail, message, reason, store.now()))
        return cur.lastrowid


def record_browser(ticket, event, status="sent", detail="브라우저 화면에서 표시"):
    """대기 화면이 브라우저 알림을 띄운 뒤 결과를 기록한다(서버는 실제 표시를 하지 않는다)."""
    if event not in EVENTS:
        raise ValueError("알 수 없는 알림 상황입니다")
    message = render_message(event, ticket)
    if status not in ("sent", "denied", "failed"):
        status = "sent"
    log_id = _log("browser", event, ticket, status, detail, message, "화면 트리거")
    return {"channel": "browser", "event": event, "message": message,
            "sent": status == "sent", "status": status, "detail": detail, "logId": log_id}


def save_push_subscription(sub):
    """앱을 닫아도 오는 푸시(운영 시)를 위한 자리. 지금은 저장만 하고 연결하지 않는다."""
    import json as _json
    endpoint = (sub or {}).get("endpoint") or ""
    if not endpoint:
        raise ValueError("구독 정보가 비었습니다")
    with store.tx() as conn:
        conn.execute(
            "INSERT INTO push_subscriptions(endpoint, keys_json, status, created_at)"
            " VALUES(?,?,?,?)", (endpoint[:400], _json.dumps(sub.get("keys") or {}), "pending",
                                 store.now()))
    return {"connected": False, "saved": True,
            "detail": "푸시 구독은 저장했지만 실제 푸시 발송은 연결되지 않았습니다(운영 시 연결)"}


def history(date=None, limit=100):
    date = date or store.today()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT * FROM notifier_log WHERE substr(created_at,1,10)=? AND store_id=?"
            " ORDER BY id DESC LIMIT ?",
            (date, stores.current(), int(limit))).fetchall()
    return [{
        "id": r["id"], "channel": r["channel"], "channelLabel": CHANNELS.get(r["channel"], {}).get("label", r["channel"]),
        "event": r["event"], "eventLabel": EVENTS.get(r["event"], {}).get("label", r["event"]),
        "ticketNo": r["ticket_no"], "recipient": r["recipient"], "status": r["status"],
        "detail": r["detail"], "message": r["message"], "createdAt": r["created_at"],
    } for r in rows]


def summary(date=None):
    date = date or store.today()
    with store.read() as conn:
        rows = conn.execute(
            "SELECT channel, status, COUNT(*) c FROM notifier_log"
            " WHERE substr(created_at,1,10)=? AND store_id=? GROUP BY channel, status",
            (date, stores.current())).fetchall()
    by_channel, by_status, total = {}, {}, 0
    for r in rows:
        by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + r["c"]
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["c"]
        total += r["c"]
    return {"date": date, "total": total, "byChannel": by_channel, "byStatus": by_status,
            "sent": by_status.get("sent", 0), "stub": by_status.get("stub", 0)}


def overview(date=None):
    """설정 화면·대기 관리 화면에 보여 줄 알림 현황."""
    return {
        "channels": channels(),
        "events": list(EVENTS.values()),
        "templates": templates(),
        "history": history(date),
        "summary": summary(date),
        "nightRule": f"{NIGHT_START}시~{NIGHT_END}시에는 문자·카카오를 보내지 않습니다(브라우저 알림은 예외)",
        "pushStub": {"connected": False,
                     "need": "앱을 닫아도 오는 푸시는 HTTPS 배포 + 푸시 키 + 구독 저장이 필요합니다(운영 시 연결)"},
    }
