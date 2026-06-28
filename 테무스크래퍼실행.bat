@echo off
chcp 65001 >nul
title 테무 식품 스크래퍼

echo ============================================
echo   테무 식품 카테고리 상품 분석기
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: ── 바탕화면에 바로가기 자동 생성 ──
set "SHORTCUT=%USERPROFILE%\Desktop\테무스크래퍼실행.lnk"
if not exist "%SHORTCUT%" (
    echo [자동] 바탕화면에 바로가기를 만드는 중...
    powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath='%~f0'; $sc.WorkingDirectory='%~dp0'; $sc.IconLocation='shell32.dll,175'; $sc.Save()"
    echo    완료! 다음부터는 바탕화면 바로가기를 더블클릭하세요.
    echo.
)

:: pip 의존성 설치
echo [1/3] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
pip install playwright -q --disable-pip-version-check
echo.

:: Chromium 설치 (없으면 자동 설치)
echo [2/3] Chromium 브라우저 확인 중...
python -m playwright install chromium
echo    Chromium 준비 완료!
echo.

:: Streamlit 실행
echo [3/3] 스크래퍼 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run temu_scraper_app.py --server.port 8502 --server.headless false

pause
