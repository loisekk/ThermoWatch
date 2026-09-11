"""Canonical feature contract shared by training, inference and projection."""
from __future__ import annotations

import zlib

CLASSES = [
    "refinery", "steel", "gas_flare", "cement", "smelter",
    "waste_incineration", "power_plant", "chemical", "unknown_industrial", "natural_fire",
]
INDUSTRIAL_LABELS = CLASSES[:9]
DIST_SENTINEL_KM = 25.0  # "no facility within 25 km"
HAZARD_ENC = {"G-I": 0, "G-II": 1, "G-III": 2}

FEATURE_ORDER = [
    "frp", "brightness_k", "night_ratio", "diurnal_variance", "persist_days",
    "facility_distance_km", "facility_hazard_enc", "forest_proxy", "agri_window",
    "cluster_density", "detections_30d", "frp_stability",
]


def feature_vector(f: dict) -> list[float]:
    dist = f.get("facility_distance_km")
    return [
        float(f.get("frp", 0.0)),
        float(f.get("brightness_k", 320.0)),
        float(f.get("night_ratio", 0.3)),
        float(f.get("diurnal_variance", 0.4)),
        float(f.get("persist_days", 0)),
        DIST_SENTINEL_KM if dist is None else min(float(dist), DIST_SENTINEL_KM),
        float(HAZARD_ENC.get(f.get("facility_hazard") or "", 0)),
        float(f.get("forest_proxy", 0.2)),
        float(f.get("agri_window", 0.1)),
        float(f.get("cluster_density", 0.3)),
        float(f.get("detections_30d", 0)),
        float(f.get("frp_stability", 0.5)),
    ]


# ---------------------------------------------------------------------------
# Session 20 (server): versioned multimodal feature registry (tw-multimodal-v2).
# The v1 contract above is preserved unchanged (train/inference/pipeline keep
# serving it); the registry documents the expanded 46-feature contract and
# multimodal_feature_vector() is its canonical encoder.
# ---------------------------------------------------------------------------
from enum import Enum

from pydantic import BaseModel


class FeatureSetVersion(str, Enum):
    V1_FIRMS = "v1"
    V2_SPATIAL = "v2"
    V3_ENVIRONMENTAL = "v3"
    V4_SPATIOTEMPORAL = "v4"


class FeatureMetadata(BaseModel):
    name: str
    source: str  # FIRMS, OSM, Open-Meteo, WorldPop, WorldCover (proxy), Derived
    unit: str
    description: str
    version: FeatureSetVersion


def _f(name: str, source: str, unit: str, description: str, version: FeatureSetVersion) -> tuple[str, FeatureMetadata]:
    return name, FeatureMetadata(name=name, source=source, unit=unit, description=description, version=version)


FEATURE_REGISTRY: dict[str, FeatureMetadata] = dict([
    # -- V1 legacy contract (12) --
    _f("frp", "FIRMS", "MW", "Fire Radiative Power", FeatureSetVersion.V1_FIRMS),
    _f("brightness_k", "FIRMS", "K", "I-4 brightness temperature (v1 alias brightness_ti4)", FeatureSetVersion.V1_FIRMS),
    _f("night_ratio", "FIRMS", "fraction", "Nighttime detection ratio over the cell window", FeatureSetVersion.V1_FIRMS),
    _f("diurnal_variance", "FIRMS", "fraction", "Diurnal acquisition variance", FeatureSetVersion.V1_FIRMS),
    _f("persist_days", "FIRMS", "days", "Consecutive detection days (STA rule)", FeatureSetVersion.V1_FIRMS),
    _f("facility_distance_km", "OSM", "km", "Distance to nearest industrial facility (sentinel 25)", FeatureSetVersion.V1_FIRMS),
    _f("facility_hazard_enc", "OSM", "ordinal", "NBC hazard class of nearest facility (0-2)", FeatureSetVersion.V1_FIRMS),
    _f("forest_proxy", "WorldCover (proxy)", "fraction", "Forest land-cover proxy", FeatureSetVersion.V1_FIRMS),
    _f("agri_window", "Derived", "fraction", "Seasonal residue-burn window prior", FeatureSetVersion.V1_FIRMS),
    _f("cluster_density", "FIRMS", "fraction", "Same-day neighbourhood density", FeatureSetVersion.V1_FIRMS),
    _f("detections_30d", "FIRMS", "count", "Detections in the last 30 days", FeatureSetVersion.V1_FIRMS),
    _f("frp_stability", "Derived", "fraction", "1 - CV of FRP over the window", FeatureSetVersion.V1_FIRMS),
    # -- V1 FIRMS raw additions (7) --
    _f("brightness_ti5", "FIRMS", "K", "VIIRS I-5 brightness temperature", FeatureSetVersion.V1_FIRMS),
    _f("brightness_delta", "Derived", "K", "TI4 - TI5 mid-IR split", FeatureSetVersion.V1_FIRMS),
    _f("confidence", "FIRMS", "0-100", "FIRMS detection confidence", FeatureSetVersion.V1_FIRMS),
    _f("scan", "FIRMS", "km", "Scan pixel dimension", FeatureSetVersion.V1_FIRMS),
    _f("track", "FIRMS", "km", "Track pixel dimension", FeatureSetVersion.V1_FIRMS),
    _f("satellite_enc", "FIRMS", "ordinal", "Stable categorical encoding of the platform", FeatureSetVersion.V1_FIRMS),
    _f("daynight_flag", "FIRMS", "binary", "1 = day acquisition, 0 = night", FeatureSetVersion.V1_FIRMS),
    # -- V2 spatial context (12) --
    _f("nearest_facility_type_enc", "OSM", "ordinal", "Subtype index of nearest facility (CLASSES order)", FeatureSetVersion.V2_SPATIAL),
    _f("facilities_within_1km", "OSM", "count", "Facilities within 1 km", FeatureSetVersion.V2_SPATIAL),
    _f("facilities_within_3km", "OSM", "count", "Facilities within 3 km", FeatureSetVersion.V2_SPATIAL),
    _f("forest_fraction", "WorldCover (proxy)", "fraction", "Forest fraction in the 1 km buffer", FeatureSetVersion.V2_SPATIAL),
    _f("cropland_fraction", "WorldCover (proxy)", "fraction", "Cropland fraction in the 1 km buffer", FeatureSetVersion.V2_SPATIAL),
    _f("grassland_fraction", "WorldCover (proxy)", "fraction", "Grassland fraction in the 1 km buffer", FeatureSetVersion.V2_SPATIAL),
    _f("shrubland_fraction", "WorldCover (proxy)", "fraction", "Shrubland fraction in the 1 km buffer", FeatureSetVersion.V2_SPATIAL),
    _f("builtup_fraction", "WorldCover (proxy)", "fraction", "Built-up fraction in the 1 km buffer", FeatureSetVersion.V2_SPATIAL),
    _f("hotspots_within_500m", "FIRMS", "count", "Other hotspots within 500 m", FeatureSetVersion.V2_SPATIAL),
    _f("cluster_size", "FIRMS", "count", "Cluster size incl. this detection", FeatureSetVersion.V2_SPATIAL),
    _f("cluster_frp_sum", "FIRMS", "MW", "Summed FRP across the cluster", FeatureSetVersion.V2_SPATIAL),
    _f("cluster_frp_mean", "FIRMS", "MW", "Mean FRP across the cluster", FeatureSetVersion.V2_SPATIAL),
    _f("population_density", "WorldPop", "people/km2", "Population density at the detection cell", FeatureSetVersion.V2_SPATIAL),
    # -- V3 environmental (7) --
    _f("temperature_2m", "Open-Meteo", "degC", "2 m air temperature at detection hour", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("relative_humidity", "Open-Meteo", "%", "Relative humidity at detection hour", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("wind_speed", "Open-Meteo", "m/s", "10 m wind speed", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("wind_direction", "Open-Meteo", "degrees", "10 m wind direction", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("precipitation", "Open-Meteo", "mm", "Precipitation at detection hour", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("cloud_cover", "Open-Meteo", "%", "Cloud cover (observation-gap prior)", FeatureSetVersion.V3_ENVIRONMENTAL),
    _f("thermal_delta", "Derived", "MW", "FRP minus local cluster mean (thermal anomaly)", FeatureSetVersion.V3_ENVIRONMENTAL),
    # -- V4 spatio-temporal (8) --
    _f("detections_7d", "FIRMS", "count", "Detections in the last 7 days", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("detections_90d", "FIRMS", "count", "Detections in the last 90 days", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("mean_frp_7d", "FIRMS", "MW", "Mean FRP over 7 days", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("max_frp_7d", "FIRMS", "MW", "Max FRP over 7 days", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("frp_std_7d", "FIRMS", "MW", "FRP std-dev over 7 days", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("frp_trend", "Derived", "MW/day", "7-day FRP linear-regression slope", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("time_since_last_detection_h", "FIRMS", "hours", "Hours since the previous detection", FeatureSetVersion.V4_SPATIOTEMPORAL),
    _f("satellite_agreement", "FIRMS", "count", "Distinct satellites detecting this cell (7 d)", FeatureSetVersion.V4_SPATIOTEMPORAL),
])

MULTIMODAL_VERSION = "tw-multimodal-v2"
MULTIMODAL_FEATURE_ORDER: list[str] = list(FEATURE_REGISTRY.keys())

_SATELLITE_ENC: dict[str, int] = {
    "VIIRS-SNPP": 0, "VIIRS-NOAA20": 1, "MODIS": 2, "VIIRS-NOAA21": 3, "unknown": 4,
}
_SUBTYPE_ENC: dict[str, int] = {name: i for i, name in enumerate(CLASSES)}  # CLASSES[8] = unknown_industrial

# Weather defaults applied when enrichment is unavailable (offline run, API
# outage, or TW_ENRICHMENT=off). Climatological midpoints: a missing value must
# never masquerade as an extreme.
WEATHER_DEFAULTS = {"temperature_2m": 20.0, "relative_humidity": 50.0, "wind_speed": 0.0,
                    "wind_direction": 0.0, "precipitation": 0.0, "cloud_cover": 0.0}


def encode_satellite(name: str | None) -> int:
    """Deterministic platform encoding (crc32 fallback; hash() is salted per process)."""
    if not name:
        return _SATELLITE_ENC["unknown"]
    if name in _SATELLITE_ENC:
        return _SATELLITE_ENC[name]
    return 100 + (zlib.crc32(name.encode("utf-8")) % 900)


def encode_subtype(subtype: str | None) -> int:
    if not subtype:
        return _SUBTYPE_ENC["unknown_industrial"]
    return _SUBTYPE_ENC.get(subtype, _SUBTYPE_ENC["unknown_industrial"])


def multimodal_feature_vector(f: dict) -> list[float]:
    """Encode a feature dict into the ordered tw-multimodal-v2 vector.

    Missing keys fall back to documented defaults/sentinels so a partially
    enriched event still yields a valid row (provenance recorded upstream).
    """
    dist = f.get("facility_distance_km")
    vals: dict[str, float] = {
        "frp": float(f.get("frp", 0.0)),
        "brightness_k": float(f.get("brightness_k", 320.0)),
        "night_ratio": float(f.get("night_ratio", 0.3)),
        "diurnal_variance": float(f.get("diurnal_variance", 0.4)),
        "persist_days": float(f.get("persist_days", 0)),
        "facility_distance_km": DIST_SENTINEL_KM if dist is None else min(float(dist), DIST_SENTINEL_KM),
        "facility_hazard_enc": float(HAZARD_ENC.get(f.get("facility_hazard") or "", 0)),
        "forest_proxy": float(f.get("forest_proxy", 0.2)),
        "agri_window": float(f.get("agri_window", 0.1)),
        "cluster_density": float(f.get("cluster_density", 0.3)),
        "detections_30d": float(f.get("detections_30d", 0)),
        "frp_stability": float(f.get("frp_stability", 0.5)),
        "brightness_ti5": float(f.get("brightness_ti5", f.get("brightness_k", 320.0))),
        "brightness_delta": float(f.get("brightness_delta", 0.0)),
        "confidence": float(f.get("confidence", 50)),
        "scan": float(f.get("scan", 0.375)),
        "track": float(f.get("track", 0.375)),
        "satellite_enc": float(f.get("satellite_enc", encode_satellite(None))),
        "daynight_flag": float(f.get("daynight_flag", 0)),
        "nearest_facility_type_enc": float(f.get("nearest_facility_type_enc", encode_subtype(None))),
        "facilities_within_1km": float(f.get("facilities_within_1km", 0)),
        "facilities_within_3km": float(f.get("facilities_within_3km", 0)),
        "forest_fraction": float(f.get("forest_fraction", 0.0)),
        "cropland_fraction": float(f.get("cropland_fraction", 0.0)),
        "grassland_fraction": float(f.get("grassland_fraction", 0.0)),
        "shrubland_fraction": float(f.get("shrubland_fraction", 0.0)),
        "builtup_fraction": float(f.get("builtup_fraction", 0.0)),
        "hotspots_within_500m": float(f.get("hotspots_within_500m", 0)),
        "cluster_size": float(f.get("cluster_size", 1)),
        "cluster_frp_sum": float(f.get("cluster_frp_sum", 0.0)),
        "cluster_frp_mean": float(f.get("cluster_frp_mean", 0.0)),
        "population_density": float(f.get("population_density", 0.0)),
        "temperature_2m": float(f.get("temperature_2m", WEATHER_DEFAULTS["temperature_2m"])),
        "relative_humidity": float(f.get("relative_humidity", WEATHER_DEFAULTS["relative_humidity"])),
        "wind_speed": float(f.get("wind_speed", WEATHER_DEFAULTS["wind_speed"])),
        "wind_direction": float(f.get("wind_direction", WEATHER_DEFAULTS["wind_direction"])),
        "precipitation": float(f.get("precipitation", WEATHER_DEFAULTS["precipitation"])),
        "cloud_cover": float(f.get("cloud_cover", WEATHER_DEFAULTS["cloud_cover"])),
        "thermal_delta": float(f.get("thermal_delta", 0.0)),
        "detections_7d": float(f.get("detections_7d", 0)),
        "detections_90d": float(f.get("detections_90d", 0)),
        "mean_frp_7d": float(f.get("mean_frp_7d", 0.0)),
        "max_frp_7d": float(f.get("max_frp_7d", 0.0)),
        "frp_std_7d": float(f.get("frp_std_7d", 0.0)),
        "frp_trend": float(f.get("frp_trend", 0.0)),
        "time_since_last_detection_h": float(f.get("time_since_last_detection_h", 999.0)),
        "satellite_agreement": float(f.get("satellite_agreement", 0)),
    }
    return [vals[name] for name in MULTIMODAL_FEATURE_ORDER]
