@echo off
chcp 65001 >nul
title 일본쇼츠 자동 프로그램
cd /d "%~dp0"

echo ============================================
echo   🎬 일본쇼츠 자동 프로그램 (RefTracker)
echo ============================================
echo.

echo [1/3] 최신 코드 받는 중...
git pull

echo [2/3] 필요한 것 설치 중... (처음 한 번만 오래 걸려요)
pip install -r requirements.txt >nul 2>&1

echo [3/3] 프로그램 켜는 중...
echo.
echo   잠시 후 브라우저가 자동으로 열립니다.
echo   안 열리면 주소창에 직접:  http://127.0.0.1:8600
echo.
start "" http://127.0.0.1:8600
python -m backend.main

pause
