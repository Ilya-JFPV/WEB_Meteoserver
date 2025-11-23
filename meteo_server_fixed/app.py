# app.py — Meteo Server (parametric, protocol 0.4.2) with persistence, status cache, TCP ingest
# Encoding: UTF-8

import asyncio
import json
import logging
import logging.config
import logging.handlers
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, Query, Header, Response
from fastapi.responses import HTMLResponse, FileResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from protocol.parser import normalize_station_id, parse_packet_042, parse_status_and_cloud

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
APP_LOG_PATH = os.getenv("APP_LOG_PATH", os.path.join(LOG_DIR, "app.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_ROTATE_BYTES = int(os.getenv("LOG_ROTATE_BYTES", str(2 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# persistence
PERSIST_STATIONS = int(os.getenv("PERSIST_STATIONS", "1"))
BASE_DIR = Path(__file__).resolve().parent
_ST_PATH_ENV = os.getenv("STATIONS_PATH", "stations.json")
STATIONS_FILE: Path = Path(_ST_PATH_ENV) if Path(_ST_PATH_ENV).is_absolute() else (BASE_DIR / _ST_PATH_ENV)
STATIC_DIR = BASE_DIR / "static"

# optional subsystems
ENABLE_TCP = int(os.getenv("ENABLE_TCP", "1"))                    # 1 — run TCP MES0 on port 9001
DEMO_TG = os.getenv("DEMO_TELEGRAM_ALERTS", "0") == "1"           # 1 — run demo Telegram alerts
_demo_alert_task: Optional[asyncio.Task] = None

# auth
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
API_KEY = os.getenv("API_KEY")

STARTED_AT = int(time.time())


# -------------------------- logging setup --------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "station_id": getattr(record, "station_id", ""),
            "metric_count": getattr(record, "metric_count", 0),
            "error": getattr(record, "error", ""),
            "raw": getattr(record, "raw", ""),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging():
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JsonFormatter,
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "level": LOG_LEVEL,
            },
            "app_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "json",
                "level": LOG_LEVEL,
                "filename": APP_LOG_PATH,
                "when": "midnight",
                "backupCount": 7,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "meteo": {
                "handlers": ["console", "app_file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
        },
    }

    if LOG_TO_FILE:
        config["handlers"]["ingest_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "level": LOG_LEVEL,
            "filename": LOG_PATH,
            "maxBytes": 1_048_576,
            "backupCount": 5,
            "encoding": "utf-8",
        }
        config["loggers"]["meteo.ingest"] = {
            "handlers": ["console", "app_file", "ingest_file"],
            "level": LOG_LEVEL,
            "propagate": False,
        }
    else:
        config["loggers"]["meteo.ingest"] = {
            "handlers": ["console", "app_file"],
            "level": LOG_LEVEL,
            "propagate": False,
        }

    config["loggers"]["meteo.store"] = config["loggers"]["meteo.ingest"]

    logging.config.dictConfig(config)


configure_logging()
logger = logging.getLogger("meteo")
ingest_logger = logging.getLogger("meteo.ingest")
store_logger = logging.getLogger("meteo.store")


# -------------------------- utils --------------------------
def _now_ts() -> int:
    return int(time.time())


def _ensure_log_dir():
    if LOG_TO_FILE and not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        # capture custom extras
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            }
        }
        if extras:
            data.update(extras)
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging():
    _ensure_log_dir()
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        }
    }

    if LOG_TO_FILE:
        handlers["app_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": APP_LOG_PATH,
            "maxBytes": LOG_ROTATE_BYTES,
            "backupCount": LOG_BACKUP_COUNT,
            "encoding": "utf-8",
        }
        handlers["ingest_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": LOG_PATH,
            "maxBytes": LOG_ROTATE_BYTES,
            "backupCount": LOG_BACKUP_COUNT,
            "encoding": "utf-8",
        }

    ingest_handlers = ["console"] + (["ingest_file"] if LOG_TO_FILE else [])
    root_handlers = ["console"] + (["app_file"] if LOG_TO_FILE else [])

    logging.config.dictConfig(
        {
            "version": 1,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": handlers,
            "root": {"level": LOG_LEVEL, "handlers": root_handlers},
            "loggers": {
                "meteo_server.ingest": {
                    "handlers": ingest_handlers,
                    "level": LOG_LEVEL,
                    "propagate": False,
                }
            },
        }
    )


setup_logging()
logger = logging.getLogger("meteo_server")
ingest_logger = logging.getLogger("meteo_server.ingest")


# -------------------------- metrics --------------------------
METRICS_REGISTRY = CollectorRegistry()
INGEST_PACKETS_TOTAL = Counter(
    "meteo_ingest_packets_total",
    "Number of ingested packets",
    ["transport"],
    registry=METRICS_REGISTRY,
)
INGEST_ERRORS_TOTAL = Counter(
    "meteo_ingest_errors_total",
    "Number of ingest errors",
    ["type"],
    registry=METRICS_REGISTRY,
)
INGEST_DURATION_SECONDS = Histogram(
    "meteo_ingest_duration_seconds",
    "Ingest handler duration in seconds",
    registry=METRICS_REGISTRY,
)
STATIONS_TOTAL = Gauge(
    "meteo_stations_total", "Registered stations", registry=METRICS_REGISTRY
)
POINT_FIELDS_TOTAL = Gauge(
    "meteo_point_fields_total",
    "Stored measurement field buckets across stations",
    registry=METRICS_REGISTRY,
)


def update_state_metrics(store: "Store"):
    STATIONS_TOTAL.set(len(store.stations))
    points_fields = sum(len(v) for v in store.points.values())
    POINT_FIELDS_TOTAL.set(points_fields)


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias=API_KEY_HEADER),
    authorization: Optional[str] = Header(default=None),
):
    """Check API key from header against API_KEY env (no-op if key not set)."""
    if not API_KEY:
        return
    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1]
    if provided != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")


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
        self.stations_file = STATIONS_FILE
        self.persist_enabled = bool(PERSIST_STATIONS)
        if PERSIST_STATIONS:
            self._load_stations()
        update_state_metrics(self)

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
                    sid = normalize_station_id(str(sid))
                    code = it.get("code") or sid
                    st = Station(id=sid, code=code, name=name, lat=float(lat), lon=float(lon))
                    self.stations[sid] = st
                    count += 1
                logger.info(
                    "[store] loaded stations",
                    extra={"count": count, "path": str(STATIONS_FILE)},
                )
        except Exception as e:
            logger.exception("[store] load stations failed", extra={"error": str(e)})

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
            logger.exception("[store] save stations failed", extra={"error": str(e)})

    # --- stations ---
    def add_station(self, lat: float, lon: float, name: Optional[str] = "Station") -> Station:
        suffix = f"{_now_ts():08x}"[-8:]
        sid = f"st-{suffix}"
        st = Station(id=sid, code=sid, name=name or "Station", lat=lat, lon=lon)
        self.stations[sid] = st
        self._save_stations()
        update_state_metrics(self)
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
        update_state_metrics(self)

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

    # --- meta ---
    def stations_count(self) -> int:
        return len(self.stations)

    def points_fields_count(self) -> int:
        return sum(len(v) for v in self.points.values())


store = Store()


def get_store_dep() -> Store:
    return store


# -------------------------- ingest logging --------------------------
INGEST_LOG_MEM: deque[str] = deque(maxlen=1000)

INGEST_SUCCESS_COUNTER = Counter(
    "meteo_ingest_success_total",
    "Number of successfully ingested packets",
    labelnames=["station_id"],
    registry=METRICS_REGISTRY,
)
INGEST_ERROR_COUNTER = Counter(
    "meteo_ingest_error_total",
    "Number of ingest errors grouped by reason",
    labelnames=["reason"],
    registry=METRICS_REGISTRY,
)
INGEST_PARSE_DURATION = Histogram(
    "meteo_ingest_parse_seconds",
    "Time spent parsing ingest payloads",
    registry=METRICS_REGISTRY,
)
INGEST_SAVE_DURATION = Histogram(
    "meteo_ingest_save_seconds",
    "Time spent saving ingest payloads",
    registry=METRICS_REGISTRY,
)


def log_ingest(ts: int, station_id: str, raw: str, metric_count: int = 0, error: str = ""):
    entry = {
        "ts": ts,
        "station_id": station_id,
        "metric_count": metric_count,
        "error": error,
        "raw": raw,
    }
    line = json.dumps(entry, ensure_ascii=False)
    INGEST_LOG_MEM.append(line)
    ingest_logger.info(
        "ingest packet accepted",
        extra={"ts": ts, "station_id": station_id, "raw": raw},
    )


# -------------------------- FastAPI app --------------------------
app = FastAPI(title="Meteo Server (parametric)")

# serve /static (index.html and client assets)
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")


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
async def health(store_dep: Store = Depends(get_store_dep)):
    points_fields = store_dep.points_fields_count()
    return {
        "ok": True,
        "now": _now_ts(),
        "uptime_s": _now_ts() - STARTED_AT,
        "stations": store_dep.stations_count(),
        "fields_per_stations": points_fields,
        "stations_file": str(store_dep.stations_file) if store_dep.stations_file else None,
        "persist": bool(store_dep.persist_enabled),
    }


@app.get("/version")
async def version():
    return {"app": APP_VERSION, "protocol": PROTOCOL_VERSION}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(METRICS_REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/logs/tail")
async def logs_tail(n: int = Query(200, ge=1, le=1000), auth=Depends(require_api_key)):
    lines = list(INGEST_LOG_MEM)[-n:]
    return {"lines": lines, "path": LOG_PATH if LOG_TO_FILE else None}


# ---------- stations ----------
class StationsListOut(BaseModel):
    items: List[Station]


@app.get("/stations/list", response_model=StationsListOut)
async def stations_list(store_dep: Store = Depends(get_store_dep)):
    return {"items": store_dep.list_stations()}


@app.post("/stations")
async def stations_create(st: StationIn, auth=Depends(require_api_key)):
    s = store.add_station(lat=st.lat, lon=st.lon, name=st.name)
    return s.model_dump()


# ---------- ingest ----------
class IngestResult(BaseModel):
    ok: bool
    station_id: str
    stored: int


LAST_RAW: Dict[str, Tuple[str, int]] = {}  # sid -> (raw, ts)


@app.post("/ingest", response_model=IngestResult)
async def ingest(
    req: Request,
    store_dep: Store = Depends(get_store_dep),
    auth=Depends(require_api_key),
):
    started = time.perf_counter()
    sid: Optional[str] = None
    raw_bytes = await req.body()
    if not raw_bytes:
        INGEST_ERRORS_TOTAL.labels(type="empty_body").inc()
        raise HTTPException(status_code=400, detail="empty body")
    if len(raw_bytes) > MAX_PACKET_LEN:
        INGEST_ERRORS_TOTAL.labels(type="too_large").inc()
        raise HTTPException(status_code=413, detail="packet too large")

    raw = raw_bytes.decode("utf-8", errors="ignore").strip()
    if not raw:
        INGEST_ERRORS_TOTAL.labels(type="empty_body").inc()
        raise HTTPException(status_code=400, detail="empty body")

    parse_started = time.perf_counter()
    try:
        sid, measures, status, cloud = parse_packet_042(raw)
    except Exception as e:
        INGEST_ERRORS_TOTAL.labels(type="parse_error").inc()
        raise HTTPException(status_code=400, detail=f"parse error: {e}")
    INGEST_PARSE_DURATION.observe(time.perf_counter() - parse_started)

    if not store_dep.get_station(sid):
        # detail intentionally contains normalized id without 'st-' for parity with prior UI messages
        short = sid[3:] if sid.startswith("st-") else sid
        INGEST_ERRORS_TOTAL.labels(type="unknown_station").inc()
        raise HTTPException(status_code=404, detail=f"unknown station: {short}")

    try:
        ts = _now_ts()
        LAST_RAW[sid] = (raw, ts)
        log_ingest(ts, sid, raw)

        stored = 0
        for k, v in measures.items():
            store_dep.add_point(sid, k, v, ts)
            stored += 1

        INGEST_PACKETS_TOTAL.labels(transport="http").inc()
        INGEST_DURATION_SECONDS.observe(time.perf_counter() - started)
        logger.info(
            "ingest handled",
            extra={"station_id": sid, "stored": stored, "status_tags": list(status.keys())},
        )

        return {"ok": True, "station_id": sid, "stored": stored}
    except HTTPException:
        raise
    except Exception as exc:
        INGEST_ERRORS_TOTAL.labels(type="unexpected").inc()
        logger.exception("ingest failed", extra={"station_id": sid, "error": str(exc)})
        raise HTTPException(status_code=500, detail="ingest failed")


# ---------- ranges ----------
@app.get("/measurements/range")
async def measurements_range(station_id: str,
                             minutes: int = 60,
                             fields: str = "Sa0,Ta1,Hr1,Pa2,Or3,Rt4,Ri4,Ra4,Rs4,Hc5",
                             units: str = "metric",
                             store_dep: Store = Depends(get_store_dep)):
    if not store_dep.get_station(station_id):
        raise HTTPException(status_code=404, detail="station not found")
    fld = [f.strip() for f in fields.split(",") if f.strip()]
    return store_dep.range(station_id, fld, minutes)


# ---------- status / cloud from last raw ----------
@app.get("/status/last")
async def status_last(station_id: str):
    raw, ts = LAST_RAW.get(station_id, (None, None))
    if not raw:
        return {"station_id": station_id, "status": {}, "ts": None, "cloud": None}

    status, cloud = parse_status_and_cloud(raw)

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
                INGEST_ERRORS_TOTAL.labels(type="tcp_parse_error").inc()
                return
            if sid not in store.stations:
                INGEST_ERRORS_TOTAL.labels(type="tcp_unknown_station").inc()
                return

            ts = _now_ts()
            LAST_RAW[sid] = (text, ts)
            log_ingest(ts, sid, text, metric_count=len(measures))

            for k, v in measures.items():
                store.add_point(sid, k, v, ts)
            INGEST_PACKETS_TOTAL.labels(transport="tcp").inc()
            logger.info(
                "tcp ingest handled",
                extra={"station_id": sid, "stored": len(measures)},
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                INGEST_ERRORS_TOTAL.labels(type="tcp_close_error").inc()

    server = await asyncio.start_server(handle, host=host, port=port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("[tcp] MES0 server started", extra={"addr": addrs})
    async with server:
        await server.serve_forever()


# ---------- Telegram demo alerts ----------
async def run_demo_telegram_alerts(period_sec: int = 10):
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("[telegram] skipped (no TOKEN/CHAT_ID)")
        return

    logger.info("[telegram] demo alerts started", extra={"period_s": period_sec})
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    i = 0

    async with httpx.AsyncClient(timeout=10) as cli:
        try:
            while True:
                i += 1
                txt = f"Demo alert {i} @ {_now_ts()}"
                try:
                    await cli.post(url, json={"chat_id": chat_id, "text": txt})
                except asyncio.CancelledError:
                    logger.info("[telegram] demo alerts stopped")
                    raise
                except Exception:
                    logger.exception("[telegram] send demo alert failed")

                try:
                    await asyncio.sleep(max(1, period_sec))
                except asyncio.CancelledError:
                    logger.info("[telegram] demo alerts stopped")
                    raise
        except asyncio.CancelledError:
            logger.info("[telegram] demo alerts stopped")
            raise


async def start_demo_alerts(period_sec: int = 10):
    global _demo_alert_task

    if _demo_alert_task and not _demo_alert_task.done():
        return {"ok": True, "status": "already_running"}

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}

    _demo_alert_task = asyncio.create_task(run_demo_telegram_alerts(period_sec=period_sec))
    return {"ok": True, "period_sec": period_sec}


async def stop_demo_alerts():
    global _demo_alert_task

    if not _demo_alert_task:
        return {"ok": True, "status": "not_running"}

    if _demo_alert_task.done():
        _demo_alert_task = None
        return {"ok": True, "status": "not_running"}

    _demo_alert_task.cancel()
    try:
        await _demo_alert_task
    except asyncio.CancelledError:
        pass
    _demo_alert_task = None
    return {"ok": True, "status": "stopped"}


@app.post("/alerts/demo/start")
async def alerts_demo_start(period_sec: int = Query(10, ge=1, le=3600)):
    return await start_demo_alerts(period_sec=period_sec)


@app.post("/alerts/demo/stop")
async def alerts_demo_stop():
    return await stop_demo_alerts()


# ---------- demo filler ----------
@app.post("/demo/fill")
async def demo_fill(
    store_dep: Store = Depends(get_store_dep), auth=Depends(require_api_key)
):
    if not store_dep.stations:
        s = store_dep.add_station(59.871644, 29.819128, "Station")
        store_dep.add_station(59.93, 30.31, "Station")
        for k, v in {"Sa0": 3.5, "Ta1": 10.5, "Hr1": 29, "Pa2": 1002.8}.items():
            store_dep.add_point(s.id, k, v, _now_ts())
    return {"ok": True}


# ---------- startup hooks ----------
@app.on_event("startup")
async def _startup():
    if ENABLE_TCP:
        asyncio.create_task(run_mes0_tcp_server(host="0.0.0.0", port=9001))
    if DEMO_TG:
        await start_demo_alerts()
