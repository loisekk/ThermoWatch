"""Live OSM scene context for the 3D incident scene (Session 23.5).

Real building footprints/trees/roads/water/land-use via the Overpass API -
"real" means fetched from the world, never invented. Server-cached because OSM
edits are slow and polyline payloads are heavy; honest degradation ladder:
  - sparse stays sparse (no infill ever),
  - total provider failure => source "unavailable" (scene labels SCHEMATIC).

Instances fallback chain: overpass-api.de -> overpass.kumi.systems.
Attribution is carried in every payload (OSM ODbL).
"""
from __future__ import annotations

import re
import time
import threading
from datetime import datetime, timezone
from typing import Optional

import httpx

INSTANCES = ("https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter")
CACHE_TTL_S = 6 * 3600
FRESH_LIMIT_S = 60           # min seconds between forced refreshes per cell
DEFAULT_RADIUS_M = 1200
CAPS = {"buildings": 600, "trees": 1500, "roads": 700, "polys": 300}
QUERY_TIMEOUT_S = 60         # Overpass server-side timeout allowance
CLIENT_TIMEOUT_S = 45.0      # per-instance network timeout (kumi can be slow)
MAX_CHAIN_PASSES = 2         # cycle instances twice -> survives transient 429/504

_KIND_DEFAULT_H = {"industrial": 8.0, "commercial": 6.0,
                   "residential": 4.5, "generic": 4.0}
_HEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m?")
_CROWN_RE = re.compile(r"(\d+(?:\.\d+)?)")

_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, dict]] = {}          # key -> (ts, doc)
_INFLIGHT: dict[tuple, bool] = {}                     # key -> in-flight flag
_FRESH_LAST: dict[tuple, float] = {}                  # key -> last forced ts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _height_m(tags: dict, kind: str) -> tuple[float, str]:
    m = _HEIGHT_RE.search(str(tags.get("height", "")))
    if m:
        return round(float(m.group(1)), 2), "tag:height"
    lv = str(tags.get("building:levels", "")).strip()
    if lv.isdigit():
        return round(int(lv) * 3.2, 2), "tag:levels"
    return _KIND_DEFAULT_H[kind], "estimated"


def _crown_m(tags: dict) -> float:
    m = _CROWN_RE.search(str(tags.get("diameter_crown", "8")))
    return float(m.group(1)) / 2 if m else 4.0  # diameter -> radius


def _kind(tags: dict) -> str:
    b = tags.get("building", "")
    if b in ("industrial", "warehouse", "factory", "shed", "garage"):
        return "industrial"
    if b in ("commercial", "retail", "office", "shop"):
        return "commercial"
    if b in ("residential", "house", "detached", "apartments", "hut"):
        return "residential"
    return "generic"
def _ql(lat: float, lon: float, r: int) -> str:
    a = f"(around:{r},{lat},{lon})"
    return (f"[out:json][timeout:{QUERY_TIMEOUT_S}];("
            f'way["building"]{a};node["natural"="tree"]{a};'
            f'way["natural"~"^(wood|forest)$"]{a};'
            f'way["landuse"~"^(forest|orchard|farmland|industrial|commercial|residential)$"]{a};'
            f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service)$"]{a};'
            f'way["natural"="water"]{a};);out tags geom;')


def _dist2(lat: float, lon: float, p0: list) -> float:
    return (p0[0] - lat) ** 2 + (p0[1] - lon) ** 2


def _parse(body: dict, lat: float, lon: float) -> dict:
    out = {"buildings": [], "trees": [], "roads": [],
           "wood": [], "landuse": [], "water": []}
    for el in body.get("elements", []):
        tags: dict = el.get("tags", {})
        if el.get("type") == "node" and tags.get("natural") == "tree":
            out["trees"].append({"lat": el.get("lat"), "lon": el.get("lon"),
                                 "crown_m": _crown_m(tags)})
            continue
        geom = el.get("geometry") or []
        pts = [[g["lat"], g["lon"]] for g in geom]
        # Roads are polylines (>= 2 points); everything else is a closed ring.
        if "highway" in tags and len(pts) >= 2:
            out["roads"].append({"points": pts, "cls": tags["highway"],
                                 "name": tags.get("name")})
            continue
        if not geom or len(geom) < 3:
            continue
        if "building" in tags:
            h, src = _height_m(tags, _kind(tags))
            out["buildings"].append({"id": el.get("id"), "outline": pts,
                                     "height_m": h, "height_source": src,
                                     "kind": _kind(tags), "name": tags.get("name")})
        elif tags.get("natural") == "water":
            out["water"].append({"outline": pts, "name": tags.get("name")})
        elif tags.get("natural") in ("wood", "forest") or tags.get("landuse") == "forest":
            out["wood"].append({"outline": pts, "name": tags.get("name")})
        elif "landuse" in tags:
            out["landuse"].append({"outline": pts, "kind": tags["landuse"],
                                   "name": tags.get("name")})
    # Keep the nearest-to-incident first, then enforce caps.
    out["buildings"].sort(key=lambda b: _dist2(lat, lon, b["outline"][0]))
    out["trees"].sort(key=lambda t: _dist2(lat, lon, [t["lat"], t["lon"]]))
    out["roads"].sort(key=lambda r: _dist2(lat, lon, r["points"][0]))
    out["buildings"] = out["buildings"][:CAPS["buildings"]]
    out["trees"] = out["trees"][:CAPS["trees"]]
    out["roads"] = out["roads"][:CAPS["roads"]]
    for k in ("wood", "landuse", "water"):
        out[k] = out[k][:CAPS["polys"]]
    return out


def _unavailable(lat: float, lon: float, radius_m: int) -> dict:
    return {"source": "unavailable", "snapshot_at": _now(),
            "radius_m": radius_m, "center": {"lat": lat, "lon": lon},
            "attribution": "\u00a9 OpenStreetMap contributors (ODbL)",
            "counts": {}, "buildings": [], "trees": [], "roads": [],
            "wood": [], "landuse": [], "water": []}
def _to_doc(body: dict, lat: float, lon: float, radius_m: int) -> dict:
    parsed = _parse(body, lat, lon)
    return {"source": "osm-overpass", "snapshot_at": _now(),
            "radius_m": radius_m, "center": {"lat": lat, "lon": lon},
            "attribution": "\u00a9 OpenStreetMap contributors (ODbL)",
            "counts": {k: len(v) for k, v in parsed.items()}, **parsed}


async def get_context(lat: float, lon: float, radius_m: int = DEFAULT_RADIUS_M,
                      fresh: bool = False,
                      client: Optional[httpx.AsyncClient] = None) -> dict:
    """-> cached/live OSM context doc. Never raises: total provider failure
    returns source "unavailable" so the scene degrades honestly, not blank."""
    key = (round(lat, 2), round(lon, 2), radius_m)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and not fresh and (time.time() - hit[0]) < CACHE_TTL_S:
            return hit[1]
        if _INFLIGHT.get(key):
            return _unavailable(lat, lon, radius_m)  # concurrent miss -> honest brief
        _INFLIGHT[key] = True
    try:
        ql = _ql(lat, lon, radius_m)
        own = client is None
        if own:
            client = httpx.AsyncClient(timeout=CLIENT_TIMEOUT_S,
                                       headers={"User-Agent": "ThermoWatch-SIH26162/1.0"})
        # Cycle the instance list twice: the public mirrors are flaky-transient
        # (occasional 429/504 under load) while succeeding moments later.
        for _pass in range(MAX_CHAIN_PASSES):
            for url in INSTANCES:
                try:
                    # Overpass /api/interpreter accepts the query as a POST form
                    # field (`data=`); GET with ?data= is rejected 406 by the
                    # lead instance, so POST is the reliable method everywhere.
                    r = await client.post(url, data={"data": ql})
                    r.raise_for_status()
                    doc = _to_doc(r.json(), lat, lon, radius_m)
                    with _LOCK:
                        _CACHE[key] = (time.time(), doc)
                    return doc
                except Exception:  # noqa: BLE001 - try next instance
                    continue
        if own:
            await client.aclose()
        doc = _unavailable(lat, lon, radius_m)
        with _LOCK:
            _CACHE[key] = (time.time(), doc)
        return doc
    finally:
        with _LOCK:
            _INFLIGHT.pop(key, None)


def can_refresh(lat: float, lon: float, radius_m: int) -> bool:
    key = (round(lat, 2), round(lon, 2), radius_m)
    with _LOCK:
        last = _FRESH_LAST.get(key, 0.0)
        return (time.time() - last) >= FRESH_LIMIT_S


def mark_refresh(lat: float, lon: float, radius_m: int) -> None:
    key = (round(lat, 2), round(lon, 2), radius_m)
    with _LOCK:
        _FRESH_LAST[key] = time.time()


def reset_cache() -> None:  # tests
    with _LOCK:
        _CACHE.clear()
        _INFLIGHT.clear()
        _FRESH_LAST.clear()