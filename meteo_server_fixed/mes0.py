import re
from typing import Dict, Tuple

class Mes0ParseError(Exception):
  pass

# Простейшая XOR-КС: между '$' и '*' (не включая)
def _xor_checksum(payload: bytes) -> int:
  x = 0
  for b in payload:
    x ^= b
  return x & 0xFF

# Берём «основное» значение для каждого параметра (первая цифра после тега)
# Sa0, v1,v2,... -> Sa0 := v1
# Da0, v1,...    -> Da0 := v1
# Pa2, hPa, ...  -> Pa2 := hPa
PRIMARY_ONLY = {"Sa", "Da", "Ta", "Hr", "Pa", "Or", "Ri", "Ra", "Rs", "Hc"}

_num = r"[-+]?\d+(?:[.,]\d+)?"

def parse_mes0_line(line: str) -> Tuple[str, Dict[str, float]]:
  """
  Вход: строка целиком (как из модема), например:
  MES0=?{0D}{0A}$\x02MSR2414,Sa0,3.5,...,Pa2,1002.8,752.1,,,{0x03}*69{0D}{0A}
  Возврат: (station_code, { "Sa0": 3.5, "Da0": 180, "Ta1": 10.5, "Hr1": 29, "Pa2": 1002.8, ... })
  """
  # выдёргиваем подстроку от '$' до '*cc'
  m = re.search(r"\$(.*?)\*(?P<cs>[\da-fA-F]{2})", line)
  if not m:
      raise Mes0ParseError("no_frame")
  payload_str = m.group(1)
  cs_hex = m.group("cs")

  # контрольная сумма (мягкая проверка — некоторые шлюзы портят байты)
  try:
      want = int(cs_hex, 16)
  except ValueError:
      want = None
  got = _xor_checksum(payload_str.encode("latin1", "ignore"))
  # Если нужна жёсткая проверка — раскомментировать:
  # if want is not None and want != got:
  #     raise Mes0ParseError(f"bad checksum: want {want:02X}, got {got:02X}")

  # убираем STX/ETX если вдруг остались
  payload_str = payload_str.replace("\x02", "").replace("\x03", "")

  if "," not in payload_str:
      raise Mes0ParseError("no_fields")
  parts = payload_str.split(",")
  station_code = parts[0].strip()
  items = parts[1:]

  out: Dict[str, float] = {}
  i = 0
  while i < len(items):
      tag = items[i].strip()    # напр. Sa0
      i += 1
      mtag = re.match(r"([A-Za-z]{2})(\d)$", tag)
      if not mtag:
          # пропускаем мусор
          continue
      base = mtag.group(1)   # Sa / Ta / Hr / Pa ...
      # собираем значения до следующего тега или конца
      vals = []
      while i < len(items):
          if re.match(r"^[A-Za-z]{2}\d$", items[i].strip()):
              break
          vals.append(items[i].strip())
          i += 1
      # первичное значение — первая цифра
      if base in PRIMARY_ONLY and vals:
          mnum = re.search(_num, vals[0])
          if mnum:
              try:
                  out[tag] = float(mnum.group(0).replace(",", "."))
              except ValueError:
                  pass

  if not station_code:
      raise Mes0ParseError("no_station_code")

  return station_code, out
