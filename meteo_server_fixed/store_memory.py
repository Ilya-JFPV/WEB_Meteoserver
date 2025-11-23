from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models.store import Station, StoreProtocol, generate_station_id, now_ts


class MemoryStore(StoreProtocol):
    def __init__(self, stations_file: Optional[Path] = None, persist_stations: bool = True,
                 max_points_per_field: int = 5000, trim_to: int = 2000):
        self.stations: Dict[str, Station] = {}
        self.points: Dict[str, Dict[str, List[Tuple[int, float]]]] = {}
        self.stations_file = stations_file
        self.persist_enabled = persist_stations and stations_file is not None
        self.max_points_per_field = max_points_per_field
        self.trim_to = trim_to
        if self.persist_enabled:
            self._load_stations()

    # ---- persistence ----
    def _load_stations(self) -> None:
        if not self.stations_file or not self.stations_file.exists():
            return
        try:
            with open(self.stations_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(items, list):
                return
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
                if sid and not sid.startswith("st-") and re.fullmatch(r"[0-9A-Fa-f]{8}", sid):
                    sid = f"st-{sid.lower()}"
                code = it.get("code") or sid
                st = Station(id=sid, code=code, name=name, lat=float(lat), lon=float(lon))
                self.stations[sid] = st
            print(f"[store] loaded {len(self.stations)} station(s) from {self.stations_file}")
        except Exception as e:
            print(f"[store] load stations failed: {e}")

    def _save_stations(self) -> None:
        if not self.persist_enabled or not self.stations_file:
            return
        try:
            items = [s.model_dump() for s in self.stations.values()]
            self.stations_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.stations_file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": items}, f, ensure_ascii=False, indent=2)
            tmp.replace(self.stations_file)
        except Exception as e:
            print(f"[store] save stations failed: {e}")

    # --- stations ---
    def add_station(self, lat: float, lon: float, name: Optional[str] = "Station") -> Station:
        sid = generate_station_id()
        st = Station(id=sid, code=sid, name=name or "Station", lat=lat, lon=lon)
        self.stations[sid] = st
        self._save_stations()
        return st

    def list_stations(self) -> List[Station]:
        return list(self.stations.values())

    def get_station(self, station_id: str) -> Optional[Station]:
        return self.stations.get(station_id)

    # --- points ---
    def add_point(self, sid: str, field: str, value: float, ts: Optional[int] = None) -> None:
        ts = ts or now_ts()
        by_field = self.points.setdefault(sid, {})
        arr = by_field.setdefault(field, [])
        arr.append((ts, float(value)))
        if len(arr) > self.max_points_per_field:
            by_field[field] = arr[-self.trim_to:]

    def range(self, sid: str, fields: List[str], minutes: int) -> Dict:
        ts_to = now_ts()
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
