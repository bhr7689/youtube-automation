@echo off
chcp 65001 >nul
title 일본쇼츠 자동 프로그램 (서버)

echo ============================================
echo  🎌 일본쇼츠 자동 프로그램  [서버 모드]
echo  🎬 쇼츠 후킹 대본 + 🧬 SRE 역설계 + 🔊 TTS
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: [1/4] 최신 버전 받아오기
echo [1/4] 최신 버전 받는 중...
git fetch origin claude/youtube-discovery-dashboard-eqO5N >nul 2>&1
if errorlevel 1 (
    echo    git fetch 실패 - 오프라인일 수 있어요. 기존 코드로 계속합니다.
) else (
    git checkout claude/youtube-discovery-dashboard-eqO5N >nul 2>&1
    git pull origin claude/youtube-discovery-dashboard-eqO5N
)
echo.

:: 폴더 확인
if not exist "jpshorts\backend\main.py" (
    echo [오류] jpshorts\backend 폴더가 안 보여요.
    echo        인터넷 연결 확인 후 다시 실행해주세요.
    pause
    exit /b 1
)

:: [2/4] Python 찾기 (python -> py -> 자동설치)
echo [2/4] Python 확인 중...
set "PYEXE="
python --version >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE ( py -3 --version >nul 2>&1 && set "PYEXE=py -3" )
if not defined PYEXE (
    where py >nul 2>&1 && (
        echo    Python 이 없어서 자동 설치를 시도해요... 몇 분 걸릴 수 있어요.
        py install 3.13
        py -3 --version >nul 2>&1 && set "PYEXE=py -3"
    )
)
if not defined PYEXE (
    echo.
    echo   [필요] Python 설치가 필요해요. 다운로드 페이지를 엽니다.
    echo   ▶ 노란 버튼으로 받은 파일을 실행하고,
    echo     설치 첫 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크한 뒤 Install Now!
    echo   ▶ 설치가 끝나면 이 창을 닫고 이 파일을 다시 더블클릭하세요.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo    Python OK (%PYEXE%)

:: [3/4] 필요한 부품 설치 (처음 한 번만 오래 걸려요)
echo [3/4] 필요한 부품 설치 중... (처음엔 몇 분)
%PYEXE% -m pip install --upgrade pip --quiet
%PYEXE% -m pip install -r jpshorts\backend\requirements.txt --quiet

:: 접속 주소(다른 PC용)
set LAN_IP=
for /f %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*'} ^| Select-Object -First 1).IPAddress" 2^>nul') do set LAN_IP=%%i

echo.
echo   ┌─────────────────────────────────────────────┐
echo   │  이 컴퓨터:     http://localhost:8787
if defined LAN_IP echo   │  다른 PC 에서:  http://%LAN_IP%:8787
echo   └─────────────────────────────────────────────┘
echo.
echo   ⚠️ 처음 실행 시 Windows 방화벽 창이 뜨면 [액세스 허용] 을 눌러주세요.
echo   ⏳ 화면이 안 뜨면 10~20초 기다렸다가 브라우저에서 새로고침(F5) 하세요.
echo.

:: 브라우저 자동 열기 (서버가 뜰 시간을 주려고 9초 뒤)
start "" cmd /c "timeout /t 9 /nobreak >nul && start http://localhost:8787/"

:: [4/4] 서버 시작 (포트 8787)
echo [4/4] 서버 시작 - 종료하려면 이 창을 닫거나 Ctrl+C
echo.
%PYEXE% -m uvicorn main:app --host 0.0.0.0 --port 8787 --app-dir jpshorts\backend

pause
