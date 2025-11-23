import socket

def xor_checksum(b: bytes) -> int:
    x = 0
    for bb in b: x ^= bb
    return x & 0xFF

HOST, PORT = "127.0.0.1", 40000  # tcp_ingest.py listens here
station = "MSRXXXX"
inner = (station + ",Sa0,3.5,3.5,3.5,3.5,3.5,3.5,3.5,"
         "Da0,180,180,180,180,180,180,180,Ta1,10.5,Hr1,29,"
         "Pa2,1002.8,752.1,,,Or3,1839,1505,Er3,0,"
         "Rt4,60,60,60,Ri4,128.01,Ra4,0.00,Rs4,55.55,"
         "Hc5,3,1122,1222,1322,Er5,0,St5,FEDCBA98,")

payload = bytes([0x02]) + inner.encode("ascii") + bytes([0x03])
cs = xor_checksum(payload)
frame = b"$" + payload + b"*" + f"{cs:02X}".encode("ascii") + b"\r\n"

with socket.create_connection((HOST, PORT), timeout=5) as s:
    s.sendall(frame)
    try:
        print(s.recv(1024).decode("ascii", "ignore").strip())
    except Exception:
        pass
