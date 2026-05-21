@echo off
REM ============================================================
REM  유튜브 음악 채널 자동화 대시보드 - Windows 원클릭 실행 스크립트
REM
REM  사용법: 이 파일을 더블클릭하면 됩니다.
REM   - 최초 1회: 의존성을 자동으로 설치합니다 (3~5분).
REM   - 이후: 즉시 실행됩니다.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   YouTube Automation Dashboard - Local Launcher (Windows)
echo ============================================================
echo.

REM --- 1) Python 존재 확인 ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python이 설치되어 있지 않습니다.
    echo.
    echo 다음 중 하나로 Python을 먼저 설치하세요:
    echo   1. Microsoft Store에서 "Python 3.11" 검색 후 설치 ^(가장 쉬움^)
    echo   2. https://www.python.org/downloads/ 에서 다운로드
    echo      ^(설치 시 "Add Python to PATH" 체크박스 반드시 켜세요^)
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] %PYVER% 발견

REM --- 2) ffmpeg 존재 확인 (탭 3·4용, 없어도 1·2는 동작) ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [WARN] ffmpeg이 PATH에 없습니다. 탭 3 ^(영상 합성^)·탭 4 ^(SRT^)는 동작하지 않습니다.
    echo        설치하려면 PowerShell을 관리자 권한으로 열고:
    echo            winget install Gyan.FFmpeg
    echo        후 PC를 재시작하세요. 탭 1·2만 쓰실 거면 무시해도 됩니다.
    echo.
) else (
    echo [OK] ffmpeg 발견
)

REM --- 3) 가상환경 준비 ---
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [SETUP] 가상환경 생성 중... ^(최초 1회만^)
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 가상환경 생성 실패.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

REM --- 4) 의존성 설치 (lockfile로 한 번만) ---
if not exist ".venv\.deps_installed" (
    echo.
    echo [SETUP] 의존성 설치 중... ^(3~5분 소요, 최초 1회만^)
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] 의존성 설치 실패. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    echo done > .venv\.deps_installed
    echo [OK] 의존성 설치 완료
)

REM --- 5) .env 파일 확인 ---
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo.
        echo [INFO] .env 파일을 생성했습니다. 메모장으로 열어 API 키를 입력하세요.
        echo        그 후 다시 이 파일을 실행하세요.
        notepad .env
        echo.
        echo API 키 입력 후 저장하셨다면 아무 키나 누르세요...
        pause >nul
    )
)

REM --- 6) Streamlit 실행 ---
echo.
echo ============================================================
echo   브라우저가 자동으로 열립니다. http://localhost:8501
echo   종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo ============================================================
echo.

streamlit run app.py

endlocal
