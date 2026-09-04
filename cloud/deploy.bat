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

echo.
echo [1/2] Building the cloud database...
python "%~dp0build_cloud_db.py" --page-size 4096
if errorlevel 1 goto fail

echo.
echo [2/2] Uploading to Cloudflare R2...
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
