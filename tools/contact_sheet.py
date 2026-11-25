#!/usr/bin/env python3
"""후보 사진을 눈으로 고르기 위한 접촉 시트 생성 (개발용).

사용: python3 tools/contact_sheet.py [시작 인덱스] [개수]
"""
import json, os, sys
from PIL import Image, ImageDraw

CAND = os.environ.get("CAND_DIR", os.path.join(os.path.dirname(__file__), "..", ".candidates"))
OUT = os.path.join(CAND, "sheets")
TW, TH = 300, 225
COLS = 6


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    man = json.load(open(os.path.join(CAND, "manifest.json"), encoding="utf-8"))
    slugs = list(man)
    os.makedirs(OUT, exist_ok=True)
    batch = slugs[start:start + count]
    W = COLS * TW + 10
    H = len(batch) * (TH + 34) + 10
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    y = 10
    for slug in batch:
        d.text((10, y), f"{slug} ({man[slug]['name']})", fill="black")
        y += 20
        for i, c in enumerate(man[slug]["candidates"][:COLS]):
            try:
                im = Image.open(c["file"]).convert("RGB")
            except Exception:
                continue
            im.thumbnail((TW - 6, TH - 6))
            x = 10 + i * TW
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + TW - 6, y + TH - 6], outline="gray")
            d.text((x + 4, y + 4), f"{i}", fill="red")
        y += TH + 14
    p = os.path.join(OUT, f"sheet_{start}.jpg")
    sheet.save(p, quality=80)
    print(p, sheet.size)


if __name__ == "__main__":
    main()
