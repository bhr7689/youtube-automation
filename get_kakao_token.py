"""get_kakao_token.py — 카카오 refresh token 1회 발급 도우미.

사장님 PC 에서 딱 한 번 실행:
    python get_kakao_token.py

준비: 카카오 개발자(https://developers.kakao.com) 에서
  1) 애플리케이션 추가 → REST API 키 확인
  2) 카카오 로그인 활성화 ON
  3) Redirect URI 에  http://localhost:8910/  등록
  4) 동의항목 → '카카오톡 메시지 전송(talk_message)' 사용

실행하면 브라우저로 로그인 → 자동으로 토큰을 받아 화면에 출력.
그 KAKAO_REFRESH_TOKEN 을 설정(.env) 또는 GitHub Secrets 에 저장하면 끝.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://localhost:8910/"
_code_holder: dict = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        code = urllib.parse.parse_qs(q).get("code", [""])[0]
        _code_holder["code"] = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>인증 완료! 이 창을 닫고 터미널로 돌아가세요.</h2>".encode())

    def log_message(self, *a):
        pass


def main():
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip() or input("REST API 키 입력: ").strip()
    auth = ("https://kauth.kakao.com/oauth/authorize?response_type=code"
            f"&client_id={rest_key}&redirect_uri={urllib.parse.quote(REDIRECT)}"
            "&scope=talk_message")

    srv = http.server.HTTPServer(("localhost", 8910), _Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("브라우저에서 카카오 로그인/동의를 진행하세요…")
    webbrowser.open(auth)

    import time
    for _ in range(120):
        if _code_holder.get("code"):
            break
        time.sleep(1)
    code = _code_holder.get("code")
    if not code:
        print("인증 코드를 받지 못했습니다. Redirect URI 등록을 확인하세요.")
        return

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": rest_key,
        "redirect_uri": REDIRECT, "code": code,
    }).encode()
    with urllib.request.urlopen("https://kauth.kakao.com/oauth/token", data=body, timeout=20) as r:
        tok = json.loads(r.read().decode())
    print("\n===== 발급 완료 =====")
    print("KAKAO_REST_API_KEY =", rest_key)
    print("KAKAO_REFRESH_TOKEN =", tok.get("refresh_token", "(없음)"))
    print("\n위 두 값을 설정(.env) 또는 GitHub Secrets 에 저장하세요.")


if __name__ == "__main__":
    main()
