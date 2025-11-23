
MeteoServer Full Patch v13
==========================
В архиве:
- app.py — бэкенд с универсальным парсером (поддержка 'Sa0=7.8' и 'Sa0,7.8'), JWT и CORS.
- static/client.js — фронт для рисования графиков (HiDPI, нормализация значений, переключатели серий).

Авторизация API
---------------
- HTTP API закрываются по ключу: задайте переменную окружения ``API_KEY`` и передавайте её значение
  в заголовке ``X-API-Key`` (можно переопределить именем из ``API_KEY_HEADER``) или как Bearer-токен.
- Ключ обязателен для мутирующих методов (``/ingest``, ``/stations``, ``/demo/fill``) и просмотра последних логов
  (``/logs/tail``). При отсутствии ``API_KEY`` проверка отключается.
- TCP-интерфейсы (``tcp_ingest.py`` и ``tcp_gateway.py``) поддерживают ограничение по IP
  (``TCP_ALLOWED_IPS=ip1,ip2``) и общий секрет (``TCP_SHARED_SECRET``). Если задан секрет, клиенты должны
  отправить его отдельной первой строкой соединения перед кадрами MES0; при указании whitelist секрет требуется
  только для неразрешённых IP.

Быстрые проверки
----------------
- Для smoke-тестов авторизации HTTP выполните ``python -m pytest tests/test_auth.py`` (ключ передайте через
  ``API_KEY``). Тесты используют встроенный TestClient и не поднимают TCP-сервер.

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

Метрики Prometheus
------------------
- Эндпоинт `/metrics` отдаёт метрики Prometheus (используется `prometheus_client.generate_latest`).
- Счётчики: `meteo_ingest_success_total{station_id="..."}` и `meteo_ingest_error_total{reason="..."}`.
- Гистограммы: `meteo_ingest_parse_seconds` и `meteo_ingest_save_seconds` для времени разбора/сохранения пакета.
- Для включения достаточно оставить зависимость `prometheus-client` из requirements и опубликовать `/metrics` в маршрутизации или scrape-конфиге Prometheus.
