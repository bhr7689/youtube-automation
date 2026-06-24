@echo off
chcp 65001 >nul
title 음악 이어붙이기 — 1/2/3/6시간 영상 만들기

echo ============================================
echo  🎵 음악 이어붙이기
echo  (음악 + 자연의 소리 + 이미지 → MP3/MP4)
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: git pull (최신 코드 받기)
echo [1/3] 최신 코드 받는 중...
git pull origin claude/youtube-discovery-dashboard-eqO5N
if errorlevel 1 (
    echo    git pull 실패 - 오프라인이거나 오류. 기존 코드로 계속합니다.
)
echo.

:: pip 의존성 확인 (streamlit 만 있으면 동작)
echo [2/3] 패키지 확인 중...
pip install streamlit -q --disable-pip-version-check
echo.

:: ffmpeg 확인
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [경고] ffmpeg 를 찾을 수 없습니다.
    echo        음악 합치기 / 영상 만들기에 ffmpeg 가 꼭 필요해요.
    echo        https://ffmpeg.org/download.html 에서 받아 설치하세요.
    echo.
    pause
    exit /b 1
)

:: Streamlit 실행 (8503 포트 — 기존 8501/8502 와 동시 실행 가능)
echo [3/3] 음악 이어붙이기 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run music_merger/app.py --server.port 8503 --server.headless false

pause
