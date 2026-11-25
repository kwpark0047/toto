"""전역 설정. 환경변수로 일부 값을 바꿀 수 있다."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 매장 정보 (시제품 기본값 — 메뉴 관리 화면에서 메뉴만 바꾸고, 매장 정보는 여기서 바꾼다)
STORE = {
    "name": os.environ.get("STORE_NAME", "맛집"),
    "tagline": os.environ.get("STORE_TAGLINE", "김포 운양동 · 한식·분식"),
    "address": "경기도 김포시 운양동",
    "phone": "031-000-0000",
    "tables": int(os.environ.get("STORE_TABLES", "8")),  # 처음 만들 때 까는 기본 테이블 수
}

_DEFAULT_DB = "/tmp/mangjip.db" if os.environ.get("VERCEL") else os.path.join(BASE_DIR, "data", "mangjip.db")
DB_PATH = os.environ.get("MENU_DB", _DEFAULT_DB)
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
IMAGE_DIR = os.path.join(PUBLIC_DIR, "images")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# 주방 지연 경고 기준(분)
DELAY_WARN_MIN = 5
DELAY_LATE_MIN = 10

STATUS_LABELS = {
    "NEW": "새 주문",
    "ACCEPTED": "접수",
    "COOKING": "조리중",
    "DONE": "조리 완료(서빙 대기)",
    "SERVED": "서빙 완료",
    "CANCELED": "취소",
}
PAYMENT_LABELS = {"UNPAID": "결제 전", "PAID": "현금 결제 완료"}

# ------------------------------------------------------------------ 로그인
# 시제품용 사업자 계정. 실제 운영에서는 외부 인증(OTP·소셜 등)으로 교체해야 한다.
OWNER_USERNAME = os.environ.get("OWNER_ID", "owner")
OWNER_PASSWORD = os.environ.get("OWNER_PW", "mangjip1234")
OWNER_NAME = os.environ.get("OWNER_NAME", "강원 사장님")
OWNER_PHONE = os.environ.get("OWNER_PHONE", "")

SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))
SESSION_COOKIE = "mj_sid"
LOGIN_MAX_FAILS = 5          # 같은 아이디로 연속 실패 허용 횟수
LOGIN_LOCK_SECONDS = 300     # 넘으면 이만큼 기다려야 다시 시도
LOGIN_FAIL_WINDOW = 600      # 실패 횟수를 세는 구간
PASSWORD_MIN_LEN = 4         # 시제품 최소 길이(실서비스는 8자 이상 + 2단계 인증 권장)

ROLE_LABELS = {"admin": "관리자", "manager": "매니저", "counter": "카운터", "kitchen": "주방",
              "part": "알바(시간제)"}
ROLE_ORDER = ["admin", "manager", "counter", "kitchen", "part"]
ROLE_HINTS = {
    "admin": "사장님 · 전부",
    "manager": "매니저 · 설정 변경만 제외",
    "counter": "카운터 · 주문·결제·회원·매출",
    "kitchen": "주방 · 주방 화면·조리 상태·품절",
    "part": "알바(시간제) · 주문 받기·상태 변경만",
}

# 세분 권한 — 역할별 기본값을 두고, 직원마다 체크박스로 예외를 준다.
PERMISSIONS = [
    ("menu.edit", "메뉴 수정", "메뉴 추가·수정·삭제"),
    ("price.edit", "가격 변경", "메뉴 가격 바꾸기"),
    ("soldout.manage", "품절 처리", "품절 켜기·끄기"),
    ("order.status", "주문 상태 변경", "주방 화면에서 접수·조리·서빙"),
    ("order.manage", "주문·결제 확인", "주문 목록·현금 결제 확인"),
    ("order.cancel", "주문 취소·환불", "주문 취소와 결제 되돌리기"),
    ("customer.view", "고객 정보 열람", "회원 목록·상세·연락처"),
    ("sales.view", "매출 조회", "매출·정산 화면과 CSV"),
    ("staff.manage", "직원 관리", "직원 추가·수정·비밀번호 초기화·스케줄"),
    ("settings.edit", "설정 변경", "매장 정보·포인트·알림·백업"),
    ("kitchen.view", "주방 화면", "주방 KDS 열기"),
]
PERMISSION_CODES = [p[0] for p in PERMISSIONS]
PERMISSION_LABELS = {p[0]: p[1] for p in PERMISSIONS}
ROLE_PERMISSIONS = {
    "admin": list(PERMISSION_CODES),
    "manager": ["menu.edit", "price.edit", "soldout.manage", "order.status", "order.manage",
                "order.cancel", "customer.view", "sales.view", "staff.manage", "kitchen.view"],
    "counter": ["soldout.manage", "order.manage", "order.cancel", "customer.view", "sales.view"],
    "kitchen": ["soldout.manage", "order.status", "kitchen.view"],
    "part": ["order.manage", "order.status"],
}
PART_TIME_ROLE = "part"    # 시급제로 계산하는 역할

# ------------------------------------------------------------------ 회원·포인트
# 등급 자동 산정 기준. 위에서부터 먼저 맞는 등급을 쓴다.
MEMBER_GRADES = [
    {"code": "VIP", "label": "VIP", "minVisits": 5, "minSpend": 100000, "tone": "brand"},
    {"code": "REGULAR", "label": "단골", "minVisits": 3, "minSpend": 30000, "tone": "amber"},
]
MEMBER_BASE_GRADE = {"code": "NEW", "label": "신규", "minVisits": 0, "minSpend": 0, "tone": ""}
POINTS_RATE = float(os.environ.get("POINTS_RATE", "1.0"))   # 결제 금액의 % 적립
POINTS_UNIT_WON = 1                                        # 1포인트 = 1원
POINTS_MAX_USE_RATIO = 0.5                                 # 한 주문에서 결제 금액의 최대 50%까지 사용
