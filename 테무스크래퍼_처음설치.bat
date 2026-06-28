@echo off
chcp 65001 >nul 2>&1
title 테무 스크래퍼 처음 설치

echo ================================================
echo   테무 식품 스크래퍼 - 처음 설치 프로그램
echo ================================================
echo.

:: ── Git 확인 ──
echo [확인 1/3] Git 설치 확인 중...
git --version
if errorlevel 1 (
    echo.
    echo ★ Git이 없습니다. 아래 주소에서 먼저 설치하세요.
    echo.
    echo    https://git-scm.com/download/win
    echo.
    echo    설치할 때 모든 옵션 기본값으로 Next 누르면 됩니다.
    echo    설치 후 이 파일을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

echo.

:: ── Python 확인 ──
echo [확인 2/3] Python 설치 확인 중...
python --version
if errorlevel 1 (
    echo.
    echo ★ Python이 없습니다. 아래 주소에서 먼저 설치하세요.
    echo.
    echo    https://www.python.org/downloads/
    echo.
    echo    설치할 때 맨 아래 "Add Python to PATH" 체크 필수!
    echo    설치 후 이 파일을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

echo.

:: ── pip 확인 ──
echo [확인 3/3] pip 확인 중...
pip --version
if errorlevel 1 (
    echo.
    echo ★ pip가 없습니다. Python을 다시 설치해주세요.
    echo    설치 시 "Add Python to PATH" 체크 필수!
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   기본 환경 확인 완료! 설치를 시작합니다.
echo ================================================
echo.
pause

:: ── 설치 위치 ──
set "INSTALL_DIR=%USERPROFILE%\Documents\youtube-automation"
echo 설치 위치: %INSTALL_DIR%
echo.

:: ── 코드 다운로드 ──
if exist "%INSTALL_DIR%\.git" (
    echo [1/4] 이미 설치됨. 최신 코드로 업데이트 중...
    cd /d "%INSTALL_DIR%"
    git pull origin claude/temu-food-scraper-tool-rg3sna
    if errorlevel 1 (
        echo.
        echo ★ 업데이트 실패. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
) else (
    echo [1/4] 코드 다운로드 중... 1~2분 소요됩니다.
    git clone -b claude/temu-food-scraper-tool-rg3sna https://github.com/bhr7689/youtube-automation.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo.
        echo ★ 다운로드 실패. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)

echo.

:: ── 패키지 설치 ──
echo [2/4] 필요한 패키지 설치 중... 2~3분 소요됩니다.
pip install -r requirements.txt -q --disable-pip-version-check
pip install playwright -q --disable-pip-version-check
echo    패키지 설치 완료
echo.

:: ── Chromium 설치 ──
echo [3/4] Chromium 브라우저 설치 중... 1~2분 소요됩니다.
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ★ Chromium 설치 실패. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
)
echo    Chromium 설치 완료
echo.

:: ── 바탕화면 바로가기 ──
echo [4/4] 바탕화면에 바로가기 만드는 중...
set "BAT=%INSTALL_DIR%\테무스크래퍼실행.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\테무스크래퍼실행.lnk"

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath='%BAT%'; $sc.WorkingDirectory='%INSTALL_DIR%'; $sc.IconLocation='shell32.dll,175'; $sc.Save()"

echo    바로가기 생성 완료
echo.
echo ================================================
echo   설치 완료!
echo.
echo   이제 바탕화면의 [테무스크래퍼실행] 을
echo   더블클릭하면 바로 실행됩니다.
echo ================================================
echo.
pause
