@echo off
chcp 65001 >nul
title Mehiron - home network
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo.
echo Open Mehiron from any device on your home network:
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo    http://%%a:8000/
echo.
call "%~dp0mehiron.bat" --host 0.0.0.0 --port 8000 --no-browser
