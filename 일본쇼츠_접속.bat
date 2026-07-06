@echo off
chcp 65001 >nul
title 일본쇼츠 접속 (서버 PC 에 연결)
cd /d "%~dp0"

echo ============================================
echo  🎌 일본쇼츠 접속  [다른 PC 용]
echo  서버 PC(일본쇼츠실행.bat 켠 컴퓨터)에 연결합니다
echo ============================================
echo.

if exist server_ip.txt goto :read

echo 서버 PC 화면에 표시된 IP 주소를 입력하세요. (예: 192.168.0.10)
set /p SERVER_IP=서버 IP 입력: 
> server_ip.txt echo %SERVER_IP%
goto :go

:read
set /p SERVER_IP=<server_ip.txt

:go
echo.
echo 연결 주소: http://%SERVER_IP%:8787
start "" http://%SERVER_IP%:8787
echo.
echo  💡 브라우저가 열리지 않거나 접속이 안 되면:
echo     1) 서버 PC 에서 '일본쇼츠실행.bat' 이 켜져 있는지 확인
echo     2) 서버 PC 방화벽에서 [액세스 허용] 했는지 확인
echo     3) IP 가 바뀌었으면 이 폴더의 server_ip.txt 를 지우고 다시 실행
echo.
timeout /t 8
