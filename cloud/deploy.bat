@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never

rem This is the manual path. It runs exactly the same steps as the daily
rem task, minus the download - so the two cannot drift apart and start
rem behaving differently from each other.
python "%~dp0daily.py" --no-scrape %*
if errorlevel 1 goto fail
pause
exit /b 0

:fail
echo.
echo Failed. See the message above, or run status.bat.
pause
exit /b 1
