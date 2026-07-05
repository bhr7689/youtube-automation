@echo off
chcp 65001 >nul
title 일본쇼츠 자동 프로그램

echo ============================================
echo  🎌 일본쇼츠 자동 프로그램
echo  📺 레퍼런스 트래커 + 🌸 번역봇 + ✂️ 컷편집
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: [1/4] 최신 버전 받아오기 (japan_shorts 개발 브랜치)
echo [1/4] 최신 버전 받는 중...
git fetch origin claude/new-session-rhtlol >nul 2>&1
if errorlevel 1 (
    echo    git fetch 실패 - 오프라인일 수 있어요. 기존 코드로 계속합니다.
) else (
    git checkout claude/new-session-rhtlol >nul 2>&1
    git pull origin claude/new-session-rhtlol
)
echo.

:: 폴더 확인
if not exist "jpshorts\backend\main.py" (
    echo [오류] jpshorts\backend 폴더가 안 보여요.
    echo        인터넷 연결 확인 후 다시 실행해주세요.
    pause
    exit /b 1
)

:: [2/4] 필요한 부품 설치 (처음 한 번만 오래 걸려요)
echo [2/4] 필요한 부품 설치 중...
pip install -r jpshorts\backend\requirements.txt --quiet

:: [3/4] 브라우저 자동 열기
echo [3/4] 브라우저 열기 (3초 후)...
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8787/"

:: [4/4] 서버 시작 (포트 8787) — UI + API 통합
echo [4/4] 서버 시작 (포트 8787)
echo.
echo  💡 .env 파일에 YOUTUBE_API_KEY 가 있으면 실제 유튜브 검색,
echo     없으면 데모 데이터로 작동해요.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
python -m uvicorn main:app --port 8787 --app-dir jpshorts\backend

pause
