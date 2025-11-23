param(
  [string]$Url = "http://127.0.0.1:8000/ingest",
  [string]$StationId = "st-6914df86"   # скопируй из попапа
)

# Из st-6914df86 делаем MSR01745ecc
$code = $StationId.Substring(3)
$msr  = "MSR$code"

# Пример пакета в стиле 0.4.2 (лишние поля сервер пока молча игнорит)
$payload = "$msr,Sa0,3.5,3.5,3.5,3.5,3.5,3.5,3.5,Da0,180,180,180,180,180,180,180,Ta1,10.5,Hr1,29,Pa2,1002.8,752.1,,,Or3,1839,1505,Er3,0,Rt4,60,60,60,Ri4,128.01,Ra4,0.00,Rs4,55.55,Hc5,3,1122,1222,1322,Er5,1,St5,FEDCBA98,"

$body = @{ station_id = $StationId; payload = $payload } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri $Url -Headers @{ "Content-Type"="application/json" } -Body $body
