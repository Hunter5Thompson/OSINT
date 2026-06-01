from __future__ import annotations

import html
import math
import re
from html.parser import HTMLParser


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("br", "p", "li"):
            self.parts.append(" ")


_WS = re.compile(r"\s+")


def clean_html(value: str) -> str:
    s = _Stripper()
    s.feed(html.unescape(value))
    return _WS.sub(" ", "".join(s.parts)).strip()


def latest_year_value(field: dict) -> str:
    if "text" in field:
        return clean_html(str(field["text"]))
    best_key, best_year = None, -1
    for k, v in field.items():
        if k == "note" or not isinstance(v, dict) or "text" not in v:
            continue
        m = re.search(r"(\d{4})\b", k)
        year = int(m.group(1)) if m else 0
        if year >= best_year:
            best_key, best_year = k, year
    return clean_html(str(field[best_key]["text"])) if best_key else ""


def format_composite(field: dict, parts: list[str]) -> str:
    out = []
    for p in parts:
        v = field.get(p)
        if isinstance(v, dict) and "text" in v:
            out.append(f"{p} {clean_html(str(v['text']))}")
    return " · ".join(out)


def _haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def is_plausible_capital(
    lat: float,
    lon: float,
    c_lat: float,
    c_lon: float,
    max_km: float = 5000.0,
) -> bool:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return _haversine_km(lat, lon, c_lat, c_lon) <= max_km
