@echo off
chcp 65001 >nul
title 경쟁 채널 인텔리전스 레이더

echo ============================================
echo  경쟁 채널 인텔리전스 레이더
echo ============================================
echo.

cd /d "%~dp0"

:: 패키지 설치
echo [1/3] 패키지 확인 중...
pip install -r requirements.txt -q --disable-pip-version-check
echo.

:: .env 확인
if not exist ".env" (
    echo [안내] .env 파일을 생성합니다. API 키를 입력하세요.
    copy .env.example .env >nul
    notepad .env
    pause
)

:: 실행
echo [2/3] 앱 시작 중... (브라우저가 자동으로 열립니다)
echo  주소: http://localhost:8502
echo  종료: 이 창을 닫거나 Ctrl+C
echo.
streamlit run radar_app.py --server.port 8502

pause
