"""Training-set construction with proxy labels.

Label provenance (stated verbatim in eval-report limitations — never on-site verified):
  synthetic : labels known by construction from per-class thermal signatures (SIH26162 §27.2).
  archive   : OSM registry proximity rules —
              <=1 km specific subtype tag -> that subtype
              <=1 km generic/unknown tag  -> unknown_industrial
              >3 km from any facility     -> natural_fire   (land-cover confirm = Session 7)
              1-3 km                      -> skipped (attribution ambiguous, MODIS ±1 km)
"""
from __future__ import annotations

import csv
import random

from app.data.facilities import FACILITIES
from app.ml.features import CLASSES, feature_vector
from app.services.geo import haversine_km

DAY = 86_400_000
# frp, persist, night_ratio, frp_stability, forest_proxy, hazards, dist_km
_SIG: dict[str, dict] = {
    "refinery":           {"frp": (150, 600),  "per": (5, 30),  "night": (0.5, 0.8), "stab": (0.70, 0.90), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2)},
    "steel":              {"frp": (80, 350),   "per": (3, 20),  "night": (0.3, 0.6), "stab": (0.60, 0.85), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2)},
    "gas_flare":          {"frp": (200, 1500), "per": (10, 60), "night": (0.45, 0.55), "stab": (0.90, 0.99), "forest": (0.00, 0.10), "hz": ("G-III",), "dist": (0.0, 1.0)},
    "cement":             {"frp": (60, 250),   "per": (5, 40),  "night": (0.3, 0.5), "stab": (0.70, 0.90), "forest": (0.00, 0.20), "hz": ("G-II",), "dist": (0.0, 1.2)},
    "smelter":            {"frp": (100, 500),  "per": (4, 25),  "night": (0.3, 0.6), "stab": (0.50, 0.80), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2)},
    "waste_incineration": {"frp": (20, 120),   "per": (2, 15),  "night": (0.2, 0.5), "stab": (0.30, 0.60), "forest": (0.00, 0.25), "hz": ("G-II",), "dist": (0.0, 1.2)},
    "power_plant":        {"frp": (50, 200),   "per": (5, 45),  "night": (0.4, 0.6), "stab": (0.75, 0.95), "forest": (0.00, 0.15), "hz": ("G-II",), "dist": (0.0, 1.2)},
    "chemical":           {"frp": (40, 400),   "per": (1, 8),   "night": (0.2, 0.5), "stab": (0.20, 0.50), "forest": (0.00, 0.20), "hz": ("G-III",), "dist": (0.0, 1.2)},
    "unknown_industrial": {"frp": (30, 400),   "per": (2, 20),  "night": (0.2, 0.6), "stab": (0.40, 0.70), "forest": (0.00, 0.25), "hz": ("G-II", "G-III"), "dist": (0.0, 1.0)},
    "natural_fire":       {"frp": (10, 300),   "per": (1, 4),   "night": (0.1, 0.3), "stab": (0.10, 0.40), "forest": (0.60, 0.95), "hz": (), "dist": (3.0, 25.0)},
}
_WEIGHT = {"refinery": 1.0, "steel": 0.8, "gas_flare": 0.7, "cement": 0.7, "smelter": 0.6,
           "waste_incineration": 0.5, "power_plant": 0.8, "chemical": 0.6,
           "unknown_industrial": 0.9, "natural_fire": 1.6}


def _u(rng: random.Random, lo: float, hi: float) -> float:
    return lo + rng.random() * (hi - lo)


def build_synthetic(n: int = 4000, seed: int = 7) -> tuple[list[list[float]], list[int], dict]:
    rng = random.Random(seed)
    total_w = sum(_WEIGHT.values())
    X: list[list[float]] = []
    y: list[int] = []
    provenance: dict = {"mode": "synthetic", "label_rule": "constructed per-class thermal signatures (SIH26162 §27.2)", "generator_seed": seed}
    for label, cls in enumerate(CLASSES):
        count = max(40, int(n * _WEIGHT[cls] / total_w))
        s = _SIG[cls]
        for _ in range(count):
            frp = _u(rng, *s["frp"])
            stab = _u(rng, *s["stab"])
            per = int(_u(rng, *s["per"]))
            agri = _u(rng, 0.6, 0.95) if (cls == "natural_fire" and rng.random() < 0.45) else _u(rng, 0.05, 0.3)
            feats = {
                "frp": frp,
                "brightness_k": 310 + frp * 0.15 + _u(rng, 0, 60),
                "night_ratio": _u(rng, *s["night"]),
                "diurnal_variance": min(1.0, max(0.0, 1 - stab + _u(rng, -0.1, 0.1))),
                "persist_days": per,
                "facility_distance_km": None if not s["hz"] else _u(rng, *s["dist"]),
                "facility_hazard": rng.choice(s["hz"]) if s["hz"] else None,
                "forest_proxy": _u(rng, *s["forest"]),
                "agri_window": agri,
                "cluster_density": _u(rng, 0.7, 0.95) if agri > 0.5 else _u(rng, 0.15, 0.55),
                "detections_30d": int(per * _u(rng, 1.5, 3.0)),
                "frp_stability": stab,
            }
            X.append(feature_vector(feats))
            y.append(label)
    order = list(range(len(y)))
    rng.shuffle(order)
    provenance["n_generated"] = len(y)
    return [X[i] for i in order], [y[i] for i in order], provenance


def build_from_archive(csv_path: str) -> tuple[list[list[float]], list[int], dict]:
    """Real FIRMS archive CSV. Persistence computed per 400 m cell across days."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cells: dict[str, dict] = {}
    for r in rows:
        cell = f"{round(float(r['latitude']) / 0.004)}:{round(float(r['longitude']) / 0.004)}"
        st = cells.setdefault(cell, {"days": set(), "frps": []})
        st["days"].add(r["acq_date"])
        st["frps"].append(float(r["frp"] or 0))
    X: list[list[float]] = []
    y: list[int] = []
    prov = {"mode": "archive", "osm_specific": 0, "osm_generic": 0, "distance_natural": 0, "skipped_ambiguous": 0}
    for r in rows:
        lat, lon = float(r["latitude"]), float(r["longitude"])
        cell = f"{round(lat / 0.004)}:{round(lon / 0.004)}"
        st = cells[cell]
        nearest = min(FACILITIES, key=lambda f: haversine_km(lat, lon, f["lat"], f["lon"]))
        dist = haversine_km(lat, lon, nearest["lat"], nearest["lon"])
        if dist <= 1.0 and nearest["subtype"]:
            label = CLASSES.index(nearest["subtype"]) if nearest["subtype"] in CLASSES else 8
            prov["osm_specific"] += 1
        elif dist <= 1.0:
            label = 8
            prov["osm_generic"] += 1
        elif dist > 3.0:
            label = 9
            prov["distance_natural"] += 1
        else:
            prov["skipped_ambiguous"] += 1
            continue
        frps = st["frps"]
        mean = sum(frps) / len(frps) or 1.0
        var = (sum((v - mean) ** 2 for v in frps) / len(frps)) ** 0.5
        feats = {
            "frp": float(r["frp"] or 0), "brightness_k": float(r["bright_ti4"] or 320),
            "night_ratio": 0.9 if r["daynight"] == "N" else 0.1,
            "diurnal_variance": 0.4, "persist_days": len(st["days"]),
            "facility_distance_km": dist if dist <= 25 else None,
            "facility_hazard": nearest["hazard"] if dist <= 3 else None,
            "forest_proxy": 0.2 if label != 9 else 0.7,
            "agri_window": 0.1, "cluster_density": 0.3,
            "detections_30d": len(st["frps"]),
            "frp_stability": max(0.0, min(1.0, 1 - var / mean)),
        }
        X.append(feature_vector(feats))
        y.append(label)
    return X, y, prov


def class_counts(y: list[int]) -> dict[str, int]:
    out = {c: 0 for c in CLASSES}
    for lab in y:
        out[CLASSES[lab]] += 1
    return out


def split_stratified(X: list, y: list[int], ratios: tuple[float, float, float] = (0.7, 0.15, 0.15), seed: int = 7):
    rng = random.Random(seed)
    by: dict[int, list[int]] = {}
    for i, lab in enumerate(y):
        by.setdefault(lab, []).append(i)
    tr: list[int] = []
    va: list[int] = []
    te: list[int] = []
    for idx in by.values():
        rng.shuffle(idx)
        a, b = int(len(idx) * ratios[0]), int(len(idx) * (ratios[0] + ratios[1]))
        tr += idx[:a]; va += idx[a:b]; te += idx[b:]
    for part in (tr, va, te):
        rng.shuffle(part)
    return tr, va, te

