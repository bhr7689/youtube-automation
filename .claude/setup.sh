#!/usr/bin/env bash
# SessionStart hook: 매 세션 시작 시 의존성 / 시스템 도구를 준비한다.
# 4개 탭(레퍼런스 발굴, AI 스토리텔링, 영상 합성, SRT 동기화) 모두 실행 가능하게 한다.
set -euo pipefail

cd "$(dirname "$0")/.."

# 1) ffmpeg / ffprobe — 탭 3·4에서 필요
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[setup] installing ffmpeg..." >&2
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends ffmpeg >/dev/null 2>&1 || true
  fi
fi

# 2) Python 의존성. cryptography/cffi 가 시스템 데비안 패키지와 충돌하는 환경
#    (pyo3 panic) 을 회피하기 위해 --ignore-installed 로 사용자 영역에 재설치.
echo "[setup] installing python deps..." >&2
pip install --quiet --ignore-installed cryptography cffi >/dev/null 2>&1 || true
pip install --quiet -r requirements.txt >/dev/null 2>&1 || true

echo "[setup] ready. run: streamlit run app.py" >&2
