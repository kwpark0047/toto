"""QR 코드 모듈.

책임: 테이블별 주문 URL 을 만들고 QR 이미지(PNG/SVG)로 그린다.
디자인(점·색·가운데 배지·하단 문구)은 qrdesign 모듈이 그리고, 이 모듈은
'스캔되는지 확인하고 실패하면 단순하게 후퇴하는' 순서를 책임진다.

qr.py(순수 파이썬 인코더)만으로 모듈을 만들며 외부 서비스에 이미지를 요청하지 않는다.
"""
import struct
import zlib

from . import qr, qrdesign, settings, stores

DEFAULT_SCALE = 10
BORDER = 4
MAX_LEN = 300


def table_url(base, code):
    """테이블 코드 → 고객 접속 주소. 코드는 tables 모듈이 붙이는 문자열("1", "9" …)."""
    base = (base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise ValueError("주소는 http:// 또는 https:// 로 시작해야 합니다")
    if len(base) > MAX_LEN:
        raise ValueError("주소가 너무 깁니다")
    code = str(code or "").strip()
    if not code or not all(ch.isalnum() or ch in "-_" for ch in code):
        raise ValueError("테이블 코드가 올바르지 않습니다")
    return f"{base}/t/{code}"


def store_url(base):
    """매장 공통 QR 주소 — 손님이 테이블을 고르는 화면(/). 다른 매장은 /?store=<id>."""
    base = (base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise ValueError("주소는 http:// 또는 https:// 로 시작해야 합니다")
    sid = stores.current()
    return f"{base}/" + (f"?store={sid}" if sid != 1 else "")


def wait_url(base):
    """웨이팅 접수 주소. 기본 매장은 /wait, 다른 매장은 /wait?store=<id>."""
    base = (base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise ValueError("주소는 http:// 또는 https:// 로 시작해야 합니다")
    sid = stores.current()
    return f"{base}/wait" + (f"?store={sid}" if sid != 1 else "")


def nfc_table_url(base, code):
    """NFC 태그에 쓰는 주소. ?via=nfc 로 QR 유입과 따로 센다."""
    url = table_url(base, code)
    sid = stores.current()
    return url + "?via=nfc" + (f"&store={sid}" if sid != 1 else "")


def online_order_url(base):
    """포장·배달 주문 화면 주소(/order). **kwargs 없이 매장만 붙인다."""
    base = (base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise ValueError("주소는 http:// 또는 https:// 로 시작해야 합니다")
    sid = stores.current()
    return f"{base}/order" + (f"?store={sid}" if sid != 1 else "")


def design_options():
    opts = dict(qrdesign.DEFAULTS)
    current = settings.get().get("qr") or {}
    opts.update({k: v for k, v in current.items() if v not in (None, "")})
    return opts


def _url_for(code, base):
    if code == "wait":
        return wait_url(base)
    if code in (None, "", "store"):
        return store_url(base)
    return table_url(base, code)


def _layout(code, base, label, store_name, opts, px, badge_ratio):
    url = _url_for(code, base)
    lay = qrdesign.layout(url, store_name, label or "", opts, px=px, badge_ratio=badge_ratio)
    lay["url"] = url
    return lay


def svg(code, base, px=8, label=None, store_name="맛집", opts=None):
    lay = _layout(code, base, label, store_name, opts or design_options(), px, 0.18)
    return qrdesign.svg(lay, px)


def png(code, base, px=DEFAULT_SCALE, label=None, store_name="맛집", opts=None, design=True):
    """(png 바이트, 정보) 를 돌려준다. 스캔이 확인되지 않으면 단순 QR 로 후퇴한다."""
    opts = opts or design_options()
    url = _url_for(code, base)
    info = {"url": url, "designed": bool(design), "badgeRatio": 0, "verified": None, "fallback": False}
    if design:
        for ratio in (0.18, 0.12, 0.0):
            lay = qrdesign.layout(url, store_name, label or "", opts, px=px, badge_ratio=ratio)
            data = qrdesign.png(lay, px)
            ok = qrdesign.verify(data, url)
            if ok is not False:
                info.update({"badgeRatio": ratio, "verified": ok,
                             "badge": lay["badge"] if ratio else "none"})
                return data, info
        info["fallback"] = True
    # 단순 QR(디자인 없음) — 가장 안전한 마지막 수단
    m = qr.encode(url)
    n = len(m)
    side = (n + BORDER * 2) * px
    rows = []
    for py in range(side):
        y = py // px - BORDER
        row = bytearray()
        for pxx in range(side):
            x = pxx // px - BORDER
            dark = 0 <= x < n and 0 <= y < n and m[y][x]
            row.append(0 if dark else 255)
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
    info["designed"] = False
    info["verified"] = qrdesign.verify(data, url)
    return data, info


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
