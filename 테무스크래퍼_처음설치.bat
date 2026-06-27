@echo off
chcp 65001 >nul
title 테무 스크래퍼 — 처음 설치

echo ================================================
echo   테무 식품 스크래퍼 — 처음 설치 프로그램
echo ================================================
echo.
echo  이 파일을 더블클릭하면 모든 설치가 자동으로 됩니다.
echo  완료 후 바탕화면에 바로가기가 생깁니다.
echo.
pause

:: ── 설치 위치 고정 (바꾸고 싶으면 아래 경로 수정) ──
set "INSTALL_DIR=%USERPROFILE%\Documents\youtube-automation"

echo.
echo [1/5] 설치 위치: %INSTALL_DIR%
echo.

:: git 설치 확인
where git >nul 2>&1
if errorlevel 1 (
    echo [오류] Git이 설치되어 있지 않습니다.
    echo.
    echo  Git 다운로드: https://git-scm.com/download/win
    echo  설치 후 이 파일을 다시 실행하세요.
    pause
    exit /b 1
)

:: python 설치 확인
where python >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo  Python 다운로드: https://www.python.org/downloads/
    echo  설치 시 "Add Python to PATH" 반드시 체크하세요!
    pause
    exit /b 1
)

:: ── 폴더 있으면 pull, 없으면 clone ──
if exist "%INSTALL_DIR%\.git" (
    echo [2/5] 이미 설치됨. 최신 코드로 업데이트 중...
    cd /d "%INSTALL_DIR%"
    git pull origin claude/temu-food-scraper-tool-rg3sna
) else (
    echo [2/5] 코드 다운로드 중... (처음 한 번, 1-2분 소요)
    git clone -b claude/temu-food-scraper-tool-rg3sna https://github.com/bhr7689/youtube-automation.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [오류] 다운로드 실패. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)
echo.

:: ── 패키지 설치 ──
echo [3/5] 필요한 패키지 설치 중... (처음 한 번, 2-3분 소요)
pip install -r requirements.txt -q --disable-pip-version-check
pip install playwright beautifulsoup4 lxml -q --disable-pip-version-check
echo.

:: ── Chromium 설치 ──
echo [4/5] Chromium 브라우저 설치 중... (처음 한 번, 1-2분 소요)
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()" >nul 2>&1
if errorlevel 1 (
    playwright install chromium
    if errorlevel 1 (
        echo [오류] Chromium 설치 실패.
        pause
        exit /b 1
    )
)
echo    완료!
echo.

:: ── 바탕화면 바로가기 생성 ──
echo [5/5] 바탕화면에 바로가기 만드는 중...
set "BAT=%INSTALL_DIR%\테무스크래퍼실행.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\테무스크래퍼실행.lnk"

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$sc = $ws.CreateShortcut('%SHORTCUT%');" ^
    "$sc.TargetPath = '%BAT%';" ^
    "$sc.WorkingDirectory = '%INSTALL_DIR%';" ^
    "$sc.IconLocation = 'shell32.dll,175';" ^
    "$sc.Description = '테무 식품 스크래퍼';" ^
    "$sc.Save()"

echo.
echo ================================================
echo   설치 완료!
echo.
echo   바탕화면의 [테무스크래퍼실행] 을
echo   더블클릭하면 바로 실행됩니다.
echo ================================================
echo.
pause
