# app.py — Meteo Server (parametric, protocol 0.4.2) with persistence, status cache, TCP ingest
# Encoding: UTF-8

import os
import re
import json
import time
import asyncio
from pathlib import Path
from collections import deque
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# -------------------------- configuration --------------------------
APP_VERSION = "0.9.2"
PROTOCOL_VERSION = "0.4.2"

# limits
MAX_PACKET_LEN = int(os.getenv("MAX_PACKET_LEN", "16384"))
MAX_POINTS_PER_FIELD = int(os.getenv("MAX_POINTS_PER_FIELD", "5000"))
TRIM_TO = int(os.getenv("TRIM_TO", "2000"))

# logging
LOG_TO_FILE = bool(int(os.getenv("INGEST_LOG_TO_FILE", "1")))
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_PATH = os.path.join(LOG_DIR, "ingest.log")

# persistence
PERSIST_STATIONS = int(os.getenv("PERSIST_STATIONS", "1"))
BASE_DIR = Path(__file__).resolve().parent
_ST_PATH_ENV = os.getenv("STATIONS_PATH", "stations.json")
STATIONS_FILE: Path = Path(_ST_PATH_ENV) if Path(_ST_PATH_ENV).is_absolute() else (BASE_DIR / _ST_PATH_ENV)

# optional subsystems
ENABLE_TCP = int(os.getenv("ENABLE_TCP", "1"))                    # 1 — run TCP MES0 on port 9001
DEMO_TG = os.getenv("DEMO_TELEGRAM_ALERTS", "0") == "1"           # 1 — run demo Telegram alerts

STARTED_AT = int(time.time())


# -------------------------- utils --------------------------
def _now_ts() -> int:
    return int(time.time())


def _to_float(x: str) -> Optional[float]:
    try:
        return float(x.replace(",", "."))
    except Exception:
        return None


def _ensure_log_dir():
    if LOG_TO_FILE and not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)


# -------------------------- models / store --------------------------
class Station(BaseModel):
    id: str
    name: str = "Station"
    lat: float
    lon: float
    code: str


class StationIn(BaseModel):
    name: Optional[str] = Field(default="Station")
    lat: float
    lon: float


class Store:
    def __init__(self):
        self.stations: Dict[str, Station] = {}  # station_id -> Station
        self.points: Dict[str, Dict[str, List[Tuple[int, float]]]] = {}  # sid -> field -> [(ts,val)]
        if PERSIST_STATIONS:
            self._load_stations()

    # ---- persistence ----
    def _load_stations(self):
        try:
            if STATIONS_FILE.exists():
                with open(STATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("items") if isinstance(data, dict) else data
                if not isinstance(items, list):
                    return
                count = 0
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    sid = it.get("id") or it.get("code")
                    lat = it.get("lat")
                    lon = it.get("lon")
                    name = it.get("name") or "Station"
                    if not sid or lat is None or lon is None:
                        continue
                    sid = str(sid)
                    # normalize IDs stored without 'st-' but 8 hex
                    if sid and not sid.startswith("st-") and re.fullmatch(r"[0-9A-Fa-f]{8}", sid):
                        sid = f"st-{sid.lower()}"
                    code = it.get("code") or sid
                    st = Station(id=sid, code=code, name=name, lat=float(lat), lon=float(lon))
                    self.stations[sid] = st
                    count += 1
                print(f"[store] loaded {count} station(s) from {STATIONS_FILE}")
        except Exception as e:
            print(f"[store] load stations failed: {e}")

    def _save_stations(self):
        if not PERSIST_STATIONS:
            return
        try:
            items = [s.model_dump() for s in self.stations.values()]
            STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATIONS_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": items}, f, ensure_ascii=False, indent=2)
            tmp.replace(STATIONS_FILE)
        except Exception as e:
            print(f"[store] save stations failed: {e}")

    # --- stations ---
    def add_station(self, lat: float, lon: float, name: Optional[str] = "Station") -> Station:
        suffix = f"{_now_ts():08x}"[-8:]
        sid = f"st-{suffix}"
        st = Station(id=sid, code=sid, name=name or "Station", lat=lat, lon=lon)
        self.stations[sid] = st
        self._save_stations()
        return st

    def list_stations(self) -> List[Station]:
        return list(self.stations.values())

    # --- points ---
    def add_point(self, sid: str, field: str, value: float, ts: Optional[int] = None):
        ts = ts or _now_ts()
        by_field = self.points.setdefault(sid, {})
        arr = by_field.setdefault(field, [])
        arr.append((ts, float(value)))
        if len(arr) > MAX_POINTS_PER_FIELD:
            by_field[field] = arr[-TRIM_TO:]

    def range(self, sid: str, fields: List[str], minutes: int) -> Dict:
        ts_to = _now_ts()
        ts_from = ts_to - minutes * 60
        out_ts: List[int] = [ts_to]
        series: Dict[str, List[float]] = {f: [] for f in fields}
        for f in fields:
            pts = [v for (t, v) in self.points.get(sid, {}).get(f, []) if t >= ts_from]
            if pts:
                series[f].append(pts[-1])
            else:
                series[f] = []
        return {"ts": out_ts, "series": series, "units": "metric"}


store = Store()


# -------------------------- parser 0.4.2 (+wrappers) --------------------------
KNOWN_FIELDS = {"Sa0", "Ta1", "Hr1", "Pa2", "Or3", "Rt4", "Ri4", "Ra4", "Rs4", "Hc5"}


def _extract_after_msr(text: str) -> Optional[Tuple[str, List[str]]]:
    m = re.search(r"MSR([A-Za-z0-9_\-]+)", text)
    if not m:
        return None
    sid = m.group(1)
    rest = text[m.end():]
    if rest.startswith(","):
        rest = rest[1:]
    parts = [p.strip() for p in rest.strip().split(",") if p.strip() != ""]
    return sid, parts


def parse_packet_042(text: str) -> Tuple[str, Dict[str, float], Dict[str, str], Optional[Dict]]:
    found = _extract_after_msr(text)
    if not found:
        raise ValueError("MSR segment not found")
    sid, parts = found

    # accept both "st-XXXXXXXX" and "XXXXXXXX" (8-hex without prefix)
    if not sid.startswith("st-") and re.fullmatch(r"[0-9A-Fa-f]{8}", sid):
        sid = f"st-{sid.lower()}"

    measurements: Dict[str, float] = {}
    status: Dict[str, str] = {}
    cloud: Optional[Dict] = None

    i = 0
    cur: Optional[str] = None
    while i < len(parts):
        tok = parts[i]
        tagm = re.fullmatch(r"([A-Za-z]{2}\d)", tok)
        if tagm:
            cur = tagm.group(1)
            i += 1
            continue

        if cur is None:
            i += 1
            continue

        if cur.startswith("Er") or cur.startswith("St"):
            if cur not in status:
                status[cur] = parts[i]
            i += 1
            continue

        if cur == "Hc5":
            layers = _to_float(parts[i])
            if layers is not None:
                measurements["Hc5"] = layers
                hs: List[float] = []
                j = i + 1
                for _ in range(4):
                    if j < len(parts):
                        vv = _to_float(parts[j])
                        if vv is not None:
                            hs.append(vv)
                            j += 1
                        else:
                            break
                cloud = {"layers": int(layers), "h": hs}
                i = j
                continue
            i += 1
            continue

        if cur in KNOWN_FIELDS:
            val = _to_float(parts[i])
            if val is not None:
                measurements[cur] = val
            i += 1
            continue

        i += 1

    return sid, measurements, status, cloud


# -------------------------- ingest logging --------------------------
INGEST_LOG_MEM: deque[str] = deque(maxlen=1000)


def log_ingest(ts: int, station_id: str, raw: str):
    line = f"{ts}\t{station_id}\t{raw}\n"
    INGEST_LOG_MEM.append(line)
    if LOG_TO_FILE:
        try:
            _ensure_log_dir()
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


# -------------------------- FastAPI app --------------------------
app = FastAPI(title="Meteo Server (parametric)")

# serve /static (index.html and client assets)
app.mount("/static", StaticFiles(directory="static", html=False), name="static")


@app.middleware("http")
async def add_no_store_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/index.html"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("static/index.html")


# --- service endpoints ---
@app.get("/health")
async def health():
    points_fields = sum(len(v) for v in store.points.values())
    return {
        "ok": True,
        "now": _now_ts(),
        "uptime_s": _now_ts() - STARTED_AT,
        "stations": len(store.stations),
        "fields_per_stations": points_fields,
        "stations_file": str(STATIONS_FILE),
        "persist": bool(PERSIST_STATIONS),
    }


@app.get("/version")
async def version():
    return {"app": APP_VERSION, "protocol": PROTOCOL_VERSION}


@app.get("/logs/tail")
async def logs_tail(n: int = Query(200, ge=1, le=1000)):
    lines = list(INGEST_LOG_MEM)[-n:]
    return {"lines": lines, "path": LOG_PATH if LOG_TO_FILE else None}


# ---------- stations ----------
class StationsListOut(BaseModel):
    items: List[Station]


@app.get("/stations/list", response_model=StationsListOut)
async def stations_list():
    return {"items": store.list_stations()}


@app.post("/stations")
async def stations_create(st: StationIn):
    s = store.add_station(lat=st.lat, lon=st.lon, name=st.name)
    return s.model_dump()


# ---------- ingest ----------
class IngestResult(BaseModel):
    ok: bool
    station_id: str
    stored: int


LAST_RAW: Dict[str, Tuple[str, int]] = {}  # sid -> (raw, ts)


@app.post("/ingest", response_model=IngestResult)
async def ingest(req: Request):
    raw_bytes = await req.body()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="empty body")
    if len(raw_bytes) > MAX_PACKET_LEN:
        raise HTTPException(status_code=413, detail="packet too large")

    raw = raw_bytes.decode("utf-8", errors="ignore").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="empty body")

    try:
        sid, measures, status, cloud = parse_packet_042(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"parse error: {e}")

    if sid not in store.stations:
        # detail intentionally contains normalized id without 'st-' for parity with prior UI messages
        short = sid[3:] if sid.startswith("st-") else sid
        raise HTTPException(status_code=404, detail=f"unknown station: {short}")

    ts = _now_ts()
    LAST_RAW[sid] = (raw, ts)
    log_ingest(ts, sid, raw)

    stored = 0
    for k, v in measures.items():
        store.add_point(sid, k, v, ts)
        stored += 1

    return {"ok": True, "station_id": sid, "stored": stored}


# ---------- ranges ----------
@app.get("/measurements/range")
async def measurements_range(station_id: str,
                             minutes: int = 60,
                             fields: str = "Sa0,Ta1,Hr1,Pa2,Or3,Rt4,Ri4,Ra4,Rs4,Hc5",
                             units: str = "metric"):
    if station_id not in store.stations:
        raise HTTPException(status_code=404, detail="station not found")
    fld = [f.strip() for f in fields.split(",") if f.strip()]
    return store.range(station_id, fld, minutes)


# ---------- status / cloud from last raw ----------
@app.get("/status/last")
async def status_last(station_id: str):
    raw, ts = LAST_RAW.get(station_id, (None, None))
    if not raw:
        return {"station_id": station_id, "status": {}, "ts": None, "cloud": None}

    status: Dict[str, str] = {}
    cloud: Optional[Dict] = None

    found = _extract_after_msr(raw)
    if found:
        _, parts = found
        i = 0
        cur = None
        while i < len(parts):
            tok = parts[i]
            m = re.fullmatch(r"([A-Za-z]{2}\d)", tok)
            if m:
                cur = m.group(1); i += 1; continue
            if cur is None:
                i += 1; continue
            if cur.startswith("Er") or cur.startswith("St"):
                if cur not in status:
                    status[cur] = parts[i]
                i += 1; continue
            if cur == "Hc5":
                layers = _to_float(parts[i])
                if layers is not None:
                    hs: List[float] = []
                    j = i + 1
                    for _ in range(4):
                        if j < len(parts):
                            vv = _to_float(parts[j])
                            if vv is not None:
                                hs.append(vv); j += 1
                            else:
                                break
                    cloud = {"layers": int(layers), "h": hs}
                    i = j; continue
            i += 1

    return {"station_id": station_id, "status": status, "ts": ts, "cloud": cloud}


# ---------- TCP MES0 server ----------
def _try_extract_line(buf: bytes) -> Optional[str]:
    # allow plain ASCII without control chars, or wrapped with STX/ETX
    s = buf.decode("ascii", errors="ignore")
    if "MSR" in s and "\x03" not in s:
        return s.strip()
    try:
        stx = buf.index(b"\x02")
        etx = buf.index(b"\x03", stx + 1)
        payload = buf[stx + 1: etx].decode("ascii", errors="ignore").strip()
        return payload
    except ValueError:
        return None


async def run_mes0_tcp_server(host: str = "0.0.0.0", port: int = 9001):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            buf = await reader.read(4096)
            if not buf:
                return
            text = _try_extract_line(buf)
            if not text or "MSR" not in text:
                return

            try:
                sid, measures, _status, _cloud = parse_packet_042(text)
            except Exception:
                return
            if sid not in store.stations:
                return

            ts = _now_ts()
            LAST_RAW[sid] = (text, ts)
            log_ingest(ts, sid, text)

            for k, v in measures.items():
                store.add_point(sid, k, v, ts)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle, host=host, port=port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    print(f"[tcp] MES0 server on {addrs}")
    async with server:
        await server.serve_forever()


# ---------- Telegram demo alerts ----------
async def run_demo_telegram_alerts():
    import httpx
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[telegram] skipped (no TOKEN/CHAT_ID)")
        return
    print("[telegram] demo alerts started (period=10s)")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    i = 0
    while True:
        try:
            i += 1
            txt = f"Demo alert {i} @ {_now_ts()}"
            async with httpx.AsyncClient(timeout=10) as cli:
                await cli.post(url, json={"chat_id": chat_id, "text": txt})
        except Exception:
            pass
        await asyncio.sleep(10)


# ---------- demo filler ----------
@app.post("/demo/fill")
async def demo_fill():
    if not store.stations:
        s = store.add_station(59.871644, 29.819128, "Station")
        store.add_station(59.93, 30.31, "Station")
        for k, v in {"Sa0": 3.5, "Ta1": 10.5, "Hr1": 29, "Pa2": 1002.8}.items():
            store.add_point(s.id, k, v, _now_ts())
    return {"ok": True}


# ---------- startup hooks ----------
@app.on_event("startup")
async def _startup():
    if ENABLE_TCP:
        asyncio.create_task(run_mes0_tcp_server(host="0.0.0.0", port=9001))
    if DEMO_TG:
        asyncio.create_task(run_demo_telegram_alerts())
