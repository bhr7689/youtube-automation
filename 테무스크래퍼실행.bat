@echo off
chcp 65001 >nul
title 테무 식품 스크래퍼

echo ============================================
echo   테무 식품 카테고리 상품 분석기
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: git pull (최신 코드 받기)
echo [1/4] 최신 코드 받는 중...
git pull origin claude/temu-food-scraper-tool-rg3sna
if errorlevel 1 (
    echo    git pull 실패 - 오프라인이거나 오류. 기존 코드로 계속합니다.
)
echo.

:: pip 의존성 설치/업데이트
echo [2/4] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
pip install playwright beautifulsoup4 lxml -q --disable-pip-version-check
echo.

:: Playwright Chromium 브라우저 확인 및 설치
echo [3/4] Chromium 브라우저 확인 중...
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()" >nul 2>&1
if errorlevel 1 (
    echo    Chromium 설치 중... (최초 1회만 실행, 약 1-2분 소요)
    playwright install chromium
    if errorlevel 1 (
        echo    [오류] Chromium 설치 실패. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    echo    Chromium 설치 완료!
) else (
    echo    Chromium OK
)
echo.

:: Streamlit 실행
echo [4/4] 스크래퍼 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run temu_scraper_app.py --server.port 8502 --server.headless false

pause
