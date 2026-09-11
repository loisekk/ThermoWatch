"""Deterministic 14-day history seed (same contract as the Bun worker's live feed)."""
import random
import time

from app.data.facilities import FACILITIES

_R = random.Random(20260908)
DAY = 86_400_000
_FLARE = [f for f in FACILITIES if f["subtype"] in ("gas_flare", "refinery", "cement", "steel", "smelter")]
_WLD = [(30.1, 79.5, 1.1), (22.3, 79.8, 1.4), (25.6, 93.2, 0.9)]
_AGR = [(30.9, 75.8, 0.8), (29.0, 76.8, 0.7)]

def _raw(kind, lat, lon, ts):
    frp = {"flare": 60 + _R.random() * 190, "incident": 150 + _R.random() * 750,
           "wildfire": 20 + _R.random() * 160, "agri": 8 + _R.random() * 52}[kind]
    return {"latitude": lat, "longitude": lon, "frp": round(frp), "bright_ti4": round(315 + _R.random() * 120),
            "confidence": 55 + _R.randint(0, 44), "satellite": _R.choice(["VIIRS-SNPP", "VIIRS-NOAA20", "MODIS"]),
            "daynight": _R.choice("DN"), "acq_epoch_ms": ts,
            "forest_proxy": {"flare": .05, "incident": .08, "wildfire": .82, "agri": .18}[kind],
            "agri_window": {"flare": .08, "incident": .08, "wildfire": .1, "agri": .9}[kind],
            "cluster_density": {"flare": .3, "incident": .2, "wildfire": .45, "agri": .8}[kind],
            "diurnal_variance": {"flare": .12, "incident": .45, "wildfire": .7, "agri": .5}[kind]}

def generate_history():
    now = int(time.time() * 1000)
    out = []
    for day in range(13, -1, -1):
        ts = now - day * DAY
        for f in _FLARE:  # chronic sources repeat daily in the same 400 m cell
            out.append(_raw("flare", f["lat"] + _R.uniform(-0.002, 0.002), f["lon"] + _R.uniform(-0.002, 0.002),
                            ts - _R.randint(0, 10_000_000)))
        for _ in range(_R.randint(6, 12)):
            r = _R.random()
            if r < 0.15:
                f = _R.choice(FACILITIES)
                out.append(_raw("incident", f["lat"] + _R.uniform(-0.05, 0.05), f["lon"] + _R.uniform(-0.05, 0.05), ts - _R.randint(0, 80_000_000)))
            elif r < 0.6:
                la, lo, sp = _R.choice(_WLD)
                out.append(_raw("wildfire", la + _R.uniform(-sp, sp), lo + _R.uniform(-sp, sp), ts - _R.randint(0, 80_000_000)))
            else:
                la, lo, sp = _R.choice(_AGR)
                out.append(_raw("agri", la + _R.uniform(-sp, sp), lo + _R.uniform(-sp, sp), ts - _R.randint(0, 80_000_000)))
    out.sort(key=lambda r: r["acq_epoch_ms"])
    return out
