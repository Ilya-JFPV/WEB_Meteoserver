param(
  [string]$ProjectDir = "D:\GIT_FLICK\Python projects\Meteoserver\meteo_server_fixed",
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8000,

  # Telegram
  [string]$BotToken = "8463154590:AAEW1E9v9nMhJ-bzS_THHNKtRs1L-jSqgLw",
  [string]$ChatId   = "1051646619",
  [string]$DemoAlerts = "1"  # "1" = enabled, "0" = disabled
)

$ErrorActionPreference = "Stop"

# 0) Go to project dir
Set-Location $ProjectDir

# 1) VENV (create if missing) and activate
if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
  Write-Host "Creating venv with system python ..."
  python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

# 1.1) Resolve python executable from venv
$PyExe = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
if (-not (Test-Path $PyExe)) {
  # fallback to python in PATH
  $PyExe = "python"
}

# 2) Env vars
$env:TELEGRAM_BOT_TOKEN = $BotToken
$env:TELEGRAM_CHAT_ID   = $ChatId
$env:DEMO_TELEGRAM_ALERTS = $DemoAlerts

# 3) Deps
Write-Host "Installing/Updating requirements..."
& $PyExe -m pip install --upgrade pip
& $PyExe -m pip install -r requirements.txt

# 4) Checks
Write-Host "Project path:" (Get-Location).Path
Write-Host "app.py exists:" (Test-Path .\app.py)
Write-Host "static\index.html exists:" (Test-Path .\static\index.html)
Write-Host "Token:" ($env:TELEGRAM_BOT_TOKEN.Substring(0,8) + "…")
Write-Host "ChatId:" $env:TELEGRAM_CHAT_ID
Write-Host "Demo alerts:" $env:DEMO_TELEGRAM_ALERTS
Write-Host "Python exe:" $PyExe

# 5) Run
Write-Host "Starting Uvicorn on http://$BindHost`:$Port ..."
& $PyExe -m uvicorn app:app --host $BindHost --port $Port --app-dir $ProjectDir
