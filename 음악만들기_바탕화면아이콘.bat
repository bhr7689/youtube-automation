@echo off
chcp 65001 >nul
title 음악 이어붙이기 바탕화면 아이콘 만들기
cd /d "%~dp0"

echo ============================================
echo  🎵 바탕화면 아이콘 만들기
echo  (딱 한 번만 - 바탕화면에 음악 아이콘이 생겨요^)
echo ============================================
echo.
echo  만드는 중...

set "FOLDER=%~dp0"
set "TARGET=%FOLDER%음악만들기실행.bat"
set "ICON=%FOLDER%assets\music_merger.ico"
set "LINK=%USERPROFILE%\Desktop\음악이어붙이기.lnk"

powershell -NoProfile -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut('%LINK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%FOLDER%';" ^
  "$s.IconLocation='%ICON%';" ^
  "$s.Description='음악 이어붙이기 - 켜기';" ^
  "$s.Save()"

if exist "%LINK%" (
    echo.
    echo ============================================
    echo  ✅ 완성!
    echo.
    echo  바탕화면에 '음악이어붙이기' 🎵 아이콘이 생겼어요.
    echo  이제 그 아이콘만 두 번 누르면 바로 켜져요.
    echo ============================================
) else (
    echo.
    echo  ⚠️ 아이콘을 못 만들었어요. 이 파일을 다시 눌러보세요.
)
echo.
echo  아무 키나 누르면 닫혀요.
pause >nul
