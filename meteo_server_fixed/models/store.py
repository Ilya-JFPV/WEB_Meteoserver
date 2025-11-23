from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from pydantic import BaseModel, Field


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


class StoreProtocol(Protocol):
    stations_file: Optional[Path]
    persist_enabled: bool

    def add_station(self, lat: float, lon: float, name: Optional[str] = "Station") -> Station:
        ...

    def list_stations(self) -> List[Station]:
        ...

    def get_station(self, station_id: str) -> Optional[Station]:
        ...

    def add_point(self, sid: str, field: str, value: float, ts: Optional[int] = None) -> None:
        ...

    def range(self, sid: str, fields: List[str], minutes: int) -> Dict:
        ...

    def stations_count(self) -> int:
        ...

    def points_fields_count(self) -> int:
        ...


def now_ts() -> int:
    return int(time.time())


def generate_station_id() -> str:
    suffix = f"{now_ts():08x}"[-8:]
    return f"st-{suffix}"
