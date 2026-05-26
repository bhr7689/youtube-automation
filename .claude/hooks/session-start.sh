#!/bin/bash
# SessionStart 훅 — Claude Code on the web 세션이 시작될 때 환경을 자동 셋업.
# 컨테이너는 매 세션 새로 클론되므로, 여기서 ffmpeg + 파이썬 의존성을 갖춰야
# streamlit/orchestrator/pipeline 실행과 검증이 곧바로 가능하다. (멱등·비대화형)
set -euo pipefail

# 원격(웹) 세션에서만 실행. 로컬 개발 환경은 건드리지 않는다.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# 1) ffmpeg/ffprobe — 영상 합성·인코딩(media_core/pipeline)에 필수. 이미 있으면 건너뜀.
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[hook] ffmpeg 설치 중..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq ffmpeg
  else
    echo "[hook] ⚠️ apt-get 없음 — ffmpeg 자동 설치 불가(인코딩 단계에서 실패할 수 있음)."
  fi
fi

# 2) 파이썬 의존성. 컨테이너 캐시를 활용하려 --upgrade 없이 일반 install.
echo "[hook] pip 의존성 설치 중..."
python -m pip install -q -r requirements.txt

# 3) cffi 보정 — 일부 컨테이너에서 _cffi_backend 가 빠져 google.generativeai /
#    googleapiclient(→cryptography) import 가 깨진다. 깨졌을 때만 재설치.
if ! python -c "import _cffi_backend" >/dev/null 2>&1; then
  echo "[hook] _cffi_backend 누락 → cffi 재설치..."
  python -m pip install -q --force-reinstall cffi
fi

echo "[hook] ✅ 환경 셋업 완료 (ffmpeg + 파이썬 의존성)."
