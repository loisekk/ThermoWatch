"""Thermal signature profiles for the production source-classification heuristic.

This is the HEURISTIC's own discriminative knowledge (versioned with
HEURISTIC_VERSION in assessment.py). The research dataset generator
(app/research/dataset.py) has its own generative profiles — they are allowed to
differ; a heuristic that perfectly inverted the generator would be circular.

Keep the facility coordinates in sync with app/research/dataset.py
FACILITY_REGISTRY.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FacilitySignature:
    facility_id: str
    name: str
    facility_type: str
    latitude: float
    longitude: float


# 18-facility registry (sync with app/research/dataset.py FACILITY_REGISTRY)
FACILITY_SIGS: list[FacilitySignature] = [
    FacilitySignature("F-001", "Jamnagar Refinery", "refinery", 22.47, 70.07),
    FacilitySignature("F-002", "Reliance SEZ Refinery", "refinery", 22.30, 69.85),
    FacilitySignature("F-003", "Koyali Refinery", "refinery", 22.28, 73.17),
    FacilitySignature("F-004", "Bokaro Steel Plant", "steel", 23.67, 86.15),
    FacilitySignature("F-005", "Tata Steel Jamshedpur", "steel", 22.80, 86.20),
    FacilitySignature("F-006", "Bhilai Steel Plant", "steel", 21.19, 81.35),
    FacilitySignature("F-007", "Mumbai High Flare", "gas_flare", 19.03, 71.55),
    FacilitySignature("F-008", "KG Basin Flare", "gas_flare", 16.50, 82.30),
    FacilitySignature("F-009", "Wadi Cement Works", "cement", 17.05, 76.98),
    FacilitySignature("F-010", "Jamul Cement Plant", "cement", 21.25, 81.35),
    FacilitySignature("F-011", "Korba Aluminium Smelter", "smelter", 22.35, 82.68),
    FacilitySignature("F-012", "Hirakud Smelter", "smelter", 21.55, 83.87),
    FacilitySignature("F-013", "Delhi WtE Plant", "waste_incineration", 28.62, 77.10),
    FacilitySignature("F-014", "Mumbai WtE Facility", "waste_incineration", 19.05, 72.88),
    FacilitySignature("F-015", "Bathinda Thermal", "power_plant", 30.21, 74.95),
    FacilitySignature("F-016", "Singrauli Super Thermal", "power_plant", 24.18, 82.68),
    FacilitySignature("F-017", "Haldia Petrochemical", "chemical", 22.06, 88.11),
    FacilitySignature("F-018", "Vapi Chemical Belt", "chemical", 20.37, 72.90),
]

# Discriminative profiles: log1p(FRP) ~ N(mu, sigma) per source class.
# Deliberately broad/overlapping — the heuristic is a floor, not an oracle.
THERMAL_PROFILES: dict[str, dict[str, float]] = {
    "refinery":           {"mu": 3.4, "sigma": 0.55},
    "steel":              {"mu": 4.2, "sigma": 0.65},
    "gas_flare":          {"mu": 3.9, "sigma": 0.40},
    "cement":             {"mu": 2.7, "sigma": 0.60},
    "smelter":            {"mu": 4.5, "sigma": 0.70},
    "waste_incineration": {"mu": 2.2, "sigma": 0.50},
    "power_plant":        {"mu": 1.7, "sigma": 0.65},
    "chemical":           {"mu": 3.1, "sigma": 0.80},
    # Classes without a stable thermal signature:
    "unknown_industrial": {"mu": 3.0, "sigma": 1.20},
    "natural_fire":       {"mu": 4.4, "sigma": 1.00},
}


def nearest_facility(
    lat: float, lon: float, max_km: float = 2.0
) -> tuple[FacilitySignature | None, float]:
    """Return (FacilitySignature, distance_km) or (None, dist_to_nearest)."""
    best: FacilitySignature | None = None
    best_d = float("inf")
    r = 6371.0
    p1 = math.radians(lat)
    for f in FACILITY_SIGS:
        p2 = math.radians(f.latitude)
        dp, dl = p2 - p1, math.radians(f.longitude - lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        d = 2 * r * math.asin(math.sqrt(a))
        if d < best_d:
            best, best_d = f, d
    if best is not None and best_d <= max_km:
        return best, best_d
    return None, best_d
