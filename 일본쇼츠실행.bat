@echo off
chcp 65001 >nul
title 일본쇼츠 자동 프로그램 (서버)

echo ============================================
echo  🎌 일본쇼츠 자동 프로그램  [서버 모드]
echo  📺 레퍼런스 트래커 + 🌸 번역봇 + ✂️ 컷편집
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: [1/4] 최신 버전 받아오기
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

:: [3/4] 사무실 다른 PC 접속 주소 확인
set LAN_IP=
for /f %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*'} ^| Select-Object -First 1).IPAddress" 2^>nul') do set LAN_IP=%%i

echo [3/4] 접속 주소
echo.
echo   ┌─────────────────────────────────────────────┐
echo   │  이 컴퓨터:     http://localhost:8787
if defined LAN_IP echo   │  다른 PC 에서:  http://%LAN_IP%:8787
if defined LAN_IP echo   │                 (다른 PC의 '일본쇼츠_접속.bat' 에 %LAN_IP% 입력)
echo   └─────────────────────────────────────────────┘
echo.
echo   ⚠️ 처음 실행 시 Windows 방화벽 창이 뜨면 [액세스 허용] 을 눌러주세요.
echo   💾 학습 데이터는 이 서버 컴퓨터에만 쌓입니다 (3대가 공유).
echo.

:: 브라우저 자동 열기
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8787/"

:: [4/4] 서버 시작 (포트 8787, 사무실 내 다른 PC 접속 허용)
echo [4/4] 서버 시작 - 종료하려면 이 창을 닫거나 Ctrl+C
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8787 --app-dir jpshorts\backend

pause
