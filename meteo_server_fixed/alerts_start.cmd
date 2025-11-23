@echo off
set "HOST=127.0.0.1"
set "PORT=8000"
curl -X POST "http://%HOST%:%PORT%/alerts/demo/start"
echo.
pause
