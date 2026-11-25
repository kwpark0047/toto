# 구조 문서 — 맛집 QR·NFC 메뉴판 주문·매장 관리 시제품

## 1. 설계 원칙

1. **한 파일에 몰아넣지 않는다.** 기능은 `app/` 아래 모듈로 나누고, 각 모듈은 자기 책임만 진다.
2. **다른 모듈의 테이블을 직접 읽지 않는다.** 공개 함수로만 부른다(예: 주문은 `catalog.items()`,
   웨이팅은 `customers.upsert()`, 결제는 `inventory.consume_conn()`).
3. **화면은 계산하지 않는다.** 금액·재고·포인트·등급·권한·급여는 서버가 다시 계산한다.
4. **표준 라이브러리만.** 외부 패키지·CDN·외부 API 없이 동작한다.
   Pillow(인쇄물 글꼴)·OpenCV(QR 스캔 검증)는 **있으면 쓰고 없으면 생략**하는 선택 기능이다.
5. **모의와 실제를 구분한다.** 결제(PG)·문자·카카오·푸시·현금영수증 발급은 **미연결**이며
   코드에 스텁과 기록만 두고 화면·문서에 "미연결/추후 연동"으로 표시한다.
6. **매장은 섞이지 않는다.** 업무 데이터는 모두 `store_id`로 나뉘고, 요청 하나는 한 매장 안에서만 동작한다.

## 2. 모듈 지도

| 모듈 | 책임 | 주요 의존 |
|---|---|---|
| `app/config.py` | 기본 설정·상태 이름·역할/권한 정의·등급 기본값·로그인 정책 | – |
| `app/store.py` | SQLite 연결/스키마/마이그레이션/시드, `rev`, 기본 매장 보장 | config |
| `app/stores.py` | 매장 목록·추가·수정·비교, **요청 단위 현재 매장(contextvar)** | store |
| `app/auth.py` | 비밀번호 해시, 로그인/잠금, 세션(매장·권한 포함), **권한 계산**, 비밀번호 초기화·매장 전환 | stores, config |
| `app/staff.py` | 직원 계정·역할, 가입, 출퇴근·월 근무시간·근태 CSV, **근무 스케줄·지각/미출근 대조**, **예상 급여** | auth, settings, stores, tables |
| `app/settings.py` | 매장별 설정(기본·사업자·영업시간·포인트/등급·알림·QR·인쇄 문구) | stores, store |
| `app/tables.py` | 매장별 테이블 등록·이름·좌석·순서·비활성, 코드/URL | stores, store |
| `app/catalog.py` | 매장별 메뉴·카테고리 CRUD, 품절, 순서, 사진, 옵션, 추천, 원산지·알레르기·번역 | stores, store |
| `app/orders.py` | 주문 생성(서버 가격), **4단계 상태 전이**, 현금 결제 확인, 포인트 연결, **재고 차감/복원 호출** | catalog, customers, inventory, tables, stores |
| `app/customers.py` | 회원·등급 자동/수동, 포인트 원장, 방문 이력, 생일, 합치기, CSV | settings, stores | 
| `app/inventory.py` | 재료·레시피, 결제 시 차감·취소 시 복원, 안전재고 경고, 입출고 기록, 품절 제안 | stores, store |
| `app/reservations.py` | 예약 신청·확정·도착·노쇼·취소, 캘린더, 테이블 배정 | tables, stores |
| `app/reviews.py` | 별점·한 줄 평가(주문 1건 1개), 답글 메모, 숨김, 평균·추이 | orders, tables, stores |
| `app/kitchen.py` | 주방 대기열(경과·지연·알레르기), **서빙 대기 목록**, 테이블 현황판 | orders, catalog, tables |
| `app/stats.py` | 오늘 요약·**기간 매출(일별·시간대·결제수단·카테고리·CSV)**, 대시보드 | stores |
| `app/waiting.py` | 대기 접수·번호·개인 링크·호출·입장·취소/노쇼·보드·자동 정리 | customers, tables, notifier, stores |
| `app/service.py` | 직원 호출(테이블별 중복 합침, 처리 완료) | tables, stores |
| `app/notifier.py` | 알림 채널(브라우저/문자/카카오), 템플릿, 동의·야간 규칙, 이력 | settings, stores |
| `app/recommend.py` | 또 시킬까요, 함께 많이 시키는 메뉴, 예상 조리시간·혼잡도 | orders, catalog |
| `app/voice_order.py` | 음성 인식 문장 → 메뉴·수량·옵션·빼기 해석 | catalog, settings |
| `app/qr.py` / `app/qrdesign.py` | 순수 파이썬 QR 인코더 / 디자인 렌더·검증 | – |
| `app/qrs.py` / `app/stand.py` / `app/pdf.py` | QR URL·디자인 적용 / 인쇄물 이미지 / 표준 라이브러리 PDF | qrs, settings, tables |
| `app/backup.py` | DB 스냅숏, 자동 백업·보관 개수(만든 시각 기준), 복원 | store, config |
| `app/api.py` | URL → 모듈 라우팅, **권한 검사**, 오류 → HTTP 상태 | 모든 업무 모듈 |
| `app/web.py` | 화면 주소 ↔ HTML, **화면별 필요 권한** | config |
| `server.py` | HTTP 파싱, 쿠키→세션, 화면 권한 게이트, 시작 배너 | api, web, auth, store |

**의존 방향**: `server → api → 업무 모듈 → store/stores`. 업무 모듈 사이 호출은
`orders → catalog/customers/tables/inventory`, `waiting → customers/tables/notifier/orders`,
`kitchen → orders/catalog/tables`, `stand → qrs/tables`, `stores → settings/tables/catalog/staff/stats` 뿐이며
역방향 호출은 없다.

## 3. 매장 분리(다점포) 구조

```
[요청] server → api.handle
  sid = 로그인 사용자의 세션 active_store   (없으면 ?store=, 그것도 없으면 1)
  with stores.use(sid):                      ← contextvar (스레드마다 독립)
      라우팅 → 모듈 함수 → SQL 의 WHERE store_id = stores.current()
```

- **컬럼**: `categories`, `menu_items`, `orders`, `customers`, `dining_tables`, `staff`, `attendance`,
  `waiting_tickets`, `service_calls`, `notifier_log`, `ingredients`, `recipes`, `ingredient_logs`,
  `reservations`, `reviews`, `staff_schedules` 에 `store_id` (기본 1).
- **기존 데이터**: 마이그레이션 때 모두 `store_id=1` 로 채워지고, 매장 1행이 자동 생성된다(이름은 설정값).
  `migration_check.py` 가 이 동작을 확인한다.
- **설정**: `settings` 키가 매장 1은 `store`(예전 그대로), 다른 매장은 `store:<id>`.
- **회원 연락처 유일**: `(store_id, phone)` 부분 유일 인덱스. 같은 번호가 두 매장에 있어도 된다.
- **대기 번호**: 매장 1은 날짜 키를 그대로, 다른 매장은 `날짜:매장` 키로 번호를 따로 센다.
- **공개 주소**(로그인 없음): 손님은 `?store=` 또는 테이블 코드로 매장을 정한다.
  `/api/table/<코드>`, `/api/menu?code=<코드>`, `/api/qr/<코드>.png`, `/api/recommend?table=<id>`,
  `/api/calls?table=<id>` 는 코드/테이블로 매장을 찾아 `stores.use()` 로 감싼 뒤 응답한다.
  주문 생성(`orders.create`)도 테이블의 매장으로 계산·저장한다.
- **전환**: `POST /api/stores/switch` → `staff_sessions.active_store` 갱신(관리자만). 직원의 소속 매장
  (`staff.store_id`)은 로그인 기본값이고, 비관리자는 바꿀 수 없다.

## 4. 권한

`config.PERMISSIONS` 에 11개 권한 키와 `ROLE_PERMISSIONS` 기본값이 있다.
실제 권한 = 역할 기본값 ⊕ `staff.permissions`(JSON, 직원별 예외). 관리자는 항상 전부.

| API/화면 | 확인하는 권한 |
|---|---|
| `/api/state`, `/api/orders`(목록), 웨이팅 관리, 예약 관리 | `order.manage` |
| 주문 상태 변경(취소 제외) | `order.status` |
| 주문 취소·결제 되돌리기 | `order.cancel` |
| 현금 결제 확인·영수증 표시 | `order.manage` |
| 메뉴·카테고리·사진·추천 | `menu.edit` (가격만 `price.edit`) |
| 품절 | `soldout.manage` |
| 회원·리뷰 | `customer.view` |
| 매출·정산·대시보드·매장 비교 | `sales.view` |
| 직원·근태·스케줄·급여·비밀번호 초기화 | `staff.manage` |
| 설정·테이블·QR·인쇄·백업·알림 테스트 | `settings.edit` |
| 주방 화면 | `kitchen.view` |
| 내 계정·출퇴근 | 로그인만 |

- `api.route(..., perm=...)` 로 검사하고, 화면은 `web.PERMS` 로 `server.py` 가 검사한다.
- 매출 권한이 없으면 `/api/state` 의 금액을 빼고 건수만 준다(`salesHidden`).
- 로그인하지 않은 손님의 `/api/orders/<id>` 는 이름·연락처를 빈 값으로 돌려준다.

## 5. 데이터 모델 (`data/mangjip.db`)

| 테이블 | 요약 |
|---|---|
| `stores` | 매장(상호·간단 정보·사용 여부) |
| `categories`, `menu_items` | 매장별 메뉴. `featured*`, `origin`, `allergens`, `spice`, `i18n` |
| `customers`, `point_events` | 매장별 회원·포인트 원장(`balance_after`) |
| `orders`, `order_items` | 주문 스냅숏. `store_id`, `subtotal`/`points_used`/`points_earned`, `served_at`, `receipt_*` |
| `dining_tables` | 매장별 테이블(`code`, `label`, `seats`, `sort`, `active`) |
| `staff`, `staff_sessions`, `attendance` | 직원(`permissions`, `pay_type`, `hourly_wage`, `monthly_salary`, `must_change`), 세션(`active_store`), 출퇴근 |
| `staff_schedules` | 근무 스케줄(직원·날짜·시작·끝) |
| `ingredients`, `recipes`, `ingredient_logs` | 재료·메뉴별 소모량·입출고 기록(`IN/OUT/ADJUST/RESTORE`) |
| `reservations` | 예약(토큰·날짜·시간·인원·상태·테이블) |
| `reviews` | 리뷰(주문 1건 UNIQUE, 별점·한 줄·숨김·답글) |
| `waiting_tickets`, `waiting_counters` | 대기(토큰, 상태, 좌석, `purged`) / 번호 |
| `service_calls`, `notifier_log`, `push_subscriptions`, `voice_log` | 직원 호출 / 알림 이력 / 푸시 자리 / 음성 문장 |
| `settings`, `meta` | 매장별 설정(JSON) / `rev` |

- 주문 항목은 **주문 시점 가격을 복사**한다. 가격을 바꿔도 과거 매출은 그대로.
- 주문 상태: `RESERVED → NEW → ACCEPTED → COOKING → DONE(조리완료·서빙 대기) → SERVED`.
  되돌리기 제한과 `CANCELED` 는 `orders.STATUS_FLOW` 한 곳에서 정의한다.
- 예약 상태: `PENDING(신청) → CONFIRMED → ARRIVED / NOSHOW / CANCELED` (`reservations.FLOW`).
- 스키마 변경은 `store.py` 의 `_ADDED_COLUMNS`/`_migrate()` 가 기존 DB에 컬럼을 더해 준다.

## 6. 요청 흐름(예)

```
[주문]  POST /api/orders
  api.api_order_create → orders.create()
    1) 테이블(또는 대기표)로 매장 결정 → with stores.use(매장)
    2) tables.get_any() 활성 확인, catalog.items() 가격·품절 확인, 금액 계산
    3) 한 트랜잭션: customers.upsert → orders/order_items insert
       → customers.use_points → store.bump(rev)

[결제]  POST /api/orders/{id}/payment  (order.manage)
  orders.set_payment(paid=True)
    같은 트랜잭션: customers.earn_on_payment → inventory.consume_conn(레시피×수량, 주문당 1회)
  paid=False → customers.cancel_earn → inventory.restore_conn(OUT 기록 되돌리기)

[서빙]  주방 화면: DONE → SERVED
  kitchen.serving() 은 DONE 주문을 오래 기다린 순으로, done_at 기준 경과 시간과 함께 준다.

[예약]  POST /api/reservations/public (손님, 동의 필수) → PENDING
       POST /api/reservations/{id}/status {CONFIRMED} (사장님)

[리뷰]  POST /api/reviews {orderId, rating, comment}
  reviews.create → orders.get 으로 매장·상태 확인(조리 완료/서빙/결제) → 주문당 1개

[매장 전환] POST /api/stores/switch → auth.switch_store(세션 active_store) → 이후 요청은 그 매장

[알림]  waiting.call() → notifier.send("sms"/"kakao") → '미연결' 기록
[QR]    GET /api/qr/3.png → qrs.png → qrdesign(실제 디코딩 검증, 실패 시 단계적 후퇴)
```

## 7. 인쇄물

- `stand.py` 가 테이블별 스탠드 PNG(200dpi)를 만들고 `pdf.py` 가 A4/B4/A3/A5/A6 규격에 맞춰 얹은 PDF를 만든다.
- 화면 인쇄는 `/print`(CSS `@page`), 파일 저장은 PDF. 파일명에 크기·배치가 들어간다.
- 테이블이 추가·이름 변경·비활성되면 다음 생성 때 자동 반영된다(매장별).

## 8. 백업·배포

- `backup.py`가 SQLite backup API로 `data/backups/backup-<태그>-<시각>.db`를 만든다.
  자동 1일 1회, 최근 7개 보관 — **만든 시각 기준**으로 정리하고 방금 만든 파일은 보호한다.
- 복원은 `confirm="복원"`을 요구하고, 실행 전 `before-restore` 백업을 남긴 뒤 덮어쓴다.
- 백업 파일은 **모든 매장**을 담는다. 매장별로 따로 백업하지 않는다.
- 배포 준비: `배포-준비.md`(HTTPS·방화벽·백업·장애 대응), 개인정보: `개인정보-처리방침-초안.md` + `/privacy`.

## 9. 확장 지점(미구현)

| 앞으로 | 붙일 위치 | 지금 해 둔 것 |
|---|---|---|
| 실결제(PG)·부분 환불 | `orders.payment_method` 확장 + 웹훅 | 현금 확인 전이 한 곳 |
| 문자·카카오 실제 발송 | `notifier.INSTANCES`의 `StubChannel.send()` 교체 | 채널 인터페이스·동의·야간 규칙·이력 |
| 앱 닫아도 오는 푸시 | `push_subscriptions` + 서비스 워커 `push` 이벤트 | 구독 저장 스텁 |
| 예약 알림·손님 확정 안내 | `reservations` 상태 전이 → `notifier.send` | 상태·토큰·템플릿 구조 |
| 재고 자동 발주 | `inventory` 에 거래처·발주서 | 품절 제안·입출고 기록 |
| 급여 세무·명세서 | 회계 프로그램 연동 | 실제 근무시간·시급/월급 계산 |
| 리뷰 공개·쿠폰 | `reviews` 공개 목록·`customers` 쿠폰 | 별점·답글·숨김 |

## 10. 한계와 주의

- 음성 인식은 **브라우저(크롬 안드로이드)가 구글 서버로 보내 처리**한다. 우리 서버는 텍스트만 받는다.
- 브라우저 알림은 탭이 열려 있을 때만 온다. 실제 푸시는 배포·키·구독이 필요하다.
- 원산지·알레르기 정보의 정확성과 법적 표시 의무는 **매장 책임**이다.
- 사업자등록번호는 형식만 검사한다(진위확인·본인인증 없음).
- 예상 급여는 **참고용**이다. 세금·4대보험·급여명세서는 다루지 않는다.
- 예약·리뷰는 문자를 보내지 않는다. 리뷰 답글은 매장 내부 메모다.
- 로컬 시제품이라 서버는 `0.0.0.0`으로 열린다. 운영 전 HTTPS·접근제어가 필요하다.
- 브라우저가 없는 환경이라 화면은 `tools/dom_harness.py`(quickjs)로 렌더만 검사했다.
  실제 기기에서의 터치·스크린리더·TTS·색감 검증은 하지 못했다.
