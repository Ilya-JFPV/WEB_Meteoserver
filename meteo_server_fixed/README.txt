
MeteoServer Full Patch v13
==========================
В архиве:
- app.py — бэкенд с универсальным парсером (поддержка 'Sa0=7.8' и 'Sa0,7.8'), JWT и CORS.
- static/client.js — фронт для рисования графиков (HiDPI, нормализация значений, переключатели серий).

Как применить:
1) Сохраните текущие файлы на всякий случай.
2) Замените ваш app.py на этот.
3) Замените ваш static/client.js на этот.
4) Перезапустите сервер (docker compose restart app, либо перезапустите uvicorn).
5) Засейте данные (можно чередовать 'Sa0=7.8' и 'Sa0,7.8') и откройте попап станции.

Пример сидера (PowerShell):
1..40 | ForEach-Object {
  $spd = [Math]::Round((Get-Random -Minimum 2 -Maximum 12) + (Get-Random)/100, 1)
  $dir = Get-Random -Minimum 0 -Maximum 359
  $temp = [Math]::Round(12 + (Get-Random -Minimum -25 -Maximum 25)/10, 1)
  $rh = Get-Random -Minimum 40 -Maximum 90
  $p  = [Math]::Round(1002 + (Get-Random -Minimum -30 -Maximum 30)/10, 1)

  $p1 = "Sa0=$spd Da0=$dir Ta1=$temp Hr1=$rh Pa2=$p"
  $p2 = "Sa0,$spd Da0,$dir Ta1,$temp Hr1,$rh Pa2,$p"
  $payload = if ($_ % 2) { $p1 } else { $p2 }

  $url = "http://localhost:8000/ingest?station_id=demo-1&payload=$([uri]::EscapeDataString($payload))"
  Invoke-RestMethod -Method Post -Uri $url -Headers @{ Authorization = "Bearer <YOUR_TOKEN>" } | Out-Null
  Start-Sleep -Milliseconds 120
}
