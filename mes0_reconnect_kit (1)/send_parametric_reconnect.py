import socket, time, argparse, math, random

def build_values(t: float):
    import math, random
    sa = round(3.0 + 1.3*math.sin(t/7.0) + random.uniform(-0.15,0.15), 2)
    da = int((180 + 40*math.sin(t/25.0)) % 360)
    ta = round(19.5 + 3.0*math.sin(t/40.0), 1)
    hr = round(52.0 + 10.0*math.sin(t/31.0), 1)
    pa = round(1013.0 + 2.5*math.sin(t/100.0), 1)
    return sa, da, ta, hr, pa

def msr_line(sid: str) -> str:
    t = time.time()
    sa, da, ta, hr, pa = build_values(t)
    return f"MSR{sid},Sa0,{sa:.2f},Da0,{da},Ta1,{ta:.1f},Hr1,{hr:.1f},Pa2,{pa:.1f}"

def pkt_plain(line: str) -> bytes:
    return (line + "\r\n").encode("ascii", "ignore")

def pkt_stxetx(line: str) -> bytes:
    return b"\x02" + line.encode("ascii", "ignore") + b"\x03\r\n"

def pkt_mes0_single(line: str, dollar: bool=True) -> bytes:
    # One write: "MES0=?\r\n" + ("$" if dollar) + STX line ETX CRLF
    prefix = b"MES0=?\r\n"
    if dollar:
        prefix += b"$"
    return prefix + b"\x02" + line.encode("ascii","ignore") + b"\x03\r\n"

def send_one(host, port, payloads):
    s = socket.create_connection((host, port), timeout=3.0)
    try:
        for p in payloads:
            s.sendall(p)
            # tiny pause between writes in multi-step modes
            time.sleep(0.02)
    finally:
        try:
            s.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        s.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Per-packet reconnect MSR/MES0 sender with handshake variants")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--id", required=True)
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--period", type=float, default=2.0)
    ap.add_argument("--mode", choices=["plain","stxetx","mes0_single","mes0_2step","mes0_2step_nodollar"], default="mes0_single")
    args = ap.parse_args()

    for _ in range(args.count):
        line = msr_line(args.id)
        if args.mode == "plain":
            send_one(args.host, args.port, [pkt_plain(line)])
        elif args.mode == "stxetx":
            send_one(args.host, args.port, [pkt_stxetx(line)])
        elif args.mode == "mes0_single":
            send_one(args.host, args.port, [pkt_mes0_single(line, dollar=True)])
        elif args.mode == "mes0_2step":
            # Two writes: "MES0=?\r\n" then "$" + STX line ETX CRLF
            send_one(args.host, args.port, [b"MES0=?\r\n", b"$" + pkt_stxetx(line)])
        elif args.mode == "mes0_2step_nodollar":
            # Two writes: "MES0=?\r\n" then STX line ETX CRLF (без "$")
            send_one(args.host, args.port, [b"MES0=?\r\n", pkt_stxetx(line)])
        time.sleep(args.period)
