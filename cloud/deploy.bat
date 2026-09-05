@echo off
chcp 65001 >nul
title Mehiron - build and upload to R2
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)

rem The app index is not rebuilt by "il_prices.py update", so it is rebuilt
rem here. Without this step the cloud database is built from yesterday's
rem aggregates while carrying today's prices.
echo.
echo [1/3] Rebuilding the app index...
python "%~dp0..\app\build_index.py"
if errorlevel 1 goto fail

rem No --page-size here on purpose. The default is 16384, which is the file
rem name upload_r2.py looks for. Passing 4096 built one file and uploaded a
rem different, older one.
echo.
echo [2/3] Building the cloud database...
python "%~dp0build_cloud_db.py"
if errorlevel 1 goto fail

echo.
echo [3/3] Uploading to Cloudflare R2...
python "%~dp0upload_r2.py"
if errorlevel 1 goto fail

echo.
echo Done. The site now serves the updated data.
pause
exit /b 0

:fail
echo.
echo Failed. See the message above.
pause
exit /b 1
