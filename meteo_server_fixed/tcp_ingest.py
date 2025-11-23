# tcp_ingest.py
import os, asyncio, re, json, binascii
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

#     (Ta/Hr/Pa/Sa/Da/...  )
TAGS = {"Ci","Cr","Cs","Da","Er","Fp","Gr","Hc","Hr","Or","Pa","Ra","Rc","Rh","Ri","Rs","Rt","Sa","St","Ta","Tf","Tr","Tt"}

STX = 0x02  # <STX>
ETX = 0x03  # <ETX>


TCP_ALLOWED_IPS = {p.strip() for p in os.getenv("TCP_ALLOWED_IPS", "").split(",") if p.strip()}
TCP_SHARED_SECRET = os.getenv("TCP_SHARED_SECRET")


def _peer_ip(peer) -> Optional[str]:
    if isinstance(peer, tuple) and peer:
        return peer[0]
    if peer:
        return str(peer)
    return None


def _is_peer_allowed(peer) -> bool:
    if not TCP_ALLOWED_IPS:
        return True
    ip = _peer_ip(peer)
    return ip in TCP_ALLOWED_IPS


async def _require_tcp_secret(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """Expect a single line with shared secret before processing frames."""
    line = await reader.readline()
    token = line.decode("ascii", "ignore").strip()
    if not token:
        return False
    if token != TCP_SHARED_SECRET:
        writer.write(b"ERR auth\r\n")
        try:
            await writer.drain()
        finally:
            return False
    return True

def _xor_checksum(payload: bytes) -> int:
    """XOR   payload ( '$'  '*',   )   ."""
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF

def _strip_braced_ctrl(s: str) -> str:
    """    {02} {03}    ."""
    return re.sub(r"\{[0-9A-Fa-f]{2}\}", "", s)

def parse_mes0_frame(raw: bytes) -> Tuple[str, Dict[str, Any]]:
    """
        : $<STX>AMS0004,Ta1,...<ETX>*CS<CR><LF>
     (station_id, parsed_dict).
     ValueError     .
    """
    #  '$' ... '*..' ... CRLF
    try:
        s = raw.decode("ascii", errors="ignore")
    except:
        s = raw.decode("utf-8", errors="ignore")

    s = _strip_braced_ctrl(s)
    # :       
    data_bytes = raw

    #    '$'  '*'   (  XOR)
    if b'$' not in data_bytes or b'*' not in data_bytes:
        raise ValueError("no $ or *")
    start = data_bytes.index(b'$') + 1
    star  = data_bytes.index(b'*')
    payload_for_crc = data_bytes[start:star]
    cs_txt = data_bytes[star+1:star+3]  #  hex-
    try:
        cs_recv = int(cs_txt.decode('ascii'), 16)
    except:
        raise ValueError("bad checksum text")

    cs_calc = _xor_checksum(payload_for_crc)
    if cs_calc != cs_recv:
        raise ValueError(f"checksum mismatch calc={cs_calc:02X} recv={cs_recv:02X}")

    #   
    #   '$'    <STX>/<ETX>/<CRLF>
    inside = data_bytes[start:star].decode('ascii', errors='ignore')
    inside = inside.replace(chr(STX), '').replace(chr(ETX), '')
    parts = [p for p in inside.split(',') if p != '']

    if not parts:
        raise ValueError("empty parts")

    #       AMS0004 / MSRXXXX (. )
    station_id = parts[0].strip()
    tokens = parts[1:]

    #   +id >      
    parsed: Dict[str, Any] = {"_raw": inside}
    i = 0
    current_key: Optional[str] = None
    while i < len(tokens):
        t = tokens[i]
        m = re.match(r'^([A-Za-z]{2})(\d)$', t)  #  Ta1, Pa2, Sa0 ...
        if m and m.group(1) in TAGS:
            current_key = t
            if current_key not in parsed:
                parsed[current_key] = []
            i += 1
            continue
        #     float
        if current_key is not None:
            try:
                v = float(t.replace(',', '.'))
            except:
                v = t
            if isinstance(parsed[current_key], list):
                parsed[current_key].append(v)
        i += 1

    #     :   ,
    #     Sa0/Da0/Pa2  ..
    for k, v in list(parsed.items()):
        if k.startswith(tuple(TAGS)) and isinstance(v, list) and v:
            #        
            parsed.setdefault("current", {})[k] = v[0]

    return station_id, parsed

class TcpIngestServer:
    def __init__(self, host: str, port: int, on_parsed_cb):
        self._host, self._port = host, port
        self._srv: Optional[asyncio.AbstractServer] = None
        self._on_parsed = on_parsed_cb

    async def start(self):
        self._srv = await asyncio.start_server(self._handle, self._host, self._port)
        addr = ", ".join(str(s.getsockname()) for s in self._srv.sockets)
        print(f"[tcp-ingest] listening on {addr}")

    async def close(self):
        if self._srv:
            self._srv.close()
            await self._srv.wait_closed()
            self._srv = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        peer_allowed = _is_peer_allowed(peer)
        if TCP_SHARED_SECRET:
            require_secret = not TCP_ALLOWED_IPS or not peer_allowed
            if require_secret:
                allowed = await _require_tcp_secret(reader, writer)
                if not allowed:
                    writer.close()
                    return
        elif not peer_allowed:
            print(f"[tcp-ingest] rejected connection from {peer} (not allowed)")
            writer.write(b"ERR auth\r\n")
            try:
                await writer.drain()
            finally:
                writer.close()
                return
        print(f"[tcp-ingest] connection from {peer}")
        buf = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk: break
                buf += chunk
                #   CRLF;   
                while b"\r\n" in buf:
                    frame, buf = buf.split(b"\r\n", 1)
                    if not frame: 
                        continue
                    try:
                        #   MES0=?     (handshake)
                        if frame.strip().startswith(b"MES0=?"):
                            writer.write(b"OK\r\n")
                            await writer.drain()
                            continue
                        #  ,       $..*CS
                        if b"$" in frame and b"*" in frame:
                            sid, parsed = parse_mes0_frame(frame)
                            await self._on_parsed(sid, parsed)
                            writer.write(b"OK\r\n")
                            await writer.drain()
                    except Exception as e:
                        err = f"ERR {e}".encode()
                        writer.write(err + b"\r\n")
                        await writer.drain()
        finally:
            writer.close()
            try: await writer.wait_closed()
            except: pass
            print(f"[tcp-ingest] closed {peer}")
