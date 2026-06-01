@echo off
chcp 65001 > nul
title 토토쌤의 떡상 채널 Finder FREE

echo.
echo  💧 토토쌤의 떡상 채널 Finder FREE
echo  ─────────────────────────────────
echo.

:: 저장소 경로 (필요 시 수정)
cd /d "%~dp0"

:: 최신 코드 받기
echo  [1/3] 최신 업데이트 확인 중...
git pull origin claude/practical-mendel-8xXP7 2>nul || echo  (업데이트 건너뜀)

echo.
echo  [2/3] 브라우저를 열고 있습니다...
start http://localhost:8502

echo.
echo  [3/3] Finder 시작 중... (창을 닫으면 종료됩니다)
echo.

:: 포트 8502 사용 (기존 app.py와 충돌 방지)
streamlit run loui.py --server.port 8502 --server.headless false

pause
