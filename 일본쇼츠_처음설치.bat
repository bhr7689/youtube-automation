@echo off
chcp 65001 >nul
title 쇼츠 자동화 - 처음 설치 (새 컴퓨터)

echo ============================================
echo   쇼츠 자동화 프로그램 - 처음 설치
echo   (SRE 역설계 / 쇼츠 후킹 대본 / TTS / 레퍼런스 채널)
echo   * 이 파일은 "새 컴퓨터에서 한 번만" 실행하면 돼요.
echo   * 다음부터는 바탕화면 [쇼츠자동화] 아이콘만 더블클릭.
echo ============================================
echo.

set "INSTALL_DIR=%USERPROFILE%\youtube-automation"
set "BRANCH=claude/youtube-discovery-dashboard-eqO5N"
set "REPO=https://github.com/bhr7689/youtube-automation.git"

:: ── [1/5] Git ──────────────────────────────
where git >nul 2>nul
if not errorlevel 1 goto have_git
echo [1/5] Git 이 없어요. 자동 설치를 시도합니다(winget)...
winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements >nul 2>nul
where git >nul 2>nul
if not errorlevel 1 goto have_git
echo.
echo    ▶ Git 자동설치를 시도했어요. 방금 설치됐다면 이 창을 닫고
echo      "일본쇼츠_처음설치.bat" 를 다시 더블클릭하면 인식됩니다.
echo      계속 안 되면 아래 페이지에서 직접 설치 후 다시 실행하세요.
start https://git-scm.com/download/win
pause
exit /b 1
:have_git
echo [1/5] Git OK

:: ── [2/5] Python (python -> py -> 자동설치) ──
set "PYEXE="
python --version >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE ( py -3 --version >nul 2>&1 && set "PYEXE=py -3" )
if not defined PYEXE (
    where py >nul 2>&1 && (
        echo [2/5] Python 자동 설치 중... 몇 분 걸릴 수 있어요.
        py install 3.13
        py -3 --version >nul 2>&1 && set "PYEXE=py -3"
    )
)
if defined PYEXE goto have_py
echo [2/5] Python 이 없어요. winget 으로 자동 설치를 시도합니다...
winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements >nul 2>nul
python --version >nul 2>&1 && set "PYEXE=python"
if defined PYEXE goto have_py
echo.
echo    ▶ Python 자동설치를 시도했어요. 방금 설치됐다면 이 창을 닫고
echo      "일본쇼츠_처음설치.bat" 를 다시 더블클릭하면 인식됩니다.
echo      직접 설치할 때는 첫 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크!
start https://www.python.org/downloads/
pause
exit /b 1
:have_py
echo [2/5] Python OK (%PYEXE%)

:: ── [3/5] 코드 받기 ────────────────────────
if exist "%INSTALL_DIR%\.git" goto pull
echo [3/5] 코드를 새로 받는 중...
cd /d "%USERPROFILE%"
git clone -b %BRANCH% %REPO%
if errorlevel 1 goto clone_fail
goto deps
:pull
echo [3/5] 이미 폴더가 있어요 - 최신 코드로 업데이트 중...
cd /d "%INSTALL_DIR%"
git checkout %BRANCH% >nul 2>nul
git pull origin %BRANCH%
goto deps
:clone_fail
echo.
echo   [실패] 코드 받기 실패 - 인터넷 연결을 확인하세요.
echo          (비공개 저장소면 GitHub 로그인 창이 뜰 수 있어요. 로그인 후 다시 실행)
pause
exit /b 1

:: ── [4/5] 부품 설치 ────────────────────────
:deps
echo [4/5] 필요한 부품 설치 중... (처음엔 몇 분 걸려요)
cd /d "%INSTALL_DIR%"
%PYEXE% -m pip install --upgrade pip -q
%PYEXE% -m pip install -r jpshorts\backend\requirements.txt

:: ── [5/5] 바탕화면 아이콘 ──────────────────
echo [5/5] 바탕화면에 [쇼츠자동화] 아이콘 만드는 중...
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $lnk=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\쇼츠자동화.lnk'); $lnk.TargetPath='%INSTALL_DIR%\일본쇼츠실행.bat'; $lnk.WorkingDirectory='%INSTALL_DIR%'; $lnk.IconLocation='%INSTALL_DIR%\assets\jp_shorts.ico'; $lnk.Save()" >nul 2>nul

echo.
echo ============================================
echo   ✅ 설치 완료!
echo.
echo   지금 바로 프로그램을 시작합니다. 브라우저가 자동으로 열려요.
echo   다음부터는 바탕화면 [쇼츠자동화] 아이콘만 더블클릭하면 됩니다.
echo.
echo   ▶ 중요: 화면이 열리면 왼쪽 메뉴에서 아래를 쓸 수 있어요
echo       - 🎬 쇼츠 후킹 대본 (제목/대본/1.5초 SRT 자막/한국어 TTS)
echo       - 🧬 SRE 역설계 · 🏷️ 카테고리별 공식 · 📺 레퍼런스 채널
echo   ▶ AI 기능(LLM 심화 / TTS 음성)을 쓰려면 화면 안
echo     [🔑 키 연결] 또는 [⚙️ 설정]에서 OpenAI 키를 한 번 넣어주세요.
echo     (키는 이 컴퓨터에만 저장됩니다. 인터넷/깃허브에 안 올라가요)
echo ============================================
echo.
pause
call "%INSTALL_DIR%\일본쇼츠실행.bat"
