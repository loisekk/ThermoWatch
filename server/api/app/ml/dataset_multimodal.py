"""Synthetic training set for the tw-multimodal-v2 (46-feature) contract.

Extends the v1 per-class thermal signatures (dataset.py) with V1-FIRMS raw,
V2 spatial/land-cover/population, V3 weather and V4 temporal ranges so the
multimodal classifier trains entirely offline with label provenance identical
to v1: labels are KNOWN BY CONSTRUCTION - never on-site verified.
"""
from __future__ import annotations

import random

from app.ml.features import CLASSES, encode_satellite, multimodal_feature_vector

# frp, persist, night_ratio, frp_stability, forest_proxy, hazards, dist_km (v1 sig)
# plus: ti5 delta, temp C, rh %, wind m/s, population density, 7-day detections
_SIG2: dict[str, dict] = {
    "refinery":           {"frp": (150, 600),  "per": (5, 30),  "night": (0.5, 0.8), "stab": (0.70, 0.90), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2), "ti5": (-25, -12), "temp": (24, 32), "rh": (45, 65), "wind": (1, 4), "pop": (800, 4000), "det7": (3, 10)},
    "steel":              {"frp": (80, 350),   "per": (3, 20),  "night": (0.3, 0.6), "stab": (0.60, 0.85), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2), "ti5": (-20, -10), "temp": (23, 31), "rh": (45, 70), "wind": (1, 5), "pop": (800, 5000), "det7": (2, 8)},
    "gas_flare":          {"frp": (200, 1500), "per": (10, 60), "night": (0.45, 0.55), "stab": (0.90, 0.99), "forest": (0.00, 0.10), "hz": ("G-III",), "dist": (0.0, 1.0), "ti5": (-40, -25), "temp": (25, 34), "rh": (50, 80), "wind": (2, 6), "pop": (50, 800), "det7": (6, 14)},
    "cement":             {"frp": (60, 250),   "per": (5, 40),  "night": (0.3, 0.5), "stab": (0.70, 0.90), "forest": (0.00, 0.20), "hz": ("G-II",),  "dist": (0.0, 1.2), "ti5": (-18, -8),  "temp": (22, 30), "rh": (40, 65), "wind": (1, 5), "pop": (500, 3000), "det7": (2, 7)},
    "smelter":            {"frp": (100, 500),  "per": (4, 25),  "night": (0.3, 0.6), "stab": (0.50, 0.80), "forest": (0.00, 0.15), "hz": ("G-III",), "dist": (0.0, 1.2), "ti5": (-22, -12), "temp": (23, 31), "rh": (45, 70), "wind": (1, 5), "pop": (300, 2500), "det7": (2, 8)},
    "waste_incineration": {"frp": (20, 120),   "per": (2, 15),  "night": (0.2, 0.5), "stab": (0.30, 0.60), "forest": (0.00, 0.25), "hz": ("G-II",),  "dist": (0.0, 1.2), "ti5": (-15, -6),  "temp": (22, 30), "rh": (40, 70), "wind": (1, 4), "pop": (500, 4000), "det7": (1, 5)},
    "power_plant":        {"frp": (50, 200),   "per": (5, 45),  "night": (0.4, 0.6), "stab": (0.75, 0.95), "forest": (0.00, 0.15), "hz": ("G-II",),  "dist": (0.0, 1.2), "ti5": (-18, -8),  "temp": (24, 33), "rh": (45, 70), "wind": (2, 6), "pop": (100, 1500), "det7": (3, 10)},
    "chemical":           {"frp": (40, 400),   "per": (1, 8),   "night": (0.2, 0.5), "stab": (0.20, 0.50), "forest": (0.00, 0.20), "hz": ("G-III",), "dist": (0.0, 1.2), "ti5": (-15, -5),  "temp": (23, 32), "rh": (45, 75), "wind": (1, 5), "pop": (800, 5000), "det7": (1, 4)},
    "unknown_industrial": {"frp": (30, 400),   "per": (2, 20),  "night": (0.2, 0.6), "stab": (0.40, 0.70), "forest": (0.00, 0.25), "hz": ("G-II", "G-III"), "dist": (0.0, 1.0), "ti5": (-20, -8), "temp": (22, 32), "rh": (40, 75), "wind": (1, 5), "pop": (300, 4000), "det7": (1, 6)},
    "natural_fire":       {"frp": (10, 300),   "per": (1, 4),   "night": (0.1, 0.3), "stab": (0.10, 0.40), "forest": (0.60, 0.95), "hz": (),         "dist": (3.0, 25.0), "ti5": (-5, 5),   "temp": (30, 41), "rh": (15, 40), "wind": (3, 9), "pop": (0, 120),    "det7": (0, 3)},
}
_WEIGHT = {"refinery": 1.0, "steel": 0.8, "gas_flare": 0.7, "cement": 0.7, "smelter": 0.6,
           "waste_incineration": 0.5, "power_plant": 0.8, "chemical": 0.6,
           "unknown_industrial": 0.9, "natural_fire": 1.6}
_SATS = ["VIIRS-SNPP", "VIIRS-NOAA20", "MODIS"]


def _u(rng: random.Random, lo: float, hi: float) -> float:
    return lo + rng.random() * (hi - lo)


def build_synthetic_multimodal(n: int = 4000, seed: int = 7) -> tuple[list[list[float]], list[int], dict]:
    """Rows are ordered tw-multimodal-v2 vectors; labels are CLASSES indices."""
    rng = random.Random(seed)
    total_w = sum(_WEIGHT.values())
    X: list[list[float]] = []
    y: list[int] = []
    provenance: dict = {
        "mode": "synthetic-multimodal",
        "label_rule": "constructed per-class multimodal signatures (thermal + spatial + weather + temporal)",
        "generator_seed": seed,
        "enrichment": "synthetic (offline); Open-Meteo/WorldPop are live-API upgrade paths",
    }
    for label, cls in enumerate(CLASSES):
        count = max(40, int(n * _WEIGHT[cls] / total_w))
        s = _SIG2[cls]
        for _ in range(count):
            frp = _u(rng, *s["frp"])
            stab = _u(rng, *s["stab"])
            per = int(_u(rng, *s["per"]))
            night = _u(rng, *s["night"])
            forest = _u(rng, *s["forest"])
            dist = _u(rng, *s["dist"])
            det7 = max(1, int(_u(rng, *s["det7"])))
            frps7 = [max(1.0, frp * _u(rng, 0.7, 1.3)) for _ in range(det7)]
            agri = _u(rng, 0.6, 0.95) if (cls == "natural_fire" and rng.random() < 0.4) else _u(rng, 0.05, 0.30)
            daynight = "N" if rng.random() < night else "D"
            ti5_delta = _u(rng, *s["ti5"])
            builtup = max(0.0, 0.72 - forest) if s["dist"][1] <= 1.5 else max(0.0, 0.25 - forest)
            mean7 = sum(frps7) / len(frps7)
            feats = {
                # v1 legacy (12)
                "frp": frp,
                "brightness_k": 320 + frp * _u(rng, 0.05, 0.12),
                "night_ratio": night,
                "diurnal_variance": _u(rng, 0.1, 0.7),
                "persist_days": per,
                "facility_distance_km": dist if dist <= 25 else None,
                "facility_hazard": rng.choice(s["hz"]) if s["hz"] else None,
                "forest_proxy": forest,
                "agri_window": agri,
                "cluster_density": _u(rng, 0.2, 0.9) if s["dist"][1] <= 1.5 else _u(rng, 0.0, 0.3),
                "detections_30d": int(per * _u(rng, 1.5, 3.0)),
                "frp_stability": stab,
                # V1 FIRMS raw (7)
                "brightness_ti5": 320 + frp * 0.08 + ti5_delta,
                "brightness_delta": ti5_delta,
                "confidence": int(_u(rng, 55, 98) if cls != "natural_fire" else _u(rng, 35, 90)),
                "scan": _u(rng, 0.35, 0.45),
                "track": _u(rng, 0.35, 0.45),
                "satellite_enc": encode_satellite(rng.choice(_SATS)),
                "daynight_flag": 1.0 if daynight == "D" else 0.0,
                # V2 spatial (12)
                "nearest_facility_type_enc": 8 if cls == "natural_fire" else CLASSES.index(cls),
                "facilities_within_1km": 0 if dist > 1.0 else int(_u(rng, 1, 3)),
                "facilities_within_3km": 0 if dist > 3.0 else int(_u(rng, 1, 4)),
                "forest_fraction": forest,
                "cropland_fraction": _u(rng, 0.05, 0.25) if cls != "natural_fire" else _u(rng, 0.15, 0.45),
                "grassland_fraction": _u(rng, 0.02, 0.12),
                "shrubland_fraction": _u(rng, 0.03, 0.15) if cls != "natural_fire" else _u(rng, 0.05, 0.20),
                "builtup_fraction": builtup,
                "hotspots_within_500m": max(0, det7 - 1),
                "cluster_size": det7,
                "cluster_frp_sum": sum(frps7) + frp,
                "cluster_frp_mean": (sum(frps7) + frp) / (det7 + 1),
                "population_density": _u(rng, *s["pop"]),
                # V3 environmental (7)
                "temperature_2m": _u(rng, *s["temp"]),
                "relative_humidity": _u(rng, *s["rh"]),
                "wind_speed": _u(rng, *s["wind"]),
                "wind_direction": _u(rng, 0.0, 360.0),
                "precipitation": _u(rng, 0.0, 0.4) if cls != "natural_fire" else 0.0,
                "cloud_cover": _u(rng, 0.0, 60.0) if cls != "natural_fire" else _u(rng, 0.0, 15.0),
                "thermal_delta": frp - mean7,
                # V4 spatio-temporal (8)
                "detections_7d": det7,
                "detections_90d": int(det7 * _u(rng, 2.0, 5.0)),
                "mean_frp_7d": mean7,
                "max_frp_7d": max(frps7),
                "frp_std_7d": (sum((v - mean7) ** 2 for v in frps7) / len(frps7)) ** 0.5,
                "frp_trend": _u(rng, -8, 8) if cls != "gas_flare" else _u(rng, -1, 1),
                "time_since_last_detection_h": _u(rng, 1, 30) if det7 > 0 else 999.0,
                "satellite_agreement": 1 if rng.random() < 0.6 else 2,
            }
            X.append(multimodal_feature_vector(feats))
            y.append(label)
    order = list(range(len(y)))
    rng.shuffle(order)
    provenance["n_generated"] = len(y)
    return [X[i] for i in order], [y[i] for i in order], provenance


def class_counts(y: list[int]) -> dict[str, int]:
    out = {c: 0 for c in CLASSES}
    for lab in y:
        out[CLASSES[lab]] += 1
    return out