# -*- coding: utf-8 -*-
import socket

def xor_checksum(b: bytes) -> int:
    x = 0
    for bb in b:
        x ^= bb
    return x & 0xFF

STATION_ID = "st-6914df86"  # <-- поменяй на свой st-... из попапа
# Встроенный TCP-сервер из app.py слушает порт 9001:
HOST, PORT = "127.0.0.1", 9001
# Если запускаешь отдельный tcp_gateway_full.py — используй 40000:
# HOST, PORT = "127.0.0.1", 40000

code = STATION_ID[3:]
msr  = "MSR" + code

inner = (
    msr + ","
    "Sa0,7.77,7.77,7.77,7.77,7.77,7.77,7.77,"
    "Da0,123,123,123,123,123,123,123,"
    "Ta1,11.11,Hr1,22.22,"
    "Pa2,1001.1,752.1,,,"
    "Or3,1839,1505,Er3,0,"
    "Rt4,60,60,60,Ri4,128.01,Ra4,0.00,Rs4,55.55,"
    "Hc5,3,1122,1222,1322,Er5,0,St5,FEDCBA98,"
)

payload = bytes([0x02]) + inner.encode("ascii") + bytes([0x03])
cs = xor_checksum(payload)
frame = b"$" + payload + b"*" + f"{cs:02X}".encode("ascii") + b"\r\n"

with socket.create_connection((HOST, PORT), timeout=5) as s:
    s.sendall(frame)
    try:
        print(s.recv(1024).decode("ascii", "ignore").strip())
    except Exception:
        pass
