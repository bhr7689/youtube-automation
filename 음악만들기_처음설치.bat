@echo off
chcp 65001 >nul
title 음악 이어붙이기 — 처음 설치 + 실행

echo ============================================
echo   🎵 음악 이어붙이기 — 처음 설치
echo ============================================
echo.

set "INSTALL_DIR=%USERPROFILE%\youtube-automation"
set "REPO_URL=https://github.com/bhr7689/youtube-automation.git"
set "BRANCH=claude/youtube-discovery-dashboard-eqO5N"

:: ───────────────────────────── 1) Git ─────────────────────────────
where git >nul 2>&1
if errorlevel 1 (
    echo [필요] Git 이 설치 안 돼 있어요.
    echo        다운로드 페이지를 열어드릴게요. 설치 후 이 창을 닫고 다시 더블클릭하세요.
    start https://git-scm.com/download/win
    pause
    exit /b 1
)
echo [1/5] Git OK

:: ───────────────────────────── 2) Python ─────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [필요] Python 이 설치 안 돼 있어요.
    echo        설치할 때 ★ "Add Python to PATH" 체크박스 꼭 켜세요! ★
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [2/5] Python OK

:: ───────────────────────────── 3) ffmpeg ─────────────────────────────
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [필요] ffmpeg 가 설치 안 돼 있어요. (음악/영상 만들기에 꼭 필요)
    echo        winget 으로 자동 설치를 시도할게요...
    winget install --id=Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    where ffmpeg >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [실패] 자동 설치 실패. 수동으로 받아주세요.
        echo        1) 아래 페이지에서 "ffmpeg-release-full.7z" 또는 .zip 받기
        echo        2) C:\ffmpeg 같은 폴더에 압축 풀기
        echo        3) Windows 검색 → "환경 변수" → Path 에 "C:\ffmpeg\bin" 추가
        echo        4) 이 창 닫고 다시 더블클릭하세요.
        start https://www.gyan.dev/ffmpeg/builds/
        pause
        exit /b 1
    )
)
echo [3/5] ffmpeg OK

:: ───────────────────────────── 4) 저장소 클론/업데이트 ─────────────────────────────
if exist "%INSTALL_DIR%\.git" (
    echo [4/5] 이미 폴더가 있어요. 최신 코드로 업데이트...
    cd /d "%INSTALL_DIR%"
    git pull origin %BRANCH%
    if errorlevel 1 (
        echo        git pull 실패 - 오프라인이거나 충돌. 기존 코드로 계속합니다.
    )
) else (
    echo [4/5] %INSTALL_DIR% 에 새로 받는 중...
    cd /d "%USERPROFILE%"
    git clone -b %BRANCH% %REPO_URL%
    if errorlevel 1 (
        echo [실패] 저장소 받기 실패. 인터넷 연결 또는 권한을 확인하세요.
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)

:: ───────────────────────────── 5) streamlit 확인 ─────────────────────────────
echo [5/5] 파이썬 패키지 확인...
pip install streamlit -q --disable-pip-version-check
if errorlevel 1 (
    echo [실패] streamlit 설치 실패.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   ✅ 준비 완료! 음악 이어붙이기 시작합니다
echo   브라우저가 자동으로 열려요. (포트 8503)
echo   종료하려면 이 창을 닫으세요.
echo ============================================
echo.

streamlit run music_merger/app.py --server.port 8503 --server.headless false

pause
