@echo off
chcp 65001 >nul
title 보컬 분리(Demucs) 설치
echo ============================================================
echo   보컬 분리(Demucs) 설치 - 가사 없는 곡 인식 정확도 향상
echo ============================================================
echo.
echo  * 처음 한 번만 설치하면 됩니다.
echo  * 용량이 커서(torch 포함) 5~20분 걸릴 수 있어요. 창을 닫지 마세요.
echo.
cd /d "%USERPROFILE%\youtube-automation"
echo [1/3] 가상환경 활성화...
call .venv\Scripts\activate
if errorlevel 1 (
    echo.
    echo [오류] .venv 가상환경을 찾지 못했습니다.
    echo        대시보드 실행 .bat 과 같은 폴더에서 이 파일을 실행하세요.
    echo.
    pause
    exit /b 1
)
echo [2/3] pip 업그레이드...
python -m pip install --upgrade pip
echo [3/3] demucs 설치 중... (보컬 분리 엔진)
python -m pip install demucs
if errorlevel 1 (
    echo.
    echo [오류] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 시도하세요.
    echo.
    pause
    exit /b 1
)
echo.
echo ============================================================
echo   설치 완료!
echo   대시보드를 다시 실행하면 '보컬 분리' 체크박스가 켜집니다.
echo ============================================================
echo.
pause
