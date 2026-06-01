@echo off
chcp 65001 > nul
cd /d "%USERPROFILE%\youtube-automation\thumbnail-automation"
git pull origin claude/inspiring-meitner-C7Nvv 2>nul
set PYTHONPATH=%USERPROFILE%\youtube-automation\thumbnail-automation
start http://localhost:8501
timeout /t 2 /nobreak > nul
streamlit run review/app.py
