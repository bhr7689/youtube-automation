@echo off
chcp 65001 >nul
title 음악 이어붙이기

echo ============================================
echo  음악 이어붙이기
echo  음악 + 자연의 소리 + 이미지 - MP3/MP4
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] 최신 코드 받는 중...
git pull origin claude/youtube-discovery-dashboard-eqO5N
echo.

echo [2/3] 패키지 확인 중...
pip install streamlit -q --disable-pip-version-check
echo.

where ffmpeg >nul 2>nul
if errorlevel 1 goto need_ffmpeg
goto run_app

:need_ffmpeg
echo [경고] ffmpeg 를 찾을 수 없습니다.
echo        음악 합치기 / 영상 만들기에 ffmpeg 가 꼭 필요해요.
echo        https://www.gyan.dev/ffmpeg/builds/ 에서 받아 설치하세요.
pause
exit /b 1

:run_app
echo [3/3] 음악 이어붙이기 시작 중. 브라우저가 자동으로 열립니다.
echo        종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run "%~dp0music_merger\app.py" --server.port 8503 --server.headless false

pause
