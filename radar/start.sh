#!/usr/bin/env bash
# Mac / Linux 실행
set -e
cd "$(dirname "$0")"
echo "=== 경쟁 채널 인텔리전스 레이더 ==="
pip install -r requirements.txt -q
[ ! -f .env ] && cp .env.example .env && echo ".env 생성됨 — 키를 입력하세요: nano .env"
streamlit run radar_app.py --server.port 8502
