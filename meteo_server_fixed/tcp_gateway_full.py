import os, asyncio, re, json, httpx

TCP_HOST = os.getenv("TCP_LISTEN_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("TCP_LISTEN_PORT", "40000"))
APP_HTTP_URL = os.getenv("APP_HTTP_URL", "http://app:8000")

STX = 0x02
ETX = 0x03
ALLOWED = {"Ci","Cr","Cs","Da","Er","Fp","Gr","Hc","Hr","Or","Pa","Ra","Rc","Rh","Ri","Rs","Rt","Sa","St","Ta","Tf","Tr","Tt"

def strip_braced_ctrl(s: str) -> str:
    return re.sub(r"\{[0-9A-Fa-f]{2}\}", "", s)

def xor_checksum(payload: bytes) -> int:
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF

def parse_mes0_frame(raw: bytes):
    try:
        s = raw.decode("ascii", errors="ignore")
    except:
        s = raw.decode("utf-8", errors="ignore")
    s = strip_braced_ctrl(s)

    if b"$" not in raw or b"*" not in raw:
        raise ValueError("no $ or * in frame")

    i_dollar = raw.index(b"$"); i_star = raw.index(b"*")
    payload_for_crc = raw[i_dollar+1:i_star]
    cs_field = raw[i_star+1:i_star+3]
    try:
        cs_recv = int(cs_field.decode("ascii"), 16)
    except:
        raise ValueError("bad checksum")

    cs_calc = xor_checksum(payload_for_crc)
    if cs_calc != cs_recv:
        raise ValueError(f"checksum mismatch: calc={cs_calc:02X} recv={cs_recv:02X}")

    inside = payload_for_crc.decode("ascii", errors="ignore")
    inside = inside.replace(chr(STX), "").replace(chr(ETX), "")
    tokens = [t for t in inside.split(",") if t != ""]
    if not tokens:
        raise ValueError("empty payload")

    station_id = tokens[0].strip()
    tokens = tokens[1:]
    tag_re = re.compile(r"^([A-Za-z]{2})(\d)$")

    full = {"_raw": inside}
    cur = None
    i = 0
    while i < len(tokens):
        t = tokens[i].strip()
        m = tag_re.match(t)
        if m and m.group(1) in ALLOWED:
            cur = t
            full.setdefault(cur, [])
            i += 1
            continue
        if cur is not None:
            try:
                v = float(t.replace(",", "."))
            except:
                v = t
            full[cur].append(v)
        i += 1

    flat = {}
    for k, arr in full.items():
        if k == "_raw":
            continue
        if isinstance(arr, list) and arr:
            v0 = arr[0]
            try:
                flat[k] = float(str(v0).replace(",", "."))
            except:
                pass
    return station_id, flat, full

async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        line = await reader.readline()
        if not line:
            writer.write(b"ERR\r\n"); await writer.drain(); return

        s = line.decode("ascii","ignore").strip()
        if s.startswith("MES0=?"):
            writer.write(b"OK\r\n"); await writer.drain(); return

        try:
            sid, flat, full = parse_mes0_frame(line)
        except Exception as e:
            writer.write(f"ERR {e}\r\n".encode()); await writer.drain(); return

        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{APP_HTTP_URL}/ingest", json={"station_id": sid, "payload": full})
            if r.status_code >= 400:
                writer.write(b"ERR\r\n"); await writer.drain(); return

        writer.write(b"OK\r\n"); await writer.drain()
    finally:
        try:
            writer.close(); await writer.wait_closed()
        except Exception:
            pass

async def main():
    srv = await asyncio.start_server(handle, TCP_HOST, TCP_PORT)
    addr = ", ".join(str(s.getsockname()) for s in srv.sockets or [])
    print(f"[tcp-gateway] Full MES0 on {addr}, forwarding to {APP_HTTP_URL}/ingest")
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
