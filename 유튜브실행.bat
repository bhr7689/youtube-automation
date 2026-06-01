@echo off
chcp 65001 >nul
title 유튜브 음악 채널 자동화

echo ============================================
echo  유튜브 음악 채널 자동화 대시보드
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

:: pip 의존성 설치/업데이트
echo [2/3] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
echo.

:: .env 파일 확인
if not exist ".env" (
    echo [경고] .env 파일이 없습니다.
    echo        .env.example 을 복사해서 .env 로 만들고 API 키를 입력하세요.
    echo.
    copy .env.example .env >nul
    echo    .env 파일을 생성했습니다. 메모장으로 열어 API 키를 입력하세요.
    notepad .env
    pause
)

:: ffmpeg 확인
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [경고] ffmpeg 를 찾을 수 없습니다.
    echo        영상 합성 기능을 사용하려면 ffmpeg 를 설치하세요.
    echo        https://ffmpeg.org/download.html
    echo.
)

:: Streamlit 실행
echo [3/3] 대시보드 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run app.py --server.port 8501 --server.headless false

pause
