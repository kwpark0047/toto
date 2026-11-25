"""테이블 메뉴판 인쇄물 모듈.

책임: 손님이 '메뉴 보고 주문하는 것'임을 한눈에 알 수 있는 세로형 스탠드 인쇄물을
테이블마다 자동으로 그리고(PNG), PDF/인쇄용 HTML 로 묶는다.

- 내용: 매장 이름 · 큰 제목(기본 "메뉴 보기 · 주문") · 부제 · 디자인 QR · 큰 테이블 번호 ·
  "NFC도 됩니다" 안내 · 사용 3단계 · 하단 안내. 문구·강조색은 설정에서 바꾼다.
- 용지: A6 / A5 / A4 / B4 (기본 A5). A4·B4 는 한 장에 1·2·4개 배치.
- 테이블이 늘거나 이름이 바뀌면 다음 생성 때 자동 반영되고, 비활성 테이블은 빠진다.
"""
import io
import re

from . import config, pdf, qrdesign, qrs, settings, tables

DPI = 200
MM = 25.4
FONT_CANDIDATES = qrdesign.FONT_CANDIDATES
SIZES = tuple(pdf.PAPERS.keys())
LAYOUTS = (1, 2, 4)


def _font(size):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def _pil():
    from PIL import Image, ImageDraw
    return Image, ImageDraw


def _rgb(color):
    c = (color or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def _mix(color, other, ratio):
    a, b = _rgb_any(color), _rgb_any(other)
    return tuple(int(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def _rgb_any(color):
    return color if isinstance(color, tuple) else _rgb(color)


def _light(color):
    """배경으로 쓸 아주 옅은 색."""
    return _mix(color, (255, 255, 255), 0.90)


def normalize_size(size, layout=1):
    size = (size or "A5").upper()
    if size not in SIZES:
        size = "A5"
    try:
        layout = int(layout)
    except (TypeError, ValueError):
        layout = 1
    if layout not in LAYOUTS:
        layout = 1
    if layout > 1 and size not in pdf.MULTI_PAPERS:
        size, layout = "A4", 4 if layout == 4 else 2
    return size, layout


def _store():
    return settings.public()


def _wait_qr_png(base, px=8):
    data, info = qrs.png("wait", base, px=px, label="대기 접수",
                         store_name=_store()["name"] or "맛집")
    return data, info


    return settings.public()


def _stand_texts():
    conf = settings.get().get("stand") or {}
    steps = [s.strip() for s in (conf.get("steps") or "").split("|") if s.strip()][:3]
    while len(steps) < 3:
        steps.append("")
    return {
        "title": conf.get("title") or "메뉴 보기 · 주문",
        "subtitle": conf.get("subtitle") or "휴대폰으로 찍어 주문하세요",
        "steps": steps,
        "nfc": conf.get("nfc") or "NFC 태그에 휴대폰을 대도 열립니다",
        "footer": conf.get("footer") or "",
        "accent": conf.get("accent") or "#d9480f",
    }


def stand_image(table, base, size="A5", dpi=DPI):
    """테이블 1개의 스탠드 PNG. (bytes, info)"""
    Image, ImageDraw = _pil()
    size, _ = normalize_size(size, 1)
    w_mm, h_mm = pdf.PAPERS[size]
    w, h = int(w_mm / MM * dpi), int(h_mm / MM * dpi)
    store = _store()
    texts = _stand_texts()
    accent = _rgb(texts["accent"])
    ink = (34, 28, 22)
    bg = _light(accent)

    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    # 위쪽 강조 띠 + 부드러운 배경
    d.rectangle([0, 0, w, int(h * 0.16)], fill=accent)
    d.rectangle([0, int(h * 0.16), w, h], fill=bg)

    unit = w / 100.0   # 폭의 1% 를 기준 단위로 쓴다(용지가 바뀌어도 비율 유지)

    f_store = _font(int(unit * 5.6))
    f_title = _font(int(unit * 9.2))
    f_sub = _font(int(unit * 4.4))
    f_label = _font(int(unit * 13))
    f_step = _font(int(unit * 4.0))
    f_small = _font(int(unit * 3.4))

    def center(text, y, font, fill):
        if not font:
            return
        tw = d.textlength(text, font=font)
        d.text(((w - tw) / 2, y), text, font=font, fill=fill)

    center(store["name"] or "맛집", unit * 5.0, f_store, (255, 255, 255))
    center(texts["title"], unit * 20.0, f_title, ink)
    center(texts["subtitle"], unit * 31.0, f_sub, _mix(ink, bg, 0.25))

    # QR (폭의 46%)
    qr_px = max(4, int(w * 0.46 / 45))
    data, info = qrs.png(table["code"], base, px=qr_px, label=table["label"],
                         store_name=store["name"] or "맛집")
    qimg = Image.open(io.BytesIO(data)).convert("RGB")
    qw = int(w * 0.46)
    qimg = qimg.resize((qw, int(qimg.height * qw / qimg.width)), Image.LANCZOS)
    img.paste(qimg, (int((w - qw) / 2), int(unit * 38)))

    # 테이블 번호(크게)
    label_y = int(unit * 38) + qimg.height + int(unit * 2)
    center(table["label"], label_y, f_label, accent)

    # NFC 안내
    center(texts["nfc"], label_y + int(unit * 14), f_small, _mix(ink, bg, 0.2))

    # 사용 3단계
    step_y = label_y + int(unit * 20)
    for i, step in enumerate(texts["steps"]):
        if not step:
            continue
        if f_step:
            d.ellipse([unit * 12, step_y + i * unit * 5.6, unit * 12 + unit * 3.4,
                       step_y + i * unit * 5.6 + unit * 3.4], fill=accent)
            num = str(i + 1)
            tw = d.textlength(num, font=f_small)
            d.text((unit * 12 + (unit * 3.4 - tw) / 2, step_y + i * unit * 5.6 + unit * 0.4),
                   num, font=f_small, fill=(255, 255, 255))
            d.text((unit * 17, step_y + i * unit * 5.6 + unit * 0.2), step, font=f_step, fill=ink)

    if texts["footer"] and f_small:
        center(texts["footer"], h - unit * 6.0, f_small, _mix(ink, bg, 0.35))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    info["size"] = size
    info["mm"] = (w_mm, h_mm)
    return buf.getvalue(), info


def _jpeg_pixels(data):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        return im.width, im.height
    except Exception:
        return 1, 1


def build_pdf(base, size="A5", layout=1, codes=None, kind="table"):
    """활성 테이블의 메뉴판(kind=table) 또는 웨이팅 안내물(kind=wait) PDF."""
    if kind == "wait":
        data, info = poster_image(base, size)
        doc = pdf.PDF()
        w_mm, h_mm = info["mm"]
        pixel_w, pixel_h = _jpeg_pixels(data)
        doc.add_page(w_mm, h_mm, [{
            "data": data, "pixel_w": pixel_w, "pixel_h": pixel_h,
            "x_mm": 0, "y_mm": 0, "w_mm": w_mm, "h_mm": h_mm}])
        return doc.build(), f"waiting-poster-{info['size']}.pdf"
    size, layout = normalize_size(size, layout)
    sheet_w, sheet_h = pdf.PAPERS[size]
    if layout > 1:
        sheet_w, sheet_h = pdf.PAPERS["A4" if size == "A4" else "B4"]
    items = [t for t in tables.list_tables(include_inactive=False) if not codes or t["code"] in codes]
    if not items:
        raise ValueError("인쇄할 테이블이 없습니다")

    # 스탠드 크기: 1장에 1개면 용지 그대로, 여러 개면 칸 크기
    if layout == 1:
        card_w, card_h = sheet_w - 16, sheet_h - 16
        margin_x, margin_y = 8, 8
        cols, rows = 1, 1
    elif layout == 2:
        card_w, card_h = sheet_w - 20, (sheet_h - 30) / 2
        cols, rows = 1, 2
        margin_x, margin_y = 10, 10
    else:
        card_w, card_h = (sheet_w - 30) / 2, (sheet_h - 30) / 2
        cols, rows = 2, 2
        margin_x, margin_y = 10, 10

    doc = pdf.PDF()
    per_sheet = layout
    cards = []
    for t in items:
        data, info = stand_image(t, base, size="A5" if layout > 1 else size)
        cards.append((t, data))

    for start in range(0, len(cards), per_sheet):
        batch = cards[start:start + per_sheet]
        images = []
        for i, (t, data) in enumerate(batch):
            col, row = i % cols, i // cols
            x = margin_x + col * ((sheet_w - 2 * margin_x) / cols)
            y = margin_y + row * ((sheet_h - 2 * margin_y) / rows)
            pixel_w, pixel_h = _jpeg_pixels(data)
            # 칸 안에 비율 유지
            ratio = min(card_w / pixel_w, card_h / pixel_h)
            w_mm = pixel_w * ratio
            h_mm = pixel_h * ratio
            images.append({"data": data, "pixel_w": pixel_w, "pixel_h": pixel_h,
                           "x_mm": x + (card_w - w_mm) / 2, "y_mm": y + (card_h - h_mm) / 2,
                           "w_mm": w_mm, "h_mm": h_mm})
        doc.add_page(sheet_w, sheet_h, images)

    return doc.build(), f"menu-stands-{size}-{layout}up.pdf"


def stands_for_print(base, size="A5", layout=1, kind="table"):
    """화면 인쇄용 목록. kind=wait 이면 매장 앞 웨이팅 안내물 1장."""
    kind = "wait" if kind == "wait" else "table"
    if kind == "wait":
        size = "A3" if (size or "").upper() == "A3" else "B4"
        return {"kind": kind, "size": size, "layout": 1, "sheet": pdf.PAPERS[size],
                "tables": [{"id": 0, "code": "wait", "label": "웨이팅 안내",
                            "url": qrs.wait_url(base),
                            "image": f"/api/print/wait.png?size={size}", "nfc": qrs.wait_url(base)}],
                "texts": _stand_texts(), "store": settings.public()}
    size, layout = normalize_size(size, layout)
    out = []
    for t in tables.list_tables(include_inactive=False):
        out.append({
            "id": t["id"], "code": t["code"], "label": t["label"],
            "url": qrs.table_url(base, t["code"]),
            "image": f"/api/print/stand.png?code={t['code']}&size={size}",
            "nfc": qrs.table_url(base, t["code"]),
        })
    return {"kind": kind, "size": size, "layout": layout, "sheet": pdf.PAPERS[size], "tables": out,
            "texts": _stand_texts(), "store": settings.public()}


# ---------------------------------------------------------------- 웨이팅 안내물
WAIT_TEXT = {
    "title": "대기 접수",
    "subtitle": "번호표 받고 잠시 기다리세요",
    "guide": "전화번호를 남기면 순서와 예상 대기시간을 화면에서 계속 알려 드립니다",
    "steps": ["QR을 찍거나 NFC에 대기", "이름·전화번호·인원 입력", "번호표 확인 후 기다리기"],
    "nfc": "NFC 태그에 휴대폰을 대도 열립니다",
}


def poster_image(base, size="B4", dpi=DPI):
    """매장 앞·입구용 웨이팅 안내물(크게). (bytes, info)"""
    Image, ImageDraw = _pil()
    size = "A3" if (size or "").upper() == "A3" else "B4"
    w_mm, h_mm = pdf.PAPERS[size]
    w, h = int(w_mm / MM * dpi), int(h_mm / MM * dpi)
    store = _store()
    texts = _stand_texts()
    accent = _rgb(texts["accent"])
    ink = (34, 28, 22)
    bg = _light(accent)

    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, h], fill=bg)
    d.rectangle([0, 0, w, int(h * 0.055)], fill=accent)
    d.rectangle([0, h - int(h * 0.03), w, h], fill=accent)
    unit = w / 100.0

    f_store = _font(int(unit * 6.0))
    f_title = _font(int(unit * 14.0))
    f_sub = _font(int(unit * 6.0))
    f_guide = _font(int(unit * 3.8))
    f_step = _font(int(unit * 4.2))
    f_small = _font(int(unit * 3.2))

    def center(text, y, font, fill):
        if not font or not text:
            return
        tw = d.textlength(text, font=font)
        d.text(((w - tw) / 2, y), text, font=font, fill=fill)

    center(store["name"] or "맛집", int(h * 0.075), f_store, accent)
    center(WAIT_TEXT["title"], int(h * 0.14), f_title, ink)
    center(WAIT_TEXT["subtitle"], int(h * 0.27), f_sub, _mix(ink, bg, 0.25))

    qr_data, info = _wait_qr_png(base, px=8)
    qimg = Image.open(io.BytesIO(qr_data)).convert("RGB")
    qw = int(w * 0.44)
    qimg = qimg.resize((qw, int(qimg.height * qw / qimg.width)), Image.LANCZOS)
    img.paste(qimg, (int((w - qw) / 2), int(h * 0.34)))

    y = int(h * 0.34) + qimg.height + int(unit * 4)
    center(WAIT_TEXT["guide"], y, f_guide, _mix(ink, bg, 0.15))
    y += int(unit * 8)
    orig_title, orig_steps = texts["title"], texts["steps"]
    texts["steps"] = WAIT_TEXT["steps"]
    for i, step in enumerate(WAIT_TEXT["steps"]):
        if f_step:
            d.ellipse([unit * 16, y + i * unit * 8, unit * 16 + unit * 5, y + i * unit * 8 + unit * 5], fill=accent)
            num = str(i + 1)
            tw = d.textlength(num, font=f_step)
            d.text((unit * 16 + (unit * 5 - tw) / 2, y + i * unit * 8 + unit * 0.4), num, font=f_step, fill=(255, 255, 255))
            d.text((unit * 24, y + i * unit * 8 + unit * 0.3), step, font=f_step, fill=ink)
    texts["steps"] = orig_steps
    texts["title"] = orig_title

    center(WAIT_TEXT["nfc"] if f_small else "", h - int(h * 0.11), f_small, _mix(ink, bg, 0.3))
    center("순서·예상 대기시간은 매장 앞 화면에서 계속 바뀝니다", h - int(h * 0.075), f_small, _mix(ink, bg, 0.3))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    info.update({"size": size, "mm": (w_mm, h_mm)})
    return buf.getvalue(), info
