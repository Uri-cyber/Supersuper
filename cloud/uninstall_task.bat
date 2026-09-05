@echo off
chcp 65001 >nul
schtasks /Delete /TN "Mehiron - daily update" /F
schtasks /Delete /TN "Mehiron - alert" /F
echo Removed. Updates will no longer run by themselves.
pause
