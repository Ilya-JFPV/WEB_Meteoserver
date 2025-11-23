@echo off
set "HOST=127.0.0.1"
set "PORT=8000"

echo Stopping...
curl -s -X POST "http://%HOST%:%PORT%/alerts/demo/stop" >NUL

echo Starting (10s)...
curl -s -X POST "http://%HOST%:%PORT%/alerts/demo/start" >NUL

echo Done.
pause
