import os, asyncio, json, httpx, re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text as sqltext, create_engine

APP_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(APP_DIR, "static")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./meteo.db")
engine = create_engine(DATABASE_URL, future=True)

app = FastAPI(title="Meteo Server (integrated TCP)")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

def ensure_tables():
    ddl_st = """
    create table if not exists stations (
        id text primary key,
        name text,
        lat double precision,
        lon double precision,
        profile text
    )"""
    if DATABASE_URL.startswith("sqlite"):
        ddl_meas = """
        create table if not exists measurements (
            id integer primary key autoincrement,
            station_id text not null,
            ts timestamp not null default (CURRENT_TIMESTAMP),
            raw text,
            parsed text
        )"""
    else:
        ddl_meas = """
        create table if not exists measurements (
            id bigserial primary key,
            station_id text not null,
            ts timestamptz not null default now(),
            raw text,
            parsed jsonb
        )"""
    with engine.begin() as conn:
        conn.execute(sqltext(ddl_st))
        conn.execute(sqltext(ddl_meas))

@app.post("/ingest")
async def ingest(inp: Dict):
    ensure_tables()
    station_id = inp.get("station_id","unknown")
    payload = inp.get("payload", {})
    with engine.begin() as conn:
        conn.execute(sqltext("insert into measurements (station_id, raw, parsed) values (:sid,:raw,:parsed)"),
                     {"sid": station_id,
                      "raw": json.dumps(payload, ensure_ascii=False),
                      "parsed": json.dumps(payload, ensure_ascii=False) if DATABASE_URL.startswith("sqlite") else payload})
        conn.execute(sqltext("""
            insert into stations (id,name,lat,lon,profile)
            values (:id,:name,0,0,'default')
            on conflict (id) do nothing
        """), {"id": station_id, "name": station_id})
    return {"ok": True}

@app.get("/measurements/range")
def range_api(station_id: str, minutes: int = 60, fields: str = "Sa0,Ta1,Hr1,Pa2"):
    ensure_tables()
    flds = [f for f in fields.split(",") if f]
    now = datetime.utcnow()
    with engine.begin() as conn:
        rows = conn.execute(sqltext("select ts, parsed from measurements where station_id=:sid and ts >= :ts_from order by ts"),
                            {"sid": station_id, "ts_from": now - timedelta(minutes=minutes+5)}).fetchall()
    ts = []; series = {f: [] for f in flds}
    for ts_val, parsed in rows:
        if isinstance(parsed, str):
            try: parsed = json.loads(parsed)
            except: parsed = {}
        ts.append(ts_val.isoformat() if hasattr(ts_val, "isoformat") else str(ts_val))
        for f in flds:
            v = parsed.get(f)
            if isinstance(v, list) and v:
                v = v[0]
            series[f].append(v)
    return {"ts": ts, "series": series}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
_alert_task: Optional[asyncio.Task] = None

async def _tg_send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except Exception:
        pass

@app.get("/alerts/demo/start")
async def alerts_start(period_sec: int = 10):
    global _alert_task
    if _alert_task and not _alert_task.done():
        return {"ok": True, "status": "already_running"}
    async def worker():
        i = 0
        try:
            while True:
                i += 1
                await _tg_send(f"Demo alert #{i}")
                await asyncio.sleep(max(1, period_sec))
        except asyncio.CancelledError:
            pass
    _alert_task = asyncio.create_task(worker())
    return {"ok": True, "period_sec": period_sec}

@app.get("/alerts/demo/stop")
async def alerts_stop():
    global _alert_task
    if _alert_task:
        _alert_task.cancel()
    return {"ok": True}

STX = 0x02
ETX = 0x03
ALLOWED = {"Ta","Hr","Pa","Sa","Da","Or","Er","Rt","Ri","Ra","Rs","Hc","Ci","Tr","Tf","Cs","Fp","Rh","Rc","Gr","Cr","Tt"}

def xor_checksum(payload: bytes) -> int:
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF

def strip_braced_ctrl(s: str) -> str:
    return re.sub(r"\\{[0-9A-Fa-f]{2}\\}", "", s)

def parse_mes0_frame(raw: bytes):
    try:
        s = raw.decode("ascii", errors="ignore")
    except:
        s = raw.decode("utf-8", errors="ignore")
    s = strip_braced_ctrl(s)

    if b"$" not in raw or b"*" not in raw:
        raise ValueError("no $ or *")
    i1 = raw.index(b"$"); i2 = raw.index(b"*")
    payload = raw[i1+1:i2]
    cs_field = raw[i2+1:i2+3]
    cs_recv = int(cs_field.decode("ascii"), 16)
    cs_calc = xor_checksum(payload)
    if cs_calc != cs_recv:
        raise ValueError(f"bad CS: calc={cs_calc:02X} recv={cs_recv:02X}")
    inside = payload.decode("ascii","ignore").replace(chr(STX),"").replace(chr(ETX),"")
    parts = [p for p in inside.split(",") if p!=""]
    if not parts: raise ValueError("empty")
    station_id = parts[0].strip()
    items = parts[1:]
    tag_re = re.compile(r"^([A-Za-z]{2})(\\d)$")
    out = {"_raw": inside}
    cur = None
    for t in items:
        m = tag_re.match(t)
        if m and m.group(1) in ALLOWED:
            cur = t; out.setdefault(cur, []); continue
        if cur is not None:
            try: v = float(t.replace(",", "."))
            except: v = t
            out[cur].append(v)
    return station_id, out

TCP_HOST = os.getenv("MES0_TCP_HOST","0.0.0.0")
TCP_PORT = int(os.getenv("MES0_TCP_PORT","9001"))
_tcp_server = None

async def _tcp_handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        raw = await reader.readline()
        if not raw:
            writer.write(b"ERR\\r\\n"); await writer.drain(); return
        line = raw.decode("ascii","ignore").strip()
        if line.startswith("MES0=?"):
            writer.write(b"OK\\r\\n"); await writer.drain(); return
        try:
            station_id, data = parse_mes0_frame(raw)
        except Exception as e:
            writer.write(f"ERR {e}\\r\\n".encode()); await writer.drain(); return
        ensure_tables()
        with engine.begin() as conn:
            conn.execute(sqltext("insert into measurements (station_id, raw, parsed) values (:sid,:raw,:parsed)"),
                         {"sid": station_id,
                          "raw": json.dumps(data, ensure_ascii=False),
                          "parsed": json.dumps(data, ensure_ascii=False) if DATABASE_URL.startswith("sqlite") else data})
            conn.execute(sqltext(\"\"\"
                insert into stations (id,name,lat,lon,profile)
                values (:id,:name,0,0,'default')
                on conflict (id) do nothing
            \"\"\"), {"id": station_id, "name": station_id})
        writer.write(b"OK\\r\\n"); await writer.drain()
    finally:
        try:
            writer.close(); await writer.wait_closed()
        except Exception:
            pass

@app.on_event("startup")
async def on_startup():
    ensure_tables()
    global _tcp_server
    _tcp_server = await asyncio.start_server(_tcp_handle, TCP_HOST, TCP_PORT)
    sockets = ", ".join(str(s.getsockname()) for s in _tcp_server.sockets or [])
    print(f"[tcp] MES0 integrated on {sockets}")

@app.on_event("shutdown")
async def on_shutdown():
    global _tcp_server
    if _tcp_server:
        _tcp_server.close()
        await _tcp_server.wait_closed()
        _tcp_server = None
        print("[tcp] MES0 server stopped")
