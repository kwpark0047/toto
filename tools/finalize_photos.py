#!/usr/bin/env python3
"""고른 후보 사진을 카드용으로 잘라 저장하고 CREDITS.md를 만든다 (개발용).

- 4:3 비율로 가운데(위쪽 편향) 크롭, 폭 640px로 축소, JPEG 품질 72
- 출처·저작자·라이선스를 public/images/CREDITS.md 에 기록
"""
import json, os, re
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND = os.environ.get("CAND_DIR", os.path.join(ROOT, ".candidates"))
DEST = os.path.join(ROOT, "public", "images")
W, H, Q = 640, 480, 72

# 슬러그: (후보 번호, 한국어 메뉴명)
PICKS = {
    "kimbap": (2, "김밥"),
    "tteokbokki": (2, "떡볶이"),
    "sundae": (2, "순대"),
    "twigim": (4, "모둠튀김"),
    "ramyeon": (2, "라면"),
    "kimchi-jjigae": (2, "김치찌개"),
    "doenjang-jjigae": (1, "된장찌개"),
    "jeyuk-bokkeum": (1, "제육볶음"),
    "bibimbap": (2, "비빔밥"),
    "bulgogi": (2, "불고기"),
    "janchi-guksu": (1, "잔치국수"),
    "gyeran-mari": (0, "계란말이"),
    "mandu": (3, "만두"),
    "cola": (4, "콜라"),
    "sikye": (0, "식혜"),
    "iced-americano": (0, "아이스아메리카노"),
}


def clean_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def main():
    man = json.load(open(os.path.join(CAND, "manifest.json"), encoding="utf-8"))
    os.makedirs(DEST, exist_ok=True)
    rows = []
    for slug, (idx, name) in PICKS.items():
        c = man[slug]["candidates"][idx]
        im = Image.open(c["file"]).convert("RGB")
        sw, sh = im.size
        target = W / H
        if sw / sh > target:
            nw = int(sh * target)
            left = (sw - nw) // 2
            im = im.crop((left, 0, left + nw, sh))
        else:
            nh = int(sw / target)
            top = max(0, int((sh - nh) * 0.35))  # 음식이 위쪽에 오는 사진이 많아 살짝 위로
            im = im.crop((0, top, sw, top + nh))
        if im.width > W:
            im = im.resize((W, H), Image.LANCZOS)
        path = os.path.join(DEST, slug + ".jpg")
        im.save(path, "JPEG", quality=Q, optimize=True, progressive=True)
        kb = os.path.getsize(path) // 1024
        rows.append({
            "slug": slug, "name": name, "kb": kb,
            "title": clean_html(c["title"]), "creator": clean_html(c["creator"]),
            "license": c["license"], "version": c["license_version"],
            "license_url": c["license_url"], "page": c["page"], "src": c["src"],
        })
        print(f"{slug:16s} {name:8s} {kb:4d}KB  {c['license']:6s} {clean_html(c['creator'])[:30]}")

    with open(os.path.join(DEST, "CREDITS.md"), "w", encoding="utf-8") as f:
        f.write("# 메뉴 사진 출처와 라이선스\n\n")
        f.write("모든 사진은 상업적 이용이 가능한 자유 라이선스(CC0/PDM/CC BY/CC BY-SA) 사진을\n")
        f.write("Openverse(https://openverse.org)와 위키미디어 공용에서 내려받아 로컬에 저장한 것입니다.\n")
        f.write("원본 서버를 직접 링크(핫링크)하지 않고 `public/images/` 에서 제공합니다.\n")
        f.write("CC BY / CC BY-SA 사진은 아래와 같이 저작자를 표시합니다. 사진을 바꿀 경우 이 파일도 함께 갱신하세요.\n\n")
        f.write("| 메뉴 | 파일 | 저작자 | 라이선스 | 원본 |\n|---|---|---|---|---|\n")
        for r in rows:
            lic = r["license"] + ((" " + r["version"]) if r["version"] else "")
            if r["license_url"]:
                lic = f"[{lic}]({r['license_url']})"
            creator = r["creator"] or "미상"
            f.write(f"| {r['name']} | `{r['slug']}.jpg` | {creator} | {lic} | [원본]({r['page']}) |\n")
        f.write("\n## 참고\n\n")
        f.write("- 사진은 메뉴 카드용으로 4:3 크롭, 폭 640px, JPEG 품질 72로 줄여 저장했습니다.\n")
        f.write("- 실제 서비스에서는 매장이 직접 찍은 사진으로 교체하는 것을 권장합니다.\n")
    print("\nCREDITS.md 작성 완료")


if __name__ == "__main__":
    main()
