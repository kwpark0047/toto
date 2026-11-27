# 구조 문서 — 맛집 QR·NFC 메뉴판 주문·매장 관리 플랫폼(모듈형 멀티테넌트)

## 1. 설계 원칙

1. **한 파일에 몰아넣지 않는다.** 기능은 `app/` 아래 모듈로 나누고, 각 모듈은 자기 책임만 진다.
2. **다른 모듈의 테이블을 직접 읽지 않는다.** 공개 함수로만 부른다(예: 주문은 `catalog.items()`,
   이벤트는 `customers.add_points()`, 결제는 `orders.set_payment()`).
3. **화면은 계산하지 않는다.** 금액·재고·포인트·등급·권한·급여·할인은 서버가 다시 계산한다.
4. **표준 라이브러리만.** 외부 패키지·CDN·외부 API 없이 동작한다.
   Pillow(인쇄물 글꼴)·OpenCV(QR 스캔 검증)는 **있으면 쓰고 없으면 생략**하는 선택 기능이다.
5. **모의와 실제를 구분한다.** PG 결제·문자·카카오·푸시·현금영수증은 **미연결**이며
   결제는 `simulated=1`(모의 승인)로만 기록하고 화면·문서에 "실제 결제 아님"으로 표시한다.
6. **계정과 매장은 섞이지 않는다.** 업무 데이터는 `store_id`, 매장은 `owner_id`(사업자 계정)로 나뉜다.

## 2. 모듈 지도

| 모듈 | 책임 | 주요 의존 |
|---|---|---|
| `app/config.py` | 기본 설정·상태/결제/경로 이름·역할(7종)/권한·등급 기본값 | – |
| `app/store.py` | SQLite/Turso 연결·스키마·마이그레이션·시드, `rev`, 기본 매장·구역 보장 | config |
| `app/stores.py` | **사업자 계정 범위**(`account_scope`)별 매장 목록·추가·수정·소유 확인, 요청 단위 현재 매장(contextvar) | store |
| `app/groups.py` | **매장 그룹**(브랜드·지역·직영/가맹), 그룹 통합 매출·메뉴 일괄 복사·직원 이동·그룹 설정 적용 | stores, stats, staff, tables |
| `app/auth.py` | 비밀번호 해시, 로그인/잠금, 세션(매장·권한 포함), 권한 계산, 매장 전환(계정 소유 확인) | stores, config |
| `app/staff.py` | 직원 계정·역할·세부 권한, **사업자 가입(계정별 매장 분리)**, 출퇴근·스케줄·예상 급여 | auth, settings, stores, tables |
| `app/settings.py` | 매장별 설정: 기본·사업자·영업시간·포인트/등급·알림·QR·인쇄 + **운영 모드·결제수단·웨이팅·이벤트·로컬 커뮤니티** | stores, store |
| `app/tables.py` | 테이블 등록·좌석·순서·비활성, **구역(홀/창가/테라스) CRUD·일괄 생성**, 코드/URL, **NFC NDEF 안내** | stores, store |
| `app/catalog.py` | 매장별 메뉴·카테고리 CRUD, 품절, 순서, 사진, 옵션, 추천, 원산지·알레르기·번역 | stores, store |
| `app/orders.py` | 주문 생성(서버 가격), **경로(table/pickup/delivery/preorder)·할인·쿠폰**, 4단계 상태, 결제 확인 | catalog, customers, events, inventory, settings, tables |
| `app/payments.py` | **결제 모듈**: 현금·계좌이체·카드·간편결제 설정, 입금 확인, PG 어댑터(모의 승인), 수수료·내역 | orders, settings, config |
| `app/events.py` | **고객 이벤트·쿠폰**: 첫 방문·재방문·생일·시간 할인·쿠폰 발급/사용/복원 | customers, settings |
| `app/community.py` | **로컬 커뮤니티**: 동네 소식·단골 공지·동네 이벤트·공동 프로모션(매장/그룹 범위) | settings, stores |
| `app/visits.py` | **QR·NFC 유입 기록·통계**(개인정보 없음) | stores |
| `app/customers.py` | 회원·등급·포인트 원장·방문 이력·생일, **이벤트용 포인트 지급 공개 함수** | settings, stores |
| `app/inventory.py` | 재료·레시피, 결제 시 차감·취소 시 복원, 안전재고 경고 | stores |
| `app/reservations.py` | 예약 신청·확정·도착·노쇼·테이블 배정 | tables, stores |
| `app/reviews.py` | 별점·한 줄 평가·답글·숨김·평균 | orders, stores |
| `app/kitchen.py` | 주방 대기열·지연·알레르기·**경로 라벨·품절 연동 알림**·서빙 대기 | orders, catalog, tables |
| `app/stats.py` | 오늘/기간 매출·시간대·결제수단·카테고리·CSV | stores |
| `app/waiting.py` | 대기 접수·번호·개인 링크·호출·착석·노쇼, **ON/OFF·최대 인원 설정 적용** | customers, tables, notifier, settings |
| `app/notifier.py` | 알림 채널(브라우저/문자/카카오), 템플릿, 동의·야간 규칙, 이력 | settings |
| `app/qr.py` / `app/qrdesign.py` | 순수 파이썬 QR 인코더 / 디자인 렌더·검증 | – |
| `app/qrs.py` | QR URL·디자인 / **NFC 태그 URL(?via=nfc)** / 인쇄물 | qrs, settings, tables |
| `app/backup.py` | DB 스냅숏·자동 백업·복원 | store |
| `app/api.py` | URL → 모듈 라우팅, **계정 범위·매장 범위·권한 검사**, 오류 → HTTP 상태 | 모든 업무 모듈 |
| `app/web.py` | 화면 주소 ↔ HTML, 화면별 필요 권한 | config |
| `server.py` | HTTP 파싱, 쿠키→세션, 화면 권한 게이트, 시작 배너 | api, web, auth, store |

**의존 방향**: `server → api → 업무 모듈 → store/stores`. 업무 모듈 사이 호출은
`orders → catalog/customers/tables/inventory`, `waiting → customers/tables/notifier/orders`,
`kitchen → orders/catalog/tables`, `stand → qrs/tables`, `stores → settings/tables/catalog/staff/stats` 뿐이며
역방향 호출은 없다.

## 3. 사업자 계정(멀티테넌트)·매장 분리 구조

```
[요청] server → api.handle
  aid = 로그인 사용자의 accountId            ← 사업자 계정
  with stores.account_scope(aid):            ← 계정 범위(contextvar)
      sid = 세션 active_store (없으면 ?store= 또는 1)
      with stores.use(sid):                  ← 매장 범위(contextvar)
          라우팅 → 모듈 함수 → SQL 의 WHERE store_id = stores.current()
```

- **계정**: `staff.account_id` 가 같은 직원은 한 사업자다. 대표(첫 관리자)의 staff id 를 계정 id 로 쓴다.
- **매장 소유**: `stores.owner_id` = 사업자 계정. `stores.list_stores()` 는 계정 범위가 있으면 자기 매장만 준다.
- **가입**: 배포 하나에 여러 사업자가 가입한다. 첫 계정은 기본 매장(1)을 물려받고, 그 뒤 계정은 자기 매장·메뉴·테이블을 새로 만든다.
  소셜 로그인도 처음이면 같은 방식으로 계정을 만든다.
- **다른 계정 보호**: 다른 계정의 매장·그룹은 수정·전환 시 404(있는지도 알리지 않음), 세션이 남아 있어도 소속 매장으로 되돌린다.
- **기존 DB 이관**: `store._migrate_accounts()` 가 첫 관리자 계정으로 기존 매장·직원을 묶는다. 기존 매장은 공개 목록(`listed=1`) 유지.
- **컬럼**: `categories`, `menu_items`, `orders`, `customers`, `dining_tables`, `staff`, `attendance`,
  `waiting_tickets`, `service_calls`, `notifier_log`, `ingredients`, `recipes`, `ingredient_logs`,
  `reservations`, `reviews`, `staff_schedules`, `payments`, `coupons`, `customer_coupons`, `event_log`,
  `community_posts`, `visit_events` 에 `store_id`.
- **공개 주소**(로그인 없음): 손님은 `?store=` 또는 테이블 코드로 매장을 정한다.
  `/api/table/<코드>`, `/api/menu`, `/api/qr/<코드>.png`, `/api/payments/methods`, `/api/public/community` 등.
- **공개 매장 목록**: `stores.listed=1` 인 매장만(`portal.public_stores`). 새 매장은 기본 비공개이며 사장님이 설정에서 켠다.

## 4. 매장 그룹

- `store_groups`(owner_id, name, kind, settings) + `stores.group_id`.
- 그룹 통합 매출(`groups.summary`), 메뉴 일괄 복사(`groups.copy_menu`), 그룹 내 직원 이동(`groups.transfer_staff`),
  그룹 기본 설정(운영 모드·웨이팅·커뮤니티) 적용(`groups.apply_settings`).
- 그룹 글(로컬 커뮤니티)은 그룹 매장 손님에게 함께 보인다(매장이 커뮤니티를 켠 경우).

## 5. 권한

`config.PERMISSIONS` 에 11개 권한 키와 `ROLE_PERMISSIONS` 기본값이 있다.
역할은 사장님·점장·매니저·카운터·홀·주방·알바(시간제) 7종이다.
실제 권한 = 역할 기본값 ⊕ `staff.permissions`(JSON, 직원별 예외). 사장님은 항상 전부.

| API/화면 | 확인하는 권한 |
|---|---|
| `/api/state`, `/api/orders`(목록), 웨이팅 관리, 예약 관리 | `order.manage` |
| 주문 상태 변경(취소 제외) | `order.status` |
| 주문 취소·결제 되돌리기·환불 | `order.cancel` |
| 결제 확인(현금·입금·카드 확인)·결제 목록 | `order.manage` |
| 메뉴·카테고리·사진·추천 | `menu.edit` (가격만 `price.edit`) |
| 품절 | `soldout.manage` |
| 회원·리뷰·쿠폰 발급 | `customer.view` |
| 매출·정산·대시보드·매장 비교·QR/NFC 통계 | `sales.view` |
| 직원·근태·스케줄·급여·비밀번호 초기화 | `staff.manage` |
| 설정·테이블·구역·QR·인쇄·백업·매장·그룹·커뮤니티 설정 | `settings.edit` |
| 주방 화면 | `kitchen.view` |
| 내 계정·출퇴근 | 로그인만 |

## 6. 데이터 모델 (`data/mangjip.db`)

| 테이블 | 요약 |
|---|---|
| `stores` | 매장(`owner_id` 사업자 계정, `group_id`, `listed` 공개 여부, 상호·정보·사용 여부) |
| `store_groups` | 매장 그룹(`owner_id`, `kind` brand/region/direct/franchise, `settings` JSON) |
| `categories`, `menu_items` | 매장별 메뉴. `featured*`, `origin`, `allergens`, `spice`, `i18n` |
| `customers`, `point_events` | 매장별 회원·포인트 원장(`balance_after`) |
| `orders`, `order_items` | 주문 스냅숏. `channel`(table/pickup/delivery/preorder), `discount`, `coupon_id`, `transfer_depositor`, `subtotal`/`points_used`/`points_earned`, `receipt_*` |
| `payments` | 결제 기록(수단·금액·수수료·상태 PENDING/PAID/REFUNDED, PG 거래번호, `simulated`) |
| `coupons`, `customer_coupons` | 쿠폰 정의(이벤트·수동) / 고객별 발급·사용·만료 |
| `event_log` | 이벤트 적용 기록(첫 방문·재방문·생일·쿠폰) |
| `community_posts` | 로컬 커뮤니티 글(매장 또는 그룹 범위) |
| `visit_events` | QR/NFC 유입 기록(매장·테이블·via·경로) |
| `dining_tables`, `table_zones` | 구역별 테이블(`zone_id`, `code`, `label`, `seats`, `sort`, `active`) |
| `staff`, `staff_sessions`, `attendance` | 직원(`account_id`, `permissions`, `pay_type`, 급여), 세션(`active_store`), 출퇴근 |
| `staff_schedules` | 근무 스케줄(직원·날짜·시작·끝) |
| `ingredients`, `recipes`, `ingredient_logs` | 재료·메뉴별 소모량·입출고 기록(`IN/OUT/ADJUST/RESTORE`) |
| `reservations` | 예약(토큰·날짜·시간·인원·상태·테이블) |
| `reviews` | 리뷰(주문 1건 UNIQUE, 별점·한 줄·숨김·답글) |
| `waiting_tickets`, `waiting_counters` | 대기(토큰, 상태, 좌석, `purged`) / 번호 |
| `service_calls`, `notifier_log`, `push_subscriptions`, `voice_log` | 직원 호출 / 알림 이력 / 푸시 자리 / 음성 문장 |
| `settings`, `meta` | 매장별 설정(JSON) / `rev` |

- 주문 항목은 **주문 시점 가격을 복사**한다. 가격을 바꿔도 과거 매출은 그대로.
- 결제 금액 = `subtotal + (배달료) − discount(시간할인+쿠폰) − points_used`. 할인·쿠폰은 서버가 다시 계산한다.
- 주문 상태: `RESERVED → NEW → ACCEPTED → COOKING → DONE(조리완료·서빙 대기) → SERVED`.
  되돌리기 제한과 `CANCELED` 는 `orders.STATUS_FLOW` 한 곳에서 정의한다.
- 결제 상태: `UNPAID → PAID`(현금·입금 확인·카드 확인), `REFUNDED` 는 `payments` 행에 남는다.
- 예약 상태: `PENDING(신청) → CONFIRMED → ARRIVED / NOSHOW / CANCELED` (`reservations.FLOW`).
- 스키마 변경은 `store.py` 의 `_ADDED_COLUMNS`/`_migrate()` 가 기존 DB에 컬럼·테이블을 더해 준다.

## 7. 요청 흐름(예)

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

## 8. 인쇄물

- `stand.py` 가 테이블별 스탠드 PNG(200dpi)를 만들고 `pdf.py` 가 A4/B4/A3/A5/A6 규격에 맞춰 얹은 PDF를 만든다.
- 화면 인쇄는 `/print`(CSS `@page`), 파일 저장은 PDF. 파일명에 크기·배치가 들어간다.
- 테이블이 추가·이름 변경·비활성되면 다음 생성 때 자동 반영된다(매장별).

## 9. 백업·배포

- `backup.py`가 SQLite backup API로 `data/backups/backup-<태그>-<시각>.db`를 만든다.
  자동 1일 1회, 최근 7개 보관 — **만든 시각 기준**으로 정리하고 방금 만든 파일은 보호한다.
- 복원은 `confirm="복원"`을 요구하고, 실행 전 `before-restore` 백업을 남긴 뒤 덮어쓴다.
- 백업 파일은 **모든 매장**을 담는다. 매장별로 따로 백업하지 않는다.
- 배포 준비: `배포-준비.md`(HTTPS·방화벽·백업·장애 대응), 개인정보: `개인정보-처리방침-초안.md` + `/privacy`.

## 10. 확장 지점

| 앞으로 | 붙일 위치 | 지금 해 둔 것 |
|---|---|---|
| 실결제(PG)·부분 환불 | `orders.payment_method` 확장 + 웹훅 | 현금 확인 전이 한 곳 |
| 문자·카카오 실제 발송 | `notifier.INSTANCES`의 `StubChannel.send()` 교체 | 채널 인터페이스·동의·야간 규칙·이력 |
| 앱 닫아도 오는 푸시 | `push_subscriptions` + 서비스 워커 `push` 이벤트 | 구독 저장 스텁 |
| 예약 알림·손님 확정 안내 | `reservations` 상태 전이 → `notifier.send` | 상태·토큰·템플릿 구조 |
| 재고 자동 발주 | `inventory` 에 거래처·발주서 | 품절 제안·입출고 기록 |
| 급여 세무·명세서 | 회계 프로그램 연동 | 실제 근무시간·시급/월급 계산 |
| 리뷰 공개·쿠폰 | `reviews` 공개 목록·`customers` 쿠폰 | 별점·답글·숨김 |

## 11. 한계와 주의

- 음성 인식은 **브라우저(크롬 안드로이드)가 구글 서버로 보내 처리**한다. 우리 서버는 텍스트만 받는다.
- 브라우저 알림은 탭이 열려 있을 때만 온다. 실제 푸시는 배포·키·구독이 필요하다.
- 원산지·알레르기 정보의 정확성과 법적 표시 의무는 **매장 책임**이다.
- 사업자등록번호는 형식만 검사한다(진위확인·본인인증 없음).
- 예상 급여는 **참고용**이다. 세금·4대보험·급여명세서는 다루지 않는다.
- 예약·리뷰는 문자를 보내지 않는다. 리뷰 답글은 매장 내부 메모다.
- 로컬 시제품이라 서버는 `0.0.0.0`으로 열린다. 운영 전 HTTPS·접근제어가 필요하다.
- 브라우저가 없는 환경이라 화면은 `tools/dom_harness.py`(quickjs)로 렌더만 검사했다.
  실제 기기에서의 터치·스크린리더·TTS·색감 검증은 하지 못했다.
