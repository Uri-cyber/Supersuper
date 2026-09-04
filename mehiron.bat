@echo off
chcp 65001 >nul
title Mehiron
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 goto nopython

if not exist "prices.db" (
  python "%~dp0app\first_run.py"
  if errorlevel 1 goto fail
  python "%~dp0il_prices.py" update
)

python "%~dp0app\build_index.py"
if errorlevel 1 goto fail

python "%~dp0app\server.py" %*
goto end

:nopython
echo.
echo Python was not found on this computer.
echo Install it from https://www.python.org/downloads/
echo During setup, tick "Add Python to PATH".
echo.
pause
exit /b 1

:fail
echo.
echo Startup failed. See the message above.
pause
exit /b 1

:end
pause
