@echo off
chcp 65001 >nul
title 쇼핑 숏폼 대본 자동화

echo ============================================
echo   쇼핑 숏폼 대본 자동화
echo ============================================
echo.

cd /d "%~dp0"

:: 바탕화면 바로가기 자동 생성
set "SHORTCUT=%USERPROFILE%\Desktop\대본자동화실행.lnk"
if not exist "%SHORTCUT%" (
    echo [자동] 바탕화면에 바로가기 만드는 중...
    powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath='%~f0'; $sc.WorkingDirectory='%~dp0'; $sc.IconLocation='shell32.dll,71'; $sc.Save()"
    echo    완료!
    echo.
)

echo [1/3] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
pip install playwright -q --disable-pip-version-check
echo.

echo [2/3] Chromium 확인 중...
python -m playwright install chromium
echo.

echo [3/3] 대본 자동화 시작 중...
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 누르세요.
echo.
streamlit run shortform_script_app.py --server.port 8503 --server.headless false

pause
