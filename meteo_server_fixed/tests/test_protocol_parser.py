import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.parser import (
    KNOWN_FIELDS,
    normalize_station_id,
    parse_packet_042,
    parse_status_and_cloud,
)


def test_parse_packet_filters_unknown_and_normalizes_station():
    raw = "prefix MSRA1B2C3D4,Sa0,1.0,Xx9,99,Ta1,2.5,Er0,ok"

    sid, measurements, status, cloud = parse_packet_042(raw)

    assert sid == "st-a1b2c3d4"
    assert measurements == {"Sa0": 1.0, "Ta1": 2.5}
    assert status == {"Er0": "ok"}
    assert cloud is None


def test_parse_packet_cloud_layers():
    raw = "MSRst-12345678,Hc5,3,100,200,300,Sa0,1"

    sid, measurements, status, cloud = parse_packet_042(raw)

    assert sid == "st-12345678"
    assert measurements["Hc5"] == 3
    assert measurements["Sa0"] == 1
    assert cloud == {"layers": 3, "h": [100.0, 200.0, 300.0]}
    assert status == {}


def test_parse_packet_rejects_missing_msr():
    with pytest.raises(ValueError):
        parse_packet_042("Sa0,1,Ta1,2")


def test_parse_status_and_cloud_tracks_first_status_only():
    raw = "MSRDEADBEEF,Er1,error,Er1,ignored,Hc5,2,500,750"

    status, cloud = parse_status_and_cloud(raw)

    assert status == {"Er1": "error"}
    assert cloud == {"layers": 2, "h": [500.0, 750.0]}


def test_normalize_station_id_pass_through_and_hex():
    assert normalize_station_id("st-abcdef12") == "st-abcdef12"
    assert normalize_station_id("ABCDEF12") == "st-abcdef12"
    assert normalize_station_id("station-01") == "station-01"
    assert "Sa0" in KNOWN_FIELDS  # sanity check tag list is accessible
