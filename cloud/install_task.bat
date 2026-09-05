@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing the daily update task...
python "%~dp0make_task.py"
if errorlevel 1 goto fail
schtasks /Create /XML "%~dp0mehiron-daily.xml" /TN "Mehiron - daily update" /F
if errorlevel 1 goto fail
echo.
echo Done. The update runs every day at 09:00.
echo If the PC is off then, it runs at the next start-up instead.
echo.
echo If an update ever fails, a file named "mehiron - tzarich tipul.txt"
echo appears on the Desktop, in Hebrew. It disappears by itself once an
echo update succeeds.
echo.
echo To check the status at any time, run status.bat in the project folder.
pause
exit /b 0

:fail
echo.
echo Failed to install the task. See the message above.
pause
exit /b 1
