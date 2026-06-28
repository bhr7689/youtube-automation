@echo off
chcp 65001 >nul
title 채널 설명·해시태그 생성기 — 알고리즘 + 의식의 흐름

echo ============================================
echo  🎬 채널 설명·해시태그 자동 생성기
echo  (유튜브 링크 → SEO + 감성 끌어당김 설명)
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] 최신 코드 받는 중...
git pull origin claude/youtube-discovery-dashboard-eqO5N
if errorlevel 1 (
    echo    git pull 실패 - 오프라인이거나 오류. 기존 코드로 계속합니다.
)
echo.

echo [2/3] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
echo.

if not exist ".env" (
    echo [경고] .env 파일이 없습니다.
    echo        .env.example 을 복사해서 .env 로 만들고
    echo        YOUTUBE_API_KEY 와 GEMINI_API_KEY 를 입력하세요.
    echo.
    if exist ".env.example" copy .env.example .env >nul
    notepad .env
    pause
)

echo [3/3] 채널 설명 생성기 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run channel_desc_app.py --server.port 8504 --server.headless false

pause
