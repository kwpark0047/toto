#!/usr/bin/env python3
"""메뉴 사진 후보 수집 스크립트 (개발용).

Openverse(CC 라이선스 사진 검색, API 키 불필요)와 위키미디어 공용에서
메뉴별 후보 사진을 내려받고, 출처·라이선스·저작자를 JSON으로 남긴다.
고른 사진만 finalize 단계에서 잘라 리사이즈해 public/images/ 에 저장한다.
"""
import json, os, sys, urllib.parse, urllib.request

UA = "MangjipMenuPrototype/1.0 (local demo)"
OUT = os.environ.get("CAND_DIR", "/tmp/cand")

DISHES = [
    ("kimbap", "김밥", ["kimbap", "gimbap korean rice roll"]),
    ("tteokbokki", "떡볶이", ["tteokbokki", "spicy rice cake korean"]),
    ("sundae", "순대", ["sundae korean sausage", "korean blood sausage sundae"]),
    ("twigim", "모둠튀김", ["korean fried snacks", "twigim fried korean"]),
    ("ramyeon", "라면", ["ramyeon", "korean ramen noodles pot"]),
    ("kimchi-jjigae", "김치찌개", ["kimchi jjigae", "kimchi stew"]),
    ("doenjang-jjigae", "된장찌개", ["doenjang jjigae", "soybean paste stew korean"]),
    ("jeyuk-bokkeum", "제육볶음", ["jeyuk bokkeum", "spicy pork korean stir fry"]),
    ("bibimbap", "비빔밥", ["bibimbap", "korean mixed rice bowl"]),
    ("bulgogi", "불고기", ["bulgogi", "korean beef bulgogi"]),
    ("janchi-guksu", "잔치국수", ["janchi guksu", "korean noodle soup"]),
    ("gyeran-mari", "계란말이", ["gyeranmari", "korean rolled omelette"]),
    ("mandu", "만두", ["mandu korean dumplings", "korean dumplings steamed"]),
    ("cola", "콜라", ["cola glass ice", "coca cola drink glass"]),
    ("sikye", "식혜", ["sikhye", "korean rice drink"]),
    ("iced-americano", "아이스아메리카노", ["iced americano", "iced coffee glass"]),
]

LICENSES = "cc0,pdm,by,by-sa"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def openverse(query, n=6):
    q = urllib.parse.urlencode({
        "q": query, "page_size": n, "license": LICENSES,
        "mature": "false", "size": "large",
    })
    try:
        data = get_json("https://api.openverse.org/v1/images/?" + q)
    except Exception as e:
        print("  openverse 오류", e, file=sys.stderr)
        return []
    out = []
    for r in data.get("results", []):
        out.append({
            "src": "openverse:" + str(r.get("source")),
            "title": r.get("title") or "",
            "creator": r.get("creator") or "",
            "license": (r.get("license") or "").upper(),
            "license_version": r.get("license_version") or "",
            "license_url": r.get("license_url") or "",
            "page": r.get("foreign_landing_url") or "",
            "url": r.get("url") or "",
        })
    return out


def commons(query, n=5):
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrsearch": "filetype:bitmap " + query, "gsrlimit": n,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1200,
    })
    try:
        data = get_json("https://commons.wikimedia.org/w/api.php?" + q)
    except Exception as e:
        print("  commons 오류", e, file=sys.stderr)
        return []
    out = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        out.append({
            "src": "commons",
            "title": page.get("title", ""),
            "creator": (meta.get("Artist", {}) or {}).get("value", ""),
            "license": lic,
            "license_version": "",
            "license_url": (meta.get("LicenseUrl", {}) or {}).get("value", ""),
            "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page.get("title", "")),
            "url": ii.get("thumburl") or ii.get("url") or "",
        })
    return out


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    if len(data) < 6000:
        raise ValueError("too small")
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    only = sys.argv[1:] or None
    manifest = {}
    for slug, name, queries in DISHES:
        if only and slug not in only:
            continue
        seen, cands = set(), []
        for q in queries:
            for c in openverse(q, 6) + commons(q, 4):
                if not c["url"] or c["url"] in seen:
                    continue
                seen.add(c["url"])
                cands.append(c)
        os.makedirs(f"{OUT}/{slug}", exist_ok=True)
        kept = []
        for i, c in enumerate(cands):
            if len(kept) >= 8:
                break
            ext = os.path.splitext(urllib.parse.urlparse(c["url"]).path)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                ext = ".jpg"
            path = f"{OUT}/{slug}/{i:02d}{ext}"
            try:
                size = download(c["url"], path)
            except Exception as e:
                print(f"  skip {slug} {i}: {e}", file=sys.stderr)
                continue
            c["file"] = path
            c["bytes"] = size
            kept.append(c)
        manifest[slug] = {"name": name, "candidates": kept}
        print(f"{slug:16s} {len(kept)}장")
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
