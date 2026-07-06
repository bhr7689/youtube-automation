@echo off
chcp 65001 >nul
title 최신 파일 받아오기
cd /d "%~dp0"

echo ============================================
echo  📥 최신 파일 받아오기
echo  (인터넷에 있는 새 파일을 이 컴퓨터로 가져와요)
echo ============================================
echo.

echo 받아오는 중... 잠깐만 기다려주세요.
echo.

git fetch origin claude/youtube-discovery-dashboard-eqO5N
git checkout claude/youtube-discovery-dashboard-eqO5N
git pull origin claude/youtube-discovery-dashboard-eqO5N

echo.
if exist "일본쇼츠실행.bat" (
    echo ============================================
    echo  ✅ 다 받았어요!
    echo.
    echo  이제 이 폴더에서 '일본쇼츠실행.bat' 을
    echo  더블클릭 하면 프로그램이 켜져요.
    echo ============================================
) else (
    echo ============================================
    echo  ⚠️ 파일이 안 보여요. 인터넷 연결을 확인하고
    echo     이 파일을 다시 더블클릭 해주세요.
    echo ============================================
)
echo.
echo  이 창은 아무 키나 누르면 닫혀요.
pause >nul
