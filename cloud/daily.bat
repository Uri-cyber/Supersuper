@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Never let git open an invisible credential dialog: a scheduled task
rem would hang on it forever instead of failing with a readable message.
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
python "%~dp0daily.py" %*
exit /b %errorlevel%
