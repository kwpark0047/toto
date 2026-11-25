#!/usr/bin/env python3
"""화면 파일 정적 점검 (개발용).

1) 모든 JS 파일의 문법 검사 (quickjs — ES2020 지원)
2) HTML 이 참조하는 JS/CSS/이미지 파일 존재 확인
3) JS 가 쓰는 $("#id") 선택자가 해당 페이지 HTML(또는 JS가 동적으로 만드는 id)에 있는지 확인
4) HTML 안의 중복 id 확인
"""
import os
import re
import sys

import quickjs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
PAIRS = {
    "customer.html": ["util.js", "customer.js"],
    "admin.html": ["util.js", "nav.js", "admin.js"],
    "kitchen.html": ["util.js", "kitchen.js"],
    "menu.html": ["util.js", "nav.js", "menu.js"],
    "customers.html": ["util.js", "nav.js", "customers.js"],
    "qr.html": ["util.js", "nav.js", "qr.js"],
    "index.html": [],
    "staff.html": ["util.js", "nav.js", "staff.js"],
    "settings.html": ["util.js", "nav.js", "settings.js"],
    "tables.html": ["util.js", "nav.js", "tables.js"],
    "wait.html": ["util.js", "wait.js"],
    "wait-admin.html": ["util.js", "nav.js", "wait-admin.js"],
    "revenue.html": ["util.js", "nav.js", "revenue.js"],
    "inventory.html": ["util.js", "nav.js", "inventory.js"],
    "reservations.html": ["util.js", "nav.js", "reservations.js"],
    "reviews.html": ["util.js", "nav.js", "reviews.js"],
    "stores.html": ["util.js", "nav.js", "stores.js"],
    "account.html": ["util.js", "nav.js", "account.js"],
    "reserve.html": ["util.js", "reserve.js"],
    "print.html": ["util.js", "print.js"],
}
errors = []

# 1) JS 문법 (quickjs 로 컴파일)
ctx = quickjs.Context()
assets = os.path.join(PUB, "assets")
for f in sorted(os.listdir(assets)):
    if not f.endswith(".js"):
        continue
    src = open(os.path.join(assets, f), encoding="utf-8").read()
    try:
        ctx.eval(f"(function(){{{src}\n}});")
    except Exception as e:
        errors.append(f"JS 문법/초기화 오류 {f}: {e}")
    print(f"  문법 OK  {f}")

# 2) 참조 파일
for page in PAIRS:
    html = open(os.path.join(PUB, page), encoding="utf-8").read()
    for m in re.finditer(r'(?:src|href)="(/assets/[^"?]+|/images/[^"?]+)"', html):
        p = os.path.join(PUB, m.group(1).lstrip("/"))
        if not os.path.exists(p):
            errors.append(f"{page}: 없는 파일 참조 {m.group(1)}")

# 3) 선택자
def ids_in_html(html):
    return set(re.findall(r'id="([^"]+)"', html))

def ids_in_js(src):
    found = set(re.findall(r'\$\("#([A-Za-z0-9_\-]+)"\)', src))
    found |= set(re.findall(r'getElementById\("([^"]+)"\)', src))
    # JS 템플릿에서 동적으로 만드는 id="..."
    found |= set(re.findall(r'id="([A-Za-z0-9_\-]+)"', src))
    return found

for page, scripts in PAIRS.items():
    html = open(os.path.join(PUB, page), encoding="utf-8").read()
    page_ids = ids_in_html(html)
    js_src = "".join(open(os.path.join(assets, s), encoding="utf-8").read() for s in scripts)
    used = ids_in_js(js_src)
    dynamic = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', js_src))
    missing = sorted(u for u in used if u not in page_ids and u not in dynamic)
    if missing:
        errors.append(f"{page}: JS가 찾는 id가 HTML/템플릿에 없음 → {missing}")
    print(f"  id 연결  {page:16s} {len(used)}개 확인")

    dup = [i for i in page_ids if html.count(f'id="{i}"') > 1]
    if dup:
        errors.append(f"{page}: 중복 id {dup}")

print()
if errors:
    print("문제:", *errors, sep="\n - ")
    sys.exit(1)
print("화면 파일 점검 통과")
