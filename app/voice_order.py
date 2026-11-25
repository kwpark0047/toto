"""음성 주문 해석 모듈.

책임: 손님이 말한 문장(브라우저에서 인식된 텍스트)을 메뉴·수량·옵션·빼기로 해석한다.
음성 파일은 다루지 않는다(브라우저 안에서만 처리). 서버에는 해석된 문장 텍스트만 남는다.

원칙:
- 애매하면 임의로 담지 않는다 → 후보(candidates)를 돌려주고 손님이 고르게 한다.
- 품절·비활성 메뉴는 담지 않고 이유를 알려 준다.
- 메뉴 이름·동의어·숫자(하나/둘/2개)·옵션(맵기·사리·조리)·빼기를 해석한다.
"""
import re

from . import catalog, settings, store

NUMBER_WORDS = {
    "한": 1, "하나": 1, "일": 1, "1": 1, "한개": 1, "한 개": 1, "한그릇": 1, "한 그릇": 1,
    "두": 2, "둘": 2, "이": 2, "2": 2, "두개": 2, "두 개": 2, "두그릇": 2, "두 그릇": 2,
    "세": 3, "셋": 3, "삼": 3, "3": 3, "세개": 3, "세 개": 3, "세그릇": 3, "세 그릇": 3,
    "네": 4, "넷": 4, "사": 4, "4": 4, "네개": 4, "네 개": 4,
    "다섯": 5, "오": 5, "5": 5, "여섯": 6, "육": 6, "6": 6,
    "일곱": 7, "칠": 7, "7": 7, "여덟": 8, "팔": 8, "8": 8, "아홉": 9, "구": 9, "9": 9,
    "열": 10, "십": 10, "10": 10,
}
REMOVE_WORDS = ("빼", "빼줘", "빼고", "삭제", "지워", "없애", "취소", "안 먹", "안먹", "빼 주")
ADD_WORDS = ("담아", "담아줘", "추가", "주문", "먹을게", "먹을래", "줘", "주세요", "더")
SYNONYMS = {
    "김밥": ["김밥", "김초밥"],
    "떡볶이": ["떡볶이", "떡복이", "떡볶기"],
    "순대": ["순대"],
    "모둠튀김": ["모둠튀김", "튀김", "모듬튀김"],
    "라면": ["라면", "라멘"],
    "김치찌개": ["김치찌개", "김치찌게", "김치찌"],
    "된장찌개": ["된장찌개", "된장찌게", "된장찌"],
    "제육볶음": ["제육볶음", "제육", "제육볶기"],
    "비빔밥": ["비빔밥", "비빔"],
    "불고기": ["불고기", "불고기덮밥"],
    "잔치국수": ["잔치국수", "국수"],
    "계란말이": ["계란말이", "계란말", "달걀말이"],
    "만두": ["만두", "군만두", "찐만두"],
    "콜라": ["콜라", "코카콜라", "콜라한잔"],
    "식혜": ["식혜"],
    "아이스아메리카노": ["아이스아메리카노", "아메리카노", "아아", "커피"],
}
UNIT_RE = re.compile(r"(개|그릇|인분|잔|병|접시)")


def _norm(text):
    t = (text or "").lower().strip()
    for ch in ",.!?\n\t":
        t = t.replace(ch, " ")
    return re.sub(r"\s+", " ", t)


def _menu_items():
    return catalog.items()


def _alias_index(items):
    """동의어/이름 → 후보 목록. 이름이 겹치면 후보가 여럿이 된다(애매함)."""
    idx = {}
    names = {i["name"]: i for i in items}
    for name, aliases in SYNONYMS.items():
        for a in aliases:
            idx.setdefault(a, set())
            if name in names:
                idx[a].add(name)
    for i in items:
        idx.setdefault(i["name"], set()).add(i["name"])
    return {k: sorted(v) for k, v in idx.items() if v}


def _qty_near(text, start, end):
    """메뉴 이름 앞뒤에서 수량을 찾는다. 없으면 1."""
    before = text[max(0, start - 12):start]
    after = text[end:end + 8]
    for chunk in (after, before):
        for word in sorted(NUMBER_WORDS, key=len, reverse=True):
            if re.search(rf"(^|\s){re.escape(word)}(\s|$|{UNIT_RE.pattern})", chunk.strip()):
                return NUMBER_WORDS[word]
    m = re.search(r"(\d+)\s*" + UNIT_RE.pattern, text[start:end + 10])
    if m:
        return max(1, min(99, int(m.group(1))))
    return 1


def _options_in(text, item):
    picked = {}
    for group in item.get("options") or []:
        for choice in group["choices"]:
            if choice in text:
                picked[group["name"]] = choice
                break
    return picked


def parse(text, items=None):
    """문장 → 담을 항목·뺄 항목·후보. 실제 장바구니 변경은 화면이 한다."""
    raw = text or ""
    t = _norm(raw)
    items = items if items is not None else _menu_items()
    index = _alias_index(items)
    by_name = {i["name"]: i for i in items}

    found = []   # (start, end, name)
    used = [False] * len(t)
    for alias in sorted(index, key=len, reverse=True):
        start = 0
        while True:
            pos = t.find(alias, start)
            if pos < 0:
                break
            if any(used[pos:pos + len(alias)]):
                pos2 = t.find(alias, pos + 1)
                if pos2 < 0:
                    break
                pos = pos2
                continue
            for k in range(pos, pos + len(alias)):
                used[k] = True
            found.append((pos, pos + len(alias), alias))
            start = pos + len(alias)
    found.sort()

    want_remove = any(w in t for w in REMOVE_WORDS)
    result = {
        "text": raw[:200],
        "action": "none",
        "lines": [],
        "removed": [],
        "candidates": [],
        "unknown": [],
        "message": "",
        "needsConfirm": False,
        "saveText": bool(_voice_setting("saveText")),
    }

    if not found:
        # 이름을 통째로 못 찾았으면 메뉴 이름의 일부(2글자 이상)로 후보를 찾아 본다
        partial = {}
        for i in items:
            name = i["name"]
            for size in (3, 2):
                for start in range(0, max(1, len(name) - size + 1)):
                    piece = name[start:start + size]
                    if len(piece) >= 2 and piece in t:
                        partial.setdefault(i["id"], i)
        if partial:
            result["candidates"] = [{"itemId": i["id"], "name": i["name"], "price": i["price"],
                                     "soldout": bool(i["soldout"])} for i in partial.values()]
            result["needsConfirm"] = True
            result["action"] = "clarify"
            result["message"] = "어떤 메뉴인지 골라 주세요: " + ", ".join(c["name"] for c in result["candidates"])
        else:
            result["action"] = "none"
            result["message"] = ("무엇을 뺄지 메뉴 이름을 함께 말해 주세요" if want_remove
                                 else "메뉴 이름을 찾지 못했습니다. 예: '김치찌개 하나 담아줘'")
        return _log_and_return(result)

    ambiguous = []
    for idx_f, (start, end, alias) in enumerate(found):
        names = index.get(alias, [])
        if len(names) > 1:
            ambiguous.append(names)
            continue
        item = by_name.get(names[0])
        if not item:
            continue
        if item.get("soldout"):
            result["unknown"].append(f"{item['name']}은(는) 품절이라 담지 않았습니다")
            continue
        # 이 메뉴 바로 뒤 문장에 '빼'가 있으면 그 메뉴만 뺀다(문장 전체가 아니라)
        next_start = found[idx_f + 1][0] if idx_f + 1 < len(found) else len(t)
        segment = t[end:min(next_start, end + 14)]
        remove_this = any(w in segment for w in REMOVE_WORDS) or (
            want_remove and len(found) == 1)
        options = _options_in(t, item)
        if remove_this:
            result["removed"].append({"itemId": item["id"], "name": item["name"],
                                      "options": options, "qty": _qty_near(t, start, end)})
        else:
            result["lines"].append({"itemId": item["id"], "name": item["name"],
                                    "price": item["price"], "qty": _qty_near(t, start, end),
                                    "options": options})

    # 같은 메뉴가 두 번 잡히면(동의어가 겹칠 때) 한 줄로 합친다
    def _dedupe(rows):
        out = {}
        for r in rows:
            key = (r["itemId"], tuple(sorted((r.get("options") or {}).items())))
            if key in out:
                out[key]["qty"] = max(out[key]["qty"], r["qty"])
            else:
                out[key] = dict(r)
        return list(out.values())

    result["lines"] = _dedupe(result["lines"])
    result["removed"] = _dedupe(result["removed"])

    if ambiguous:
        # 애매하면 담지 않고 후보만 보여 준다
        seen = set()
        result["candidates"] = []
        for names in ambiguous:
            for nm in names:
                if nm in seen:
                    continue
                seen.add(nm)
                it = by_name.get(nm)
                if it:
                    result["candidates"].append({"itemId": it["id"], "name": it["name"],
                                                 "price": it["price"], "soldout": bool(it["soldout"])})
        result["needsConfirm"] = True

    if result["removed"] and not result["lines"]:
        result["action"] = "remove"
        result["message"] = ", ".join(f"{r['name']} 빼기" for r in result["removed"])
    elif result["lines"] and not result["removed"]:
        result["action"] = "add"
        result["message"] = ", ".join(f"{l['name']} {l['qty']}개" for l in result["lines"])
    elif result["lines"] and result["removed"]:
        result["action"] = "mixed"
        result["message"] = ("담기: " + ", ".join(f"{l['name']} {l['qty']}개" for l in result["lines"])
                             + " / 빼기: " + ", ".join(r["name"] for r in result["removed"]))
    if result["candidates"]:
        result["message"] = ("어떤 메뉴인지 골라 주세요: "
                             + ", ".join(c["name"] for c in result["candidates"]))
    if not result["lines"] and not result["removed"] and not result["candidates"]:
        result["message"] = result["unknown"][0] if result["unknown"] else "담을 메뉴를 찾지 못했습니다"
    return _log_and_return(result)


def _voice_setting(key, default=True):
    conf = settings.get().get("voice") or {}
    return conf.get(key, default)


def _log_and_return(result):
    """해석된 문장만 남긴다(음성 파일 없음). 설정에서 저장을 끄면 남기지 않는다."""
    if not _voice_setting("saveText"):
        return result
    try:
        with store.tx() as conn:
            conn.execute(
                "INSERT INTO voice_log(text, action, lines_json, created_at) VALUES(?,?,?,?)",
                (result["text"][:200], result["action"],
                 str([l["name"] for l in result["lines"]]), store.now()))
    except Exception:
        pass
    return result


def log(limit=50):
    with store.read() as conn:
        rows = conn.execute("SELECT * FROM voice_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "text": r["text"], "action": r["action"], "createdAt": r["created_at"]}
            for r in rows]
