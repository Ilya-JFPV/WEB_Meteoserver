import re, json, os
from typing import Dict, Any

def load_profiles() -> dict:
    with open('protocol_profiles.json','r',encoding='utf-8') as f: return json.load(f)
PROFILES = load_profiles()

def build_config(profile: str) -> dict:
    return PROFILES.get(profile, PROFILES.get('default', {}))

def _normalize_decimal_commas(s: str) -> str:
    return re.sub(r'(?<=\d),(?=\d)', '.', s)

def parse_payload(payload: str, profile: str = 'default') -> Dict[str, Any]:
    cfg = build_config(profile)
    KEY_RE     = re.compile(cfg["key_pattern"])
    PAIR_DELIM = re.compile(cfg["pair_delims"])
    KV_STD     = re.compile(r'\b([A-Za-z]{2}\d)\s*=\s*([^;, ]+)')
    GEN_KV_RE  = re.compile(r'\b([A-Za-z_]+)\s*=\s*([^;, ]+)')
    CS_FIELD   = cfg.get("checksum",{}).get("field","CS")
    CS_RE      = re.compile(r'\b' + re.escape(CS_FIELD) + r'\s*=\s*([0-9A-Fa-fx]+)')

    s = payload.strip().replace('\r',' ').replace('\n',' ')
    s = _normalize_decimal_commas(s)
    out: Dict[str, Any] = {"_profile": profile}

    m = CS_RE.search(s)
    if m:
        claimed = m.group(1)
        s_wo_cs = CS_RE.sub('', s).strip().rstrip(',;')
        calc = sum(s_wo_cs.encode('utf-8')) % 65535
        out["_checksum_ok"] = (int(claimed,16) if claimed.lower().startswith('0x') else int(claimed)) == calc
        out["_checksum_calc"] = calc; out["_checksum_claimed"] = claimed

    for m in KV_STD.finditer(s): out[m.group(1)] = _coerce(m.group(2))
    s = KV_STD.sub('', s)

    for m in GEN_KV_RE.finditer(s):
        k, v = m.group(1), m.group(2)
        if k not in out: out[k] = _coerce(v)
    s = GEN_KV_RE.sub('', s)

    it = list(KEY_RE.finditer(s))
    arr_keys = set(cfg.get("array_keys", []))
    for i, m in enumerate(it):
        k = m.group(1); start = m.end(); end = it[i+1].start() if i+1 < len(it) else len(s)
        chunk = s[start:end].strip().strip(',')
        if not chunk: continue
        vals = [t for t in PAIR_DELIM.split(chunk) if t]
        coerced = [_coerce(v) for v in vals]
        out[k] = coerced if k in arr_keys else (coerced if len(coerced)>1 else coerced[0])
    return out

def _coerce(v: str):
    v = v.strip()
    if v.lower() in ('nan','none','null'): return None
    if re.match(r'^-?\d+\.\d+$', v): return float(v)
    if re.match(r'^-?\d+$', v): return int(v)
    return v

def pick_numeric(value):
    if isinstance(value, list):
        for v in value:
            if isinstance(v, (int, float)): return float(v)
        return None
    return float(value) if isinstance(value, (int, float)) else None
