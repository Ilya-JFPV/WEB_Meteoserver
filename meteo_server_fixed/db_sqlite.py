from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .models.store import Station, StoreProtocol, generate_station_id, now_ts


class SQLiteStore(StoreProtocol):
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else Path(__file__).resolve().parent / "meteo.db"
        self.stations_file = None
        self.persist_enabled = True
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS stations (
            id TEXT PRIMARY KEY,
            code TEXT UNIQUE,
            name TEXT,
            lat REAL,
            lon REAL
        );

        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            station_id TEXT NOT NULL,
            field TEXT NOT NULL,
            sensor_idx INTEGER,
            value REAL,
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_measurements_station_field_ts
            ON measurements (station_id, field, ts);
        """
        with self._lock:
            self._conn.executescript(ddl)

    # --- stations ---
    def add_station(self, lat: float, lon: float, name: Optional[str] = "Station") -> Station:
        sid = generate_station_id()
        station = Station(id=sid, code=sid, name=name or "Station", lat=lat, lon=lon)
        with self._lock:
            self._conn.execute(
                "INSERT INTO stations (id, code, name, lat, lon) VALUES (?, ?, ?, ?, ?)",
                (station.id, station.code, station.name, station.lat, station.lon),
            )
            self._conn.commit()
        return station

    def list_stations(self) -> List[Station]:
        with self._lock:
            cur = self._conn.execute("SELECT id, code, name, lat, lon FROM stations ORDER BY id")
            rows = cur.fetchall()
        return [Station(**dict(r)) for r in rows]

    def get_station(self, station_id: str) -> Optional[Station]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, code, name, lat, lon FROM stations WHERE id = ?",
                (station_id,),
            )
            row = cur.fetchone()
        return Station(**dict(row)) if row else None

    # --- points ---
    def add_point(self, sid: str, field: str, value: float, ts: Optional[int] = None) -> None:
        ts_val = ts or now_ts()
        if not self.get_station(sid):
            raise ValueError(f"unknown station: {sid}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO measurements (ts, station_id, field, sensor_idx, value) VALUES (?, ?, ?, ?, ?)",
                (ts_val, sid, field, None, float(value)),
            )
            self._conn.commit()

    def range(self, sid: str, fields: List[str], minutes: int) -> Dict:
        ts_to = now_ts()
        ts_from = ts_to - minutes * 60
        series: Dict[str, List[float]] = {f: [] for f in fields}
        with self._lock:
            for f in fields:
                cur = self._conn.execute(
                    """
                    SELECT value FROM measurements
                    WHERE station_id = ? AND field = ? AND ts >= ?
                    ORDER BY ts DESC LIMIT 1
                    """,
                    (sid, f, ts_from),
                )
                row = cur.fetchone()
                if row is not None and row[0] is not None:
                    series[f].append(float(row[0]))
        return {"ts": [ts_to], "series": series, "units": "metric"}

    # --- meta ---
    def stations_count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM stations")
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def points_fields_count(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(DISTINCT station_id || ':' || field) FROM measurements"
            )
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
