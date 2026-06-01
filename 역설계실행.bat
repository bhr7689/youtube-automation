@echo off
chcp 65001 >nul
title 곡 역설계 — 곡·작사가 프롬프트 도서관

echo ============================================
echo  🔎 곡 역설계 단독 툴
echo  (URL 한 줄 → 곡 프롬프트 + 작사가 프롬프트)
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

:: Streamlit 실행 (8502 포트 — 메인 대시보드 8501 과 동시 실행 가능)
echo [3/3] 역설계 툴 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run reverse_app.py --server.port 8502 --server.headless false

pause
