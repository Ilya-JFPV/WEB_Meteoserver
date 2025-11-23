import time
from pathlib import Path

from meteo_server_fixed.db_sqlite import SQLiteStore


def test_sqlite_store_roundtrip(tmp_path: Path):
    db_path = tmp_path / "store.db"
    store = SQLiteStore(db_path)

    station = store.add_station(lat=10.5, lon=20.5, name="Test station")
    assert station.id.startswith("st-")
    assert store.get_station(station.id) is not None

    ts = int(time.time())
    store.add_point(station.id, "Ta1", 12.3, ts)
    store.add_point(station.id, "Ta1", 14.8, ts + 1)

    data = store.range(station.id, ["Ta1"], minutes=60)
    assert data["series"]["Ta1"] == [14.8]
    assert data["ts"][0] >= ts

    assert store.stations_count() == 1
    assert store.points_fields_count() == 1

    store_again = SQLiteStore(db_path)
    assert store_again.get_station(station.id) is not None
    persisted = store_again.range(station.id, ["Ta1"], minutes=120)
    assert persisted["series"]["Ta1"] == [14.8]
