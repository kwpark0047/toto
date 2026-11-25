#!/usr/bin/env python3
"""맛집 QR 메뉴판 주문 플랫폼 — 로컬 시제품 서버.

실행:
    python3 server.py                 # http://localhost:8000
    python3 server.py --port 8100     # 포트 바꾸기
    python3 server.py --reset         # 저장된 주문·회원·직원 데이터를 지우고 처음부터

처음 실행하면 /login 에서 '가입'(매장 이름 + 아이디·비밀번호)으로 사업자 계정을 만든다.
외부 서비스·인터넷 없이 동작한다(파이썬 표준 라이브러리만 사용).
"""
import argparse
import json
import os
import signal
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from app import api, auth, backup, config, settings, staff, store, tables, web, waiting

BODY_LIMIT = 6 * 1024 * 1024  # 사진 업로드 포함


class Handler(BaseHTTPRequestHandler):
    server_version = "MangjipPrototype/2.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    # -------------------------------------------------- 공통
    def _headers(self, status, ctype, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            if isinstance(v, (list, tuple)):
                for item in v:
                    self.send_header(k, item)
            else:
                self.send_header(k, v)
        self.end_headers()

    def _send(self, status, ctype, body, extra=None):
        self._headers(status, ctype, len(body), extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status, html, extra=None):
        self._send(status, "text/html; charset=utf-8", html.encode("utf-8"),
                   {"Cache-Control": "no-store", **(extra or {})})

    def _base_url(self):
        host = self.headers.get("Host") or f"localhost:{config.PORT}"
        return f"http://{host}"

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > BODY_LIMIT:
            return None
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _client_ip(self):
        return self.client_address[0] if self.client_address else ""

    def _handle(self, method):
        parts = urlsplit(self.path)
        path = parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        token = auth.token_from_cookie(self.headers.get("Cookie"))
        user = auth.user_for_token(token)

        if path.startswith("/api/"):
            body = self._read_body() if method in ("POST", "PATCH", "PUT") else {}
            if body is None:
                return self._send(400, "application/json; charset=utf-8",
                                  b'{"error":"\\uC694\\uCCAD \\uD615\\uC2DD\\uC774 \\uC798\\uBABB\\uB418\\uC5C8\\uC2B5\\uB2C8\\uB2E4"}')
            try:
                res = api.handle(method, path, query, body, self._base_url(),
                                 self.headers.get("Host", ""), user=user, token=token,
                                 ip=self._client_ip(),
                                 ua=self.headers.get("User-Agent", ""),
                                 cookies=self.headers.get("Cookie", ""))
            except Exception as e:  # 마지막 안전망
                import traceback
                traceback.print_exc()
                return self._send(500, "application/json; charset=utf-8",
                                  json.dumps({"error": str(e)}, ensure_ascii=False).encode())
            return self._send(res.status, res.content_type, res.body, res.headers)

        # 화면/정적 파일 — 로그인·역할 확인
        perms = web.required_perms(path)
        if perms is not None:
            if not user:
                nxt = quote(path + (("?" + parts.query) if parts.query else ""), safe="/?=&")
                return self._html(302, "", {"Location": f"/login?next={nxt}",
                                            "Cache-Control": "no-store"})
            if perms and not any(auth.has_perm(user, p) for p in perms):
                return self._html(403, self._denied_html(user, perms))
        if web.guest_only(path) and user:
            return self._html(302, "", {"Location": "/admin", "Cache-Control": "no-store"})

        try:
            file_path, ctype = web.resolve(path)
        except web.NotFound:
            body = ("<h1>404 — 없는 주소입니다</h1>"
                    "<p><a href='/'>처음으로</a> · <a href='/login'>로그인</a></p>").encode("utf-8")
            return self._send(404, "text/html; charset=utf-8", body)
        body = web.read_file(file_path)
        cache = "no-store" if ctype.startswith("text/html") else "public, max-age=3600"
        self._send(200, ctype, body, {"Cache-Control": cache})

    def _denied_html(self, user, perms=None):
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>권한이 없습니다</title>
<link rel="stylesheet" href="/assets/base.css"></head>
<body><main class="wrap page" style="max-width:560px;margin-top:60px">
<div class="card pad">
  <h1 style="font-size:26px">권한이 없습니다</h1>
  <p class="muted" style="line-height:1.6">
    {user['name']} 님({user['roleLabel']})은 이 화면을 볼 수 없습니다.<br>
    필요한 권한: <b>{", ".join(config.PERMISSION_LABELS.get(p, p) for p in (perms or [])) or "-"}</b><br>
    사장님(관리자)이 직원 화면에서 권한을 주면 열립니다.
  </p>
  <div class="row" style="gap:8px;margin-top:16px">
    <a class="btn primary" href="/admin">주문 화면으로</a>
    <a class="btn ghost" href="/kitchen">주방 화면</a>
  </div>
</div></main></body></html>""".encode("utf-8").decode("utf-8")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_HEAD(self):
        self._handle("GET")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def banner():
    ip = lan_ip()
    store_name = settings.public()["name"]
    tlist = tables.active_tables()
    first_code = tlist[0]["code"] if tlist else "1"
    print("=" * 62)
    print(f"  {store_name} — QR 메뉴판 주문 시제품 (로컬 실행)")
    print("=" * 62)
    if not staff.has_owner():
        print("  처음이시면  http://localhost:%d/signup 에서 가입해 주세요" % config.PORT)
    print(f"  로그인      http://localhost:{config.PORT}/login")
    print(f"  고객 화면   http://localhost:{config.PORT}/t/{first_code}  (활성 테이블 {len(tlist)}개)")
    print(f"  웨이팅 접수 http://localhost:{config.PORT}/wait")
    print(f"  대기 보드   http://localhost:{config.PORT}/wait/board")
    print(f"  사장님 화면 http://localhost:{config.PORT}/admin")
    print(f"  주방 화면   http://localhost:{config.PORT}/kitchen")
    print(f"  메뉴 관리   http://localhost:{config.PORT}/menu")
    print(f"  회원 관리   http://localhost:{config.PORT}/customers")
    print(f"  직원 관리   http://localhost:{config.PORT}/staff")
    print(f"  테이블      http://localhost:{config.PORT}/tables")
    print(f"  매장 설정   http://localhost:{config.PORT}/settings")
    print(f"  매출·정산   http://localhost:{config.PORT}/revenue")
    print(f"  재고·재료   http://localhost:{config.PORT}/inventory")
    print(f"  예약 관리   http://localhost:{config.PORT}/reservations")
    print(f"  리뷰        http://localhost:{config.PORT}/reviews")
    print(f"  매장 전환   http://localhost:{config.PORT}/stores")
    print(f"  QR 인쇄     http://localhost:{config.PORT}/qr")
    if ip:
        print(f"  휴대폰에서  http://{ip}:{config.PORT}/{first_code}")
    print("-" * 62)
    print("  실제 결제·문자 발송·외부 전송 없음. Ctrl+C 로 종료.")
    print("=" * 62, flush=True)


def main():
    p = argparse.ArgumentParser(description="맛집 QR 메뉴판 시제품 서버")
    p.add_argument("--port", type=int, default=config.PORT)
    p.add_argument("--host", default=config.HOST)
    p.add_argument("--reset", action="store_true", help="주문·회원·직원 데이터를 지우고 처음 상태로")
    args = p.parse_args()

    config.PORT = args.port
    config.HOST = args.host
    if args.reset and os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
        for suffix in ("-wal", "-shm"):
            if os.path.exists(config.DB_PATH + suffix):
                os.remove(config.DB_PATH + suffix)
        print("기존 데이터를 지웠습니다.")
    store.init()
    waiting.cleanup()
    try:
        backup.daily()          # 하루 1회 자동 백업(최근 7개 보관)
    except Exception as e:
        print(f"자동 백업을 건너뛰었습니다: {e}")

    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    srv.daemon_threads = True
    banner()
    signal.signal(signal.SIGTERM, lambda *a: srv.shutdown())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
