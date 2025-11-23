@echo off
set SID=st-49f0819b
py -3.11 "%~dp0send_parametric_reconnect.py" --id %SID% --mode plain --period 2 --count 60
echo.
pause