@echo off
chcp 65001 >nul
title 썸네일·제목 연구소 바탕화면 아이콘 만들기
cd /d "%~dp0"

echo ============================================
echo  🎨 바탕화면 아이콘 만들기
echo  (딱 한 번만 - 바탕화면에 🎬 버튼이 생겨요^)
echo ============================================
echo.
echo  만드는 중...

set "FOLDER=%~dp0"
set "TARGET=%FOLDER%썸네일제목분석기실행.bat"
set "ICON=%FOLDER%assets\thumb_lab.ico"
set "LINK=%USERPROFILE%\Desktop\썸네일제목연구소.lnk"

powershell -NoProfile -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut('%LINK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory='%FOLDER%';" ^
  "$s.IconLocation='%ICON%';" ^
  "$s.Description='썸네일·제목 연구소 - 켜기';" ^
  "$s.Save()"

if exist "%LINK%" (
    echo.
    echo ============================================
    echo  ✅ 완성!
    echo.
    echo  바탕화면에 '썸네일제목연구소' 🎬 아이콘이 생겼어요.
    echo  이제 그 아이콘만 두 번 누르면 켜져요.
    echo ============================================
) else (
    echo.
    echo  ⚠️ 아이콘을 못 만들었어요. 이 파일을 다시 눌러보세요.
)
echo.
echo  아무 키나 누르면 닫혀요.
pause >nul
