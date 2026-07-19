@echo off
chcp 65001 >nul
title 썸네일·제목 연구소 — 장르별 채널 공장

echo ============================================
echo  🎬 썸네일·제목 연구소
echo  (장르별 구간 분석 + 썸네일·제목 생성)
echo ============================================
echo.

:: 이 배치 파일이 있는 폴더로 이동
cd /d "%~dp0"

:: git pull (최신 코드 받기) — default 브랜치
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

:: .env 파일 확인 (없으면 생성)
if not exist ".env" (
    echo [안내] .env 파일이 없습니다. 앱의 '설정' 탭에서 키를 넣어도 됩니다.
    if exist ".env.example" copy .env.example .env >nul
)

:: 이전에 켜둔 앱이 8505 포트를 잡고 있으면 자동 정리 (중복 실행 방지)
echo [3/3] 이전 실행 정리 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8505 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

:: Streamlit 실행 (8505 포트 — 다른 툴과 충돌 안 함)
echo  연구소 시작 중... (브라우저가 자동으로 열립니다)
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
streamlit run thumbnail_title_lab.py --server.port 8505 --server.headless false

pause
