@echo off
set HOST=127.0.0.1
set PORT=8000
set CODE=be3728ec
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0send_http_ingest.ps1" -HostName %HOST% -Port %PORT% -Code %CODE%
pause
