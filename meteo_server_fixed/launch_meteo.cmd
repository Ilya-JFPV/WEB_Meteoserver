@echo off
REM ==== НАСТРОЙКИ ====
set "PROJECT_DIR=D:\GIT_FLICK\Python projects\Meteoserver\meteo_server_fixed"
set "PY=py -3.11"
set "HOST=127.0.0.1"
set "PORT=8000"

REM === Telegram (вшито по просьбе) ===
set TELEGRAM_BOT_TOKEN=8463154590:AAEW1E9v9nMhJ-bzS_THHNKtRs1L-jSqgLw
set TELEGRAM_CHAT_ID=1051646619
set DEMO_TELEGRAM_ALERTS=1
REM =====================

echo.
echo [1/6] Переход в папку проекта...
cd /d "%PROJECT_DIR%" || (
  echo [ERR] Не могу перейти в "%PROJECT_DIR%".
  pause
  exit /b 1
)

echo.
echo [2/6] Проверка виртуального окружения...
if not exist ".venv\Scripts\activate.bat" (
  echo Создаю .venv ...
  %PY% -m venv .venv || (
    echo [ERR] Не удалось создать .venv
    pause
    exit /b 1
  )
)

echo.
echo [3/6] Активация .venv ...
call ".venv\Scripts\activate.bat" || (
  echo [ERR] Не удалось активировать .venv
  pause
  exit /b 1
)

echo.
echo [4/6] Обновление pip и установка зависимостей...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt || (
  echo [ERR] Установка зависимостей не удалась
  pause
  exit /b 1
)

echo.
echo [5/6] Переменные окружения:
for /f "delims=" %%A in ('echo %TELEGRAM_BOT_TOKEN%') do set "_TBT=%%A"
set "_TBT=********%_TBT:~-6%"
echo TELEGRAM_BOT_TOKEN=%_TBT%
echo TELEGRAM_CHAT_ID=%TELEGRAM_CHAT_ID%
echo DEMO_TELEGRAM_ALERTS=%DEMO_TELEGRAM_ALERTS%

echo.
echo [6/6] Старт uvicorn...
%PY% -m uvicorn app:app --host %HOST% --port %PORT% --app-dir "%PROJECT_DIR%"
