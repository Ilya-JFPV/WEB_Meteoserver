FULL MES0 ENHANCEMENT PACK
============================
Содержимое:
  - tcp_gateway_full.py — улучшенный TCP sidecar (XOR КС, STX/ETX, полный парс тегов)
  - app_with_tcp.py — приложение с интегрированным TCP-сервером (без отдельного sidecar)
  - deploy/docker-compose.timescale.sidecar.yml — стек с отдельным TCP-сервисом
  - deploy/docker-compose.timescale.integrated.yml — стек с интегрированным TCP
  - deploy/systemd/meteoserver.service — unit для автозапуска compose (integrated-вариант)
  - deploy/cloud-init/yc-user-data.yaml — cloud-init для Yandex Cloud

Безопасность TCP
----------------
- Для ограничения источников используйте ``TCP_ALLOWED_IPS`` (список IP через запятую) или общий секрет
  ``TCP_SHARED_SECRET``. При задании секрета клиент должен первым сообщением отправить строку с ключом,
  после чего переходить к кадрам MES0. Whitelist позволяет пропускать доверенные IP без секрета.
Использование:
  Вариант SIDEcar:
    cd deploy
    cp docker-compose.timescale.sidecar.yml docker-compose.timescale.yml
    echo "TCP_INGEST_PORT=40000" >> .env
    docker compose -f docker-compose.timescale.yml up -d --build
  Вариант INTEGRATED:
    cd deploy
    cp docker-compose.timescale.integrated.yml docker-compose.timescale.yml
    echo "MES0_TCP_PORT=9001" >> .env
    docker compose -f docker-compose.timescale.yml up -d --build
Проверка:
  - Веб: http://<PUBLIC_IP>:8000/healthz
  - TCP: nc <PUBLIC_IP> <порт>; отправьте одну строку $...*CS\r\n — ответ OK
