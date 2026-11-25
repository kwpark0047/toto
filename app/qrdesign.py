"""디자인 QR 렌더링 모듈.

책임: 매장 디자인(점 모양·색·파인더·가운데 배지·하단 문구)을 입힌 QR 을 SVG/PNG 로 그리고,
**실제로 스캔되는지 확인**한다(OpenCV 가 있으면 디코딩, 없으면 생략).

스캔을 지키는 규칙:
- 오류정정 레벨 H(복원 여유 30%)로 만든다.
- 가운데 배지는 전체 폭의 20% 이내, 실패하면 12% → 배지 없음 → 기본 QR 순서로 자동 후퇴한다.
- 전경/배경 명도 대비가 낮으면 저장을 거절한다.
- 생성한 PNG 를 그대로 디코딩해 내용이 맞는지 확인한다(실패 시 자동 후퇴).

PNG 는 Pillow 가 있으면 글꼴까지 그려 문구가 들어가고, 없으면 문구 없이 점·색만 그린다.
SVG·인쇄 화면은 Pillow 없이도 문구가 들어간다.
"""
import base64
import io
import os

from . import config, qr

DEFAULTS = {
    "dot": "rounded",       # rounded | square
    "eye": "rounded",       # rounded | square
    "fg": "#1f2a44",        # 짙은 남색
    "bg": "#fdf3e3",        # 크림
    "badge": "initial",     # initial | none | logo
    "caption": "auto",      # auto | 직접 쓴 문구
    "border": 4,            # 조용한 여백(모듈 수)
    "badgeImage": "",       # 업로드한 배지 이미지 경로(/images/...)
}

FONT_CANDIDATES = [
    "/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _hex(value, fallback):
    v = (value or "").strip()
    if not v:
        return fallback
    v = v.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise ValueError("색은 #1f2a44 처럼 16진수로 넣어 주세요")
    return "#" + v.lower()


def _rgb(color):
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def luminance(color):
    def chan(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(color)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def normalize(opts):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in (opts or {}).items() if v is not None})
    o["dot"] = "rounded" if o.get("dot") == "rounded" else "square"
    o["eye"] = "rounded" if o.get("eye") == "rounded" else "square"
    o["fg"] = _hex(o.get("fg"), DEFAULTS["fg"])
    o["bg"] = _hex(o.get("bg"), DEFAULTS["bg"])
    o["badge"] = o.get("badge") if o.get("badge") in ("initial", "none", "logo") else "initial"
    try:
        o["border"] = max(2, min(10, int(o.get("border") or 4)))
    except (TypeError, ValueError):
        o["border"] = 4
    if contrast(o["fg"], o["bg"]) < 3.5:
        raise ValueError("전경색과 배경색 대비가 너무 낮습니다. 진한 색 + 밝은 배경으로 골라 주세요")
    return o


def caption_text(opts, store_name, label):
    cap = (opts.get("caption") or "").strip()
    if not cap or cap == "auto":
        return f"{store_name} · {label} · 찍고 주문하세요"
    return cap.replace("{store}", store_name).replace("{table}", label)


def layout(text, store_name, label, opts, px=12, badge_ratio=0.18):
    """QR 모듈 행렬 + 그리기 설정을 한 묶음으로 만든다."""
    o = normalize(opts)
    matrix = qr.encode(text, "H")
    n = len(matrix)
    border = o["border"]
    total = n + border * 2
    caption = caption_text(o, store_name, label)
    badge = o["badge"]
    if badge == "logo" and not o.get("badgeImage"):
        badge = "initial"
    badge_d = 0.0
    if badge != "none":
        badge_d = max(3.0, round(total * badge_ratio, 2))
    return {
        "matrix": matrix, "n": n, "border": border, "total": total, "px": px,
        "opts": o, "caption": caption, "badge": badge, "badgeD": badge_d,
        "text": text, "store": store_name, "label": label,
    }


def _finder_boxes(n):
    return [(0, 0), (n - 7, 0), (0, n - 7)]


def _in_finder(x, y, n):
    return ((x < 8 and y < 8) or (x >= n - 8 and y < 8) or (x < 8 and y >= n - 8))


def _badge_center(lay):
    half = lay["total"] / 2
    return half, half


def _in_badge(x, y, lay):
    if lay["badgeD"] <= 0:
        return False
    cx, cy = _badge_center(lay)
    r = lay["badgeD"] / 2
    return (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r


# ---------------------------------------------------------------- SVG
def svg(lay, px=None):
    px = px or lay["px"]
    o = lay["opts"]
    n, border, total = lay["n"], lay["border"], lay["total"]
    cap_h = 2.2 if lay["caption"] else 0
    w = total
    h = total + cap_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * px:.0f}" height="{h * px:.0f}" '
        f'viewBox="0 0 {w} {h}" shape-rendering="geometricPrecision">',
        f'<rect width="{w}" height="{h}" fill="{o["bg"]}"/>',
    ]

    def mod(rect):
        parts.append(rect)

    # 파인더(모서리 눈금)
    for (fx, fy) in _finder_boxes(n):
        x, y = fx + border, fy + border
        if o["eye"] == "rounded":
            mod(f'<rect x="{x + 0.5}" y="{y + 0.5}" width="6" height="6" rx="2" fill="none" '
                f'stroke="{o["fg"]}" stroke-width="1"/>')
            mod(f'<rect x="{x + 2}" y="{y + 2}" width="3" height="3" rx="1.1" fill="{o["fg"]}"/>')
        else:
            mod(f'<rect x="{x + 0.5}" y="{y + 0.5}" width="6" height="6" fill="none" '
                f'stroke="{o["fg"]}" stroke-width="1"/>')
            mod(f'<rect x="{x + 2}" y="{y + 2}" width="3" height="3" fill="{o["fg"]}"/>')

    # 데이터 모듈
    for y in range(n):
        for x in range(n):
            if not lay["matrix"][y][x]:
                continue
            if _in_finder(x, y, n) or _in_badge(x, y, lay):
                continue
            cx, cy = x + border + 0.5, y + border + 0.5
            if o["dot"] == "rounded":
                mod(f'<circle cx="{cx}" cy="{cy}" r="0.5" fill="{o["fg"]}"/>')
            else:
                mod(f'<rect x="{cx - 0.5}" y="{cy - 0.5}" width="1" height="1" fill="{o["fg"]}"/>')

    # 가운데 배지
    if lay["badgeD"] > 0:
        cx, cy = _badge_center(lay)
        r = lay["badgeD"] / 2
        mod(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{o["bg"]}"/>')
        if lay["badge"] == "logo" and o.get("badgeImage"):
            path = _public_path(o["badgeImage"])
            if path and os.path.isfile(path):
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                ext = "png" if path.lower().endswith(".png") else "jpeg"
                size = r * 1.7
                mod(f'<image href="data:image/{ext};base64,{data}" x="{cx - size / 2}" y="{cy - size / 2}" '
                    f'width="{size}" height="{size}" preserveAspectRatio="xMidYMid slice"/>')
        else:
            initial = (lay["store"] or "맛")[:1]
            mod(f'<circle cx="{cx}" cy="{cy}" r="{r * 0.62}" fill="{o["fg"]}"/>')
            mod(f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="-apple-system, Noto Sans KR, sans-serif" font-weight="900" '
                f'font-size="{r * 0.95}" fill="{o["bg"]}">{_esc(initial)}</text>')

    # 하단 문구
    if lay["caption"]:
        mod(f'<text x="{total / 2}" y="{total + 1.35}" text-anchor="middle" '
            f'font-family="-apple-system, Noto Sans KR, sans-serif" font-weight="800" '
            f'font-size="1.05" fill="{o["fg"]}">{_esc(lay["caption"])}</text>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _public_path(url):
    if not url:
        return None
    rel = url.lstrip("/")
    path = os.path.normpath(os.path.join(config.PUBLIC_DIR, rel))
    if not path.startswith(config.PUBLIC_DIR):
        return None
    return path


# ---------------------------------------------------------------- PNG
def _font(size):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


def _pil_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def png(lay, px=None):
    """PNG. Pillow 가 있으면 곡선·글꼴까지, 없으면 단순 도형으로 그린다."""
    px = int(px or lay["px"])
    if _pil_available():
        return _png_pil(lay, px)
    return _png_plain(lay, px)


def _png_pil(lay, px):
    from PIL import Image, ImageDraw
    ss = 2 if lay["total"] * px <= 900 else 1     # 큰 이미지는 한 번만 그린다
    o = lay["opts"]
    n, border, total = lay["n"], lay["border"], lay["total"]
    cap_h = 2.2 if lay["caption"] else 0
    W, H = total * px * ss, (total + cap_h) * px * ss
    img = Image.new("RGB", (int(W), int(H)), o["bg"])
    d = ImageDraw.Draw(img)
    u = px * ss  # 모듈 1칸

    def box(x, y, w, h):
        return [x * u, y * u, (x + w) * u, (y + h) * u]

    for (fx, fy) in _finder_boxes(n):
        x, y = fx + border, fy + border
        d.rounded_rectangle(box(x + 0.5, y + 0.5, 6, 6), radius=2 * u, outline=o["fg"], width=max(1, int(u)))
        d.rounded_rectangle(box(x + 2, y + 2, 3, 3), radius=1.1 * u, fill=o["fg"])

    r = 0.5 * u
    for y in range(n):
        row = lay["matrix"][y]
        for x in range(n):
            if not row[x] or _in_finder(x, y, n) or _in_badge(x, y, lay):
                continue
            cx, cy = (x + border + 0.5) * u, (y + border + 0.5) * u
            if o["dot"] == "rounded":
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=o["fg"])
            else:
                d.rectangle([cx - r, cy - r, cx + r, cy + r], fill=o["fg"])

    if lay["badgeD"] > 0:
        cx, cy = _badge_center(lay)
        rad = lay["badgeD"] / 2
        d.ellipse([(cx - rad) * u, (cy - rad) * u, (cx + rad) * u, (cy + rad) * u], fill=o["bg"])
        if lay["badge"] == "logo" and o.get("badgeImage"):
            path = _public_path(o["badgeImage"])
            if path and os.path.isfile(path):
                try:
                    logo = Image.open(path).convert("RGB")
                    size = int(rad * 1.7 * u)
                    logo = logo.resize((size, size), Image.LANCZOS)
                    mask = Image.new("L", (size, size), 0)
                    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
                    img.paste(logo, (int((cx * u) - size / 2), int((cy * u) - size / 2)), mask)
                except Exception:
                    _draw_initial(d, lay, cx, cy, rad, u)
            else:
                _draw_initial(d, lay, cx, cy, rad, u)
        else:
            _draw_initial(d, lay, cx, cy, rad, u)

    if lay["caption"]:
        font = _font(int(1.05 * u))
        if font:
            tw = d.textlength(lay["caption"], font=font)
            d.text(((total * u - tw) / 2, (total + 0.25) * u), lay["caption"], font=font, fill=o["fg"])

    if ss > 1:
        img = img.resize((int(total * px), int((total + cap_h) * px)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_initial(d, lay, cx, cy, rad, u):
    o = lay["opts"]
    d.ellipse([(cx - rad * 0.62) * u, (cy - rad * 0.62) * u,
               (cx + rad * 0.62) * u, (cy + rad * 0.62) * u], fill=o["fg"])
    font = _font(int(rad * 0.95 * u))
    initial = (lay["store"] or "맛")[:1]
    if font:
        tw = d.textlength(initial, font=font)
        d.text((cx * u - tw / 2, cy * u - rad * 0.5 * u), initial, font=font, fill=o["bg"])


def _png_plain(lay, px):
    """Pillow 없이 그리는 단순 PNG(점·색·여백만). 문구는 들어가지 않는다."""
    import struct
    import zlib
    o = lay["opts"]
    n, border, total = lay["n"], lay["border"], lay["total"]
    side = total * px
    fg = _rgb(o["fg"])
    bg = _rgb(o["bg"])
    rows = []
    for py in range(side):
        y = py / px - border
        row = bytearray()
        for pxx in range(side):
            x = pxx / px - border
            dark = False
            if 0 <= x < n and 0 <= y < n and lay["matrix"][int(y)][int(x)]:
                dark = True
            if dark and lay["badgeD"] > 0:
                cx, cy = _badge_center(lay)
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= (lay["badgeD"] / 2) ** 2:
                    dark = False
            row += bytes(fg) if dark else bytes(bg)
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- 검증
def verify(png_bytes, expected):
    """생성한 PNG 를 실제로 디코딩해 본다. OpenCV 가 없으면 None(확인 못 함)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return False
        detector = cv2.QRCodeDetector()
        for scale in (1.0, 1.6):
            target = img
            if scale != 1.0:
                target = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            text, _, _ = detector.detectAndDecode(target)
            if text:
                return text == expected
        return False
    except Exception:
        return False
