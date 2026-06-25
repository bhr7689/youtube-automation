@echo off
chcp 65001 >nul
title 음악 이어붙이기 처음 설치

echo ============================================
echo  음악 이어붙이기 - 처음 설치
echo ============================================
echo.

set INSTALL_DIR=%USERPROFILE%\youtube-automation
set BRANCH=claude/youtube-discovery-dashboard-eqO5N

where git >nul 2>nul
if errorlevel 1 goto need_git
echo [1/5] Git OK

where python >nul 2>nul
if errorlevel 1 goto need_python
echo [2/5] Python OK

where ffmpeg >nul 2>nul
if errorlevel 1 goto need_ffmpeg
echo [3/5] ffmpeg OK
goto clone_or_pull

:need_git
echo [필요] Git 이 없어요. 다운로드 페이지를 열어드릴게요.
echo        설치 후 이 창을 닫고 다시 더블클릭하세요.
start https://git-scm.com/download/win
pause
exit /b 1

:need_python
echo [필요] Python 이 없어요. 다운로드 페이지를 열어드릴게요.
echo        설치할 때 Add Python to PATH 체크박스 꼭 켜주세요.
start https://www.python.org/downloads/
pause
exit /b 1

:need_ffmpeg
echo [필요] ffmpeg 가 없어요. winget 으로 자동 설치 시도합니다.
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
where ffmpeg >nul 2>nul
if errorlevel 1 goto ffmpeg_manual
echo [3/5] ffmpeg OK
goto clone_or_pull

:ffmpeg_manual
echo 자동 설치 실패. 수동 설치 필요.
echo 1) 페이지에서 ffmpeg-release-full.zip 받기
echo 2) C:\ffmpeg 폴더에 압축 풀기
echo 3) 환경변수 Path 에 C:\ffmpeg\bin 추가
echo 4) 이 창 닫고 다시 더블클릭
start https://www.gyan.dev/ffmpeg/builds/
pause
exit /b 1

:clone_or_pull
if exist "%INSTALL_DIR%\.git" goto update_repo
echo [4/5] 새로 받는 중...
cd /d "%USERPROFILE%"
git clone -b %BRANCH% https://github.com/bhr7689/youtube-automation.git
if errorlevel 1 goto clone_failed
goto install_pkg

:update_repo
echo [4/5] 이미 폴더가 있어요. 최신 코드로 업데이트 중...
cd /d "%INSTALL_DIR%"
git pull origin %BRANCH%
goto install_pkg

:clone_failed
echo [실패] 저장소 받기 실패. 인터넷 연결 또는 권한 확인.
pause
exit /b 1

:install_pkg
echo [5/5] 파이썬 패키지 확인...
pip install streamlit -q --disable-pip-version-check

echo.
echo ============================================
echo  준비 완료. 음악 이어붙이기 시작합니다.
echo  브라우저가 자동으로 열려요. 포트 8503
echo  종료하려면 이 창을 닫으세요.
echo ============================================
echo.

cd /d "%INSTALL_DIR%"
streamlit run "%INSTALL_DIR%\music_merger\app.py" --server.port 8503 --server.headless false

pause
