"""QR 코드 생성기 — 표준 라이브러리만 사용하는 순수 파이썬 구현.

바이트 모드(UTF-8), 오류정정 레벨 M·H, 버전 1~10 지원.
디자인 QR(가운데 배지)은 복원 여유가 큰 레벨 H 를 쓴다.
외부 패키지(qrcode/segno 등)나 인터넷 없이 동작한다.
"""

# 버전별 오류정정 레벨 M 블록 구조: (블록당 EC 코드워드 수, [(블록 수, 데이터 코드워드 수), ...])
_EC_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

# 버전별 오류정정 레벨 H 블록 구조 (가운데 배지용 — 복원 여유 30%)
_EC_H = {
    1: (17, [(1, 9)]),
    2: (28, [(1, 16)]),
    3: (22, [(2, 13)]),
    4: (16, [(4, 9)]),
    5: (22, [(2, 11), (2, 12)]),
    6: (28, [(4, 15)]),
    7: (26, [(4, 13), (1, 14)]),
    8: (26, [(4, 14), (2, 15)]),
    9: (24, [(4, 12), (4, 13)]),
    10: (28, [(6, 15), (2, 16)]),
}
_EC_TABLES = {"M": _EC_M, "H": _EC_H}
_ECL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

# 정렬 패턴 중심 좌표
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# 버전별 남는 비트 수
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _format_bits(ecl_bits, mask):
    data = (ecl_bits << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _version_bits(ver):
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return (ver << 12) | rem


def _make_codewords(text, version, level="M"):
    data = text.encode("utf-8")
    table = _EC_TABLES.get(level) or _EC_M
    ec_per_block, groups = table[version]
    total_data = sum(n * d for n, d in groups)

    bits = []

    def put(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    put(0b0100, 4)                      # 바이트 모드
    put(len(data), 8 if version <= 9 else 16)
    for b in data:
        put(b, 8)
    capacity = total_data * 8
    if len(bits) > capacity:
        raise ValueError("내용이 너무 깁니다")
    put(0, min(4, capacity - len(bits)))  # 종료자
    while len(bits) % 8:
        bits.append(0)
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < total_data:
        codewords.append(pad[i % 2])
        i += 1

    # 블록 분할 + EC 계산
    blocks, pos = [], 0
    for count, dlen in groups:
        for _ in range(count):
            chunk = codewords[pos:pos + dlen]
            pos += dlen
            blocks.append(chunk)
    ec_blocks = [_rs_remainder(b, _rs_divisor(ec_per_block)) for b in blocks]

    # 인터리브
    out = []
    maxlen = max(len(b) for b in blocks)
    for i in range(maxlen):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_per_block):
        for b in ec_blocks:
            out.append(b[i])
    return out


class _Matrix:
    def __init__(self, version):
        self.version = version
        self.size = version * 4 + 17
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set(self, col, row, dark, func=True):
        self.mod[row][col] = bool(dark)
        if func:
            self.fn[row][col] = True

    def draw_function_patterns(self):
        s = self.size
        # 파인더 패턴 + 분리자
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        dist = max(abs(dx), abs(dy))
                        self.set(x, y, dist not in (2, 4))
        # 타이밍 패턴
        for i in range(s):
            if not self.fn[6][i]:
                self.set(i, 6, i % 2 == 0)
            if not self.fn[i][6]:
                self.set(6, i, i % 2 == 0)
        # 정렬 패턴
        pos = _ALIGN[self.version]
        for i, cx in enumerate(pos):
            for j, cy in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        # 포맷 정보 영역 예약(임시로 밝게, 함수 모듈로 표시)
        for i in range(9):
            if not self.fn[8][i]:
                self.set(i, 8, False)
            if not self.fn[i][8]:
                self.set(8, i, False)
        for i in range(8):
            self.set(s - 1 - i, 8, False)
            self.set(8, s - 1 - i, False)
        # 항상 어두운 모듈
        self.set(8, s - 8, True)

    def draw_codewords(self, codewords):
        s = self.size
        bits = [(b >> i) & 1 for b in codewords for i in range(7, -1, -1)]
        idx = 0
        right = s - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    y = (s - 1 - vert) if upward else vert
                    if not self.fn[y][x] and idx < len(bits):
                        self.mod[y][x] = bits[idx] == 1
                        idx += 1
            right -= 2

    def draw_format(self, mask, ecl_bits=0b00):
        s = self.size
        bits = _format_bits(ecl_bits, mask)
        for i in range(6):
            self.set(8, i, (bits >> i) & 1)
        self.set(8, 7, (bits >> 6) & 1)
        self.set(8, 8, (bits >> 7) & 1)
        self.set(7, 8, (bits >> 8) & 1)
        for i in range(9, 15):
            self.set(14 - i, 8, (bits >> i) & 1)
        for i in range(8):
            self.set(s - 1 - i, 8, (bits >> i) & 1)
        for i in range(8, 15):
            self.set(8, s - 15 + i, (bits >> i) & 1)
        self.set(8, s - 8, True)

    def draw_version(self):
        if self.version < 7:
            return
        s = self.size
        bits = _version_bits(self.version)
        for i in range(18):
            bit = (bits >> i) & 1
            a = s - 11 + i % 3
            b = i // 3
            self.set(a, b, bit)
            self.set(b, a, bit)

    def apply_mask(self, mask):
        f = [
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        ][mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self):
        s = self.size
        m = self.mod
        score = 0
        # 규칙 1: 같은 색 5개 이상 연속
        for line in list(m) + [list(col) for col in zip(*m)]:
            run, prev = 1, line[0]
            for v in line[1:]:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run, prev = 1, v
            if run >= 5:
                score += 3 + (run - 5)
        # 규칙 2: 2x2 같은 색 블록
        for y in range(s - 1):
            for x in range(s - 1):
                v = m[y][x]
                if v == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        # 규칙 3: 파인더 비슷한 패턴
        pat_a = [True, False, True, True, True, False, True, False, False, False, False]
        pat_b = pat_a[::-1]
        for line in list(m) + [list(col) for col in zip(*m)]:
            for i in range(s - 10):
                w = line[i:i + 11]
                if w == pat_a or w == pat_b:
                    score += 40
        # 규칙 4: 어두운 모듈 비율
        dark = sum(sum(1 for v in row if v) for row in m)
        total = s * s
        score += 10 * (abs(dark * 100 // total - 50) // 5)
        return score


def capacity_bytes(version, level="M"):
    table = _EC_TABLES.get(level) or _EC_M
    return sum(n * d for n, d in table[version][1])


def encode(text, level="M"):
    """텍스트를 QR 모듈 행렬(list[list[bool]])로 변환한다. level 은 M 또는 H."""
    level = (level or "M").upper()
    if level not in _EC_TABLES:
        level = "M"
    data_len = len(text.encode("utf-8"))
    version = None
    for v in range(1, 11):
        header = 4 + (8 if v <= 9 else 16)
        if header + data_len * 8 <= capacity_bytes(v, level) * 8:
            version = v
            break
    if version is None:
        raise ValueError("QR로 만들기에는 내용이 너무 깁니다")

    codewords = _make_codewords(text, version, level)
    ecl_bits = _ECL_BITS.get(level, 0b00)
    best = None
    for mask in range(8):
        mat = _Matrix(version)
        mat.draw_function_patterns()
        mat.draw_codewords(codewords)
        mat.draw_version()
        mat.apply_mask(mask)
        mat.draw_format(mask, ecl_bits)
        p = mat.penalty()
        if best is None or p < best[0]:
            best = (p, mat)
    return best[1].mod
