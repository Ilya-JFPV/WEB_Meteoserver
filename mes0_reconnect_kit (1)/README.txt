MES0 Reconnect Kit
====================
Набор для серверов, которые закрывают сокет после кадра (WinError 10053).
Скрипт переподключается на КАЖДЫЙ пакет и поддерживает варианты рукопожатия MES0.

Файлы:
- send_parametric_reconnect.py
- msr_plain_reconnect.cmd
- msr_stxetx_reconnect.cmd
- msr_mes0_single_reconnect.cmd          (одной посылкой: "MES0=?\r\n$" + STX/MSR/ETX\r\n)
- msr_mes0_2step_reconnect.cmd           (двумя посылками: "MES0=?\r\n", затем "$"+STX/MSR/ETX\r\n)
- msr_mes0_2step_nodollar_reconnect.cmd  (двумя посылками без "$": "MES0=?\r\n", затем STX/MSR/ETX\r\n)

Как использовать:
1) При необходимости поменяй SID внутри .cmd (по умолчанию st-1b5666b9).
2) Запускай .cmd по очереди и смотри, какой режим «заходит» (график/логи сервера).
