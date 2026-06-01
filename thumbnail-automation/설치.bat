@echo off
chcp 65001 > nul
echo ================================================
echo   썸네일 자동화 시스템 - 최초 설치
echo ================================================
echo.

REM Python 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo python.org 에서 Python 3.10 이상을 설치하세요.
    pause
    exit /b 1
)

REM Git 확인
git --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Git이 설치되어 있지 않습니다.
    echo git-scm.com 에서 Git을 설치하세요.
    pause
    exit /b 1
)

echo [1/4] 저장소 다운로드 중...
cd /d "%USERPROFILE%"
if exist "youtube-automation" (
    echo     이미 존재 - 최신 코드 업데이트 중...
    cd youtube-automation
    git pull origin claude/inspiring-meitner-C7Nvv
) else (
    git clone https://github.com/bhr7789/youtube-automation.git
    cd youtube-automation
    git fetch origin claude/inspiring-meitner-C7Nvv
    git checkout FETCH_HEAD -- thumbnail-automation
)

echo.
echo [2/4] 의존성 설치 중...
cd thumbnail-automation
pip install -r requirements.txt

echo.
echo [3/4] 환경 설정 파일 생성 중...
if not exist .env (
    copy .env.example .env
    echo     .env 파일이 생성되었습니다.
) else (
    echo     .env 파일이 이미 존재합니다.
)

echo.
echo [4/4] 바탕화면에 실행 파일 생성 중...
set DESKTOP=%USERPROFILE%\Desktop
set BATFILE=%DESKTOP%\썸네일실행.bat

(
echo @echo off
echo chcp 65001 ^> nul
echo cd /d "%%USERPROFILE%%\youtube-automation\thumbnail-automation"
echo git pull origin claude/inspiring-meitner-C7Nvv 2^>nul
echo set PYTHONPATH=%%USERPROFILE%%\youtube-automation\thumbnail-automation
echo start http://localhost:8501
echo timeout /t 2 /nobreak ^> nul
echo streamlit run review/app.py
) > "%BATFILE%"

echo.
echo ================================================
echo   설치 완료!
echo ================================================
echo.
echo 지금 .env 파일에 API 키를 입력하세요:
echo   - YOUTUBE_API_KEY  (필수)
echo   - GEMINI_API_KEY   (분석 + 이미지생성)
echo   - OPENAI_API_KEY   (DALL-E 3)
echo.
echo .env 파일 위치:
echo   %USERPROFILE%\youtube-automation\thumbnail-automation\.env
echo.
notepad .env
echo.
echo 바탕화면의 [썸네일실행.bat]을 더블클릭하면 실행됩니다!
pause
