@echo off
set SID=st-1b5666b9
py -3.11 "%~dp0send_parametric_reconnect.py" --id %SID% --mode mes0_2step --period 2 --count 60
echo.
pause