#!/usr/bin/env bash
# Mac / Linux 실행 스크립트
# 사용법: bash start.sh

set -e
cd "$(dirname "$0")"

echo "============================================"
echo " 유튜브 음악 채널 자동화 대시보드"
echo "============================================"

# git pull
echo "[1/3] 최신 코드 받는 중..."
git pull origin claude/youtube-discovery-dashboard-eqO5N || echo "  git pull 실패 - 기존 코드로 계속"

# pip 설치
echo "[2/3] 패키지 확인 중..."
pip install -r requirements.txt -q

# .env 확인
if [ ! -f .env ]; then
    echo "[경고] .env 파일이 없습니다. .env.example 을 복사합니다."
    cp .env.example .env
    echo "  .env 파일을 열어 API 키를 입력하세요: nano .env"
fi

# 실행
echo "[3/3] 대시보드 시작... (http://localhost:8501)"
streamlit run app.py --server.port 8501
