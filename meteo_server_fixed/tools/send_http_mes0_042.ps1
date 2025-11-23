param(
  [string]$Url = "http://127.0.0.1:8000/ingest",
  [string]$Station = "MSRXXXX"
)

function Get-XorChecksum([byte[]]$bytes) {
  $x = 0; foreach($b in $bytes){ $x = $x -bxor $b }; return $x -band 0xFF
}

# Внутренности MES0 (между STX и ETX) — пример 0.4.2
$inner = "$Station,Sa0,3.5,3.5,3.5,3.5,3.5,3.5,3.5,Da0,180,180,180,180,180,180,180,Ta1,10.5,Hr1,29,Pa2,1002.8,752.1,,,Or3,1839,1505,Er3,0,Rt4,60,60,60,Ri4,128.01,Ra4,0.00,Rs4,55.55,Hc5,3,1122,1222,1322,Er5,0,St5,FEDCBA98,"

# Собираем полный MES0 с контрольной суммой
$payloadBytes = [System.Text.Encoding]::ASCII.GetBytes([string]([char]2) + $inner + [char]3)
$cs = Get-XorChecksum $payloadBytes
$frame = '$' + [string]([char]2) + $inner + [string]([char]3) + '*' + ($cs.ToString("X2"))

# Отправим в /ingest (ожидает строку payload)
$body = @{ station_id = $Station; payload = $frame } | ConvertTo-Json -Depth 3 -Compress

Invoke-RestMethod -Method Post -Uri $Url `
  -Headers @{ "Content-Type"="application/json" } `
  -Body $body
