import os, asyncio, re, httpx

TCP_HOST = os.getenv("TCP_LISTEN_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("TCP_LISTEN_PORT", "40000"))
APP_HTTP_URL = os.getenv("APP_HTTP_URL", "http://127.0.0.1:8000")

TAGS = ("Sa0","Ta1","Hr1","Pa2")

def parse_frame_line(line: str):
    sid = "MSRXXXX"
    m = re.search(r"\$[^\w]*([A-Z]{2,}\d{0,})[,]", line)
    if m:
        sid = m.group(1)

    def first_of(tag):
        m = re.search(rf"{tag}\s*,\s*([-+0-9.,]+)", line)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", "."))
        except:
            return None

    payload = {}
    for t in TAGS:
        v = first_of(t)
        if v is not None:
            payload[t] = v
    return sid, payload

async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        raw = await reader.readline()
        if not raw:
            writer.write(b"ERR\n"); await writer.drain(); return
        s = raw.decode("ascii","ignore").strip()

        if s.startswith("MES0=?"):
            writer.write(b"OK\n"); await writer.drain(); return

        sid, payload = parse_frame_line(s)
        if not payload:
            writer.write(b"ERR\n"); await writer.drain(); return

        async with httpx.AsyncClient(timeout=5.0) as cli:
            r = await cli.post(f"{APP_HTTP_URL}/ingest", json={"station_id": sid, "payload": payload})
            if r.status_code >= 400:
                writer.write(b"ERR\n"); await writer.drain(); return

        writer.write(b"OK\n"); await writer.drain()
    finally:
        try:
            writer.close(); await writer.wait_closed()
        except Exception:
            pass

async def main():
    srv = await asyncio.start_server(handle, TCP_HOST, TCP_PORT)
    addr = ", ".join(str(s.getsockname()) for s in srv.sockets or [])
    print(f"[tcp-gateway] listening on {addr}, forwarding to {APP_HTTP_URL}/ingest")
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
