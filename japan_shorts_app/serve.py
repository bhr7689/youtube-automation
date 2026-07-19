"""일본쇼츠 자동 프로그램 - 정적 시안 서버.

사용법:
    python serve.py            # 기본 포트 8505
    python serve.py 8000       # 다른 포트
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

DEFAULT_PORT = 8505


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    root = Path(__file__).resolve().parent

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

    with socketserver.TCPServer(("0.0.0.0", port), Handler) as httpd:
        print(f"🌸 일본쇼츠 자동 프로그램 시안 서버")
        print(f"   http://localhost:{port}/")
        print(f"   Ctrl+C 로 종료")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
