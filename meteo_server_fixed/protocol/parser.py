"""Parser utilities for protocol 0.4.2 packets."""

import re
from typing import Dict, List, Optional, Tuple

KNOWN_FIELDS = {"Sa0", "Ta1", "Hr1", "Pa2", "Or3", "Rt4", "Ri4", "Ra4", "Rs4", "Hc5"}


def _to_float(x: str) -> Optional[float]:
    try:
        return float(x.replace(",", "."))
    except Exception:
        return None


def normalize_station_id(station_id: str) -> str:
    """Normalize station identifiers to "st-xxxxxxxx" format when possible."""
    if not station_id.startswith("st-") and re.fullmatch(r"[0-9A-Fa-f]{8}", station_id):
        return f"st-{station_id.lower()}"
    return station_id


def _extract_after_msr(text: str) -> Optional[Tuple[str, List[str]]]:
    m = re.search(r"MSR([A-Za-z0-9_\-]+)", text)
    if not m:
        return None
    sid = normalize_station_id(m.group(1))
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
            status.setdefault(cur, parts[i])
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


def parse_status_and_cloud(text: str) -> Tuple[Dict[str, str], Optional[Dict]]:
    """Extract status and cloud information from a raw packet."""
    found = _extract_after_msr(text)
    if not found:
        return {}, None

    _sid, parts = found
    status: Dict[str, str] = {}
    cloud: Optional[Dict] = None

    i = 0
    cur: Optional[str] = None
    while i < len(parts):
        tok = parts[i]
        m = re.fullmatch(r"([A-Za-z]{2}\d)", tok)
        if m:
            cur = m.group(1)
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        if cur.startswith("Er") or cur.startswith("St"):
            status.setdefault(cur, parts[i])
            i += 1
            continue
        if cur == "Hc5":
            layers = _to_float(parts[i])
            if layers is not None:
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

    return status, cloud


__all__ = [
    "KNOWN_FIELDS",
    "parse_packet_042",
    "parse_status_and_cloud",
    "normalize_station_id",
]
