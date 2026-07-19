@echo off
chcp 65001 >nul
title 키 설정 (.env 만들기)
cd /d "%~dp0"

echo ============================================
echo  🔑 API 키 설정 도우미
echo ============================================
echo.

if exist ".env" (
    echo  .env 파일이 이미 있어요. 메모장으로 열게요.
) else (
    echo  키 넣을 자리(.env)를 새로 만드는 중...
    (
    echo # ============================================
    echo # 🔑 API 키 파일 - 이 파일에 키를 붙여넣으세요
    echo # 등호(=) 오른쪽에 키를 붙여넣고 [파일-저장] 하면 끝!
    echo # ============================================
    echo.
    echo # ① YouTube 키 (필수 - 이게 있어야 진짜 영상 데이터가 나와요^)
    echo #    발급: https://console.cloud.google.com
    echo YOUTUBE_API_KEY=
    echo.
    echo # ② Gemini 키 (권장 - 대본/번역/컨셉 분석이 진짜로 작동^)
    echo #    발급: https://aistudio.google.com/app/apikey
    echo GEMINI_API_KEY=
    echo.
    echo # ③ OpenAI 키 (선택 - 넣으면 컨셉 제조기가 GPT로 작동^)
    echo #    발급: https://platform.openai.com/api-keys
    echo OPENAI_API_KEY=
    ) > .env
    echo  ✅ 만들었어요!
)
echo.
echo  메모장이 열리면:
echo    1) 등호(=^) 오른쪽에 키를 붙여넣으세요
echo    2) 위쪽 [파일] - [저장] 을 누르세요
echo    3) 메모장을 닫으세요
echo    4) 일본쇼츠실행.bat 을 다시 더블클릭 (서버 재시작^)
echo.
echo  ⚠️ 이 .env 파일은 인터넷에 안 올라가요 (사장님 컴퓨터에만 안전하게 보관^)
echo.
timeout /t 2 >nul
notepad .env
