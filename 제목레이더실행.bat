@echo off
chcp 65001 >nul
title 제목 알고리즘 분석 — 시드 키워드 자동 발굴

echo ============================================
echo  🔬 제목 알고리즘 분석 (제목 레이더)
echo  - 히든 젬 시드 발굴 (구독자 적은데 조회수 폭발)
echo  - 글로벌 15개국 시드 비교
echo  - 쇼츠/롱폼 따로 분석
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
    echo        .env.example 을 복사해서 .env 로 만들고 YOUTUBE_API_KEY 를 입력하세요.
    echo.
    copy .env.example .env >nul
    echo    .env 파일을 생성했습니다. 메모장으로 열어 API 키를 입력하세요.
    notepad .env
    pause
)

:: Streamlit 실행 (8503 포트 — 메인 8501 / 역설계 8502 와 동시 실행 가능)
echo [3/3] 제목 레이더 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run title_analyzer_app.py --server.port 8503 --server.headless false

pause
