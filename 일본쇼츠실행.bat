@echo off
chcp 65001 >nul
title 일본쇼츠 자동 프로그램 — 시안 미리보기

echo ============================================
echo  🎌 일본쇼츠 자동 프로그램 (시안 미리보기)
echo  📺 레퍼런스 트래커 + 🌸 번역봇 + ✂️ 컷편집
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: [1/3] 최신 시안 받아오기 (japan_shorts 개발 브랜치)
echo [1/3] 최신 시안 받는 중...
git fetch origin claude/new-session-rhtlol >nul 2>&1
if errorlevel 1 (
    echo    git fetch 실패 - 오프라인일 수 있어요. 기존 코드로 계속합니다.
) else (
    git checkout claude/new-session-rhtlol >nul 2>&1
    git pull origin claude/new-session-rhtlol
)
echo.

:: 폴더 확인
if not exist "japan_shorts_app\serve.py" (
    echo [오류] japan_shorts_app 폴더가 안 보여요.
    echo        인터넷 연결 확인 후 다시 실행해주세요.
    pause
    exit /b 1
)

:: [2/3] 브라우저 자동 열기
echo [2/3] 브라우저 열기 (2초 후)...
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8505/"

:: [3/3] 시안 서버 시작 (포트 8505)
echo [3/3] 시안 서버 시작 (포트 8505)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
cd japan_shorts_app
python serve.py 8505

pause
