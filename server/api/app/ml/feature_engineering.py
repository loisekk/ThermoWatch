"""Multimodal feature engineering (tw-multimodal-v2, 46 features).

Extracts the versioned registry contract (app.ml.features.FEATURE_REGISTRY) for a
detection: V1 FIRMS raw + legacy, V2 spatial context (OSM registry + clustering),
V3 environmental enrichment (Open-Meteo; WorldPop population), V4 spatio-temporal
aggregates over the 90-day history.

Events are accepted as FireEventOut models or plain dicts (the store and the
ingest worker use different shapes); accessors normalise both. `detected_at` is
epoch milliseconds in this codebase.

Every enrichment failure degrades to a documented default - extraction never
raises, so the ingest path can never be taken down by an external API.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.data.facilities import FACILITIES
from app.ml.features import (
    CLASSES,
    HAZARD_ENC,
    WEATHER_DEFAULTS,
    encode_satellite,
    encode_subtype,
    multimodal_feature_vector,
)
from app.services.geo import haversine_km
from app.services.landcover import LandCoverService, landcover_service
from app.services.population import PopulationService, population_service
from app.services.weather import WeatherService, weather_service

logger = logging.getLogger(__name__)

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-key accessor for model/dict polymorphism."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _epoch_ms(obj: Any) -> int:
    """Normalise detected_at: epoch-ms int in this codebase; datetime tolerated."""
    v = _get(obj, "detected_at", 0)
    if isinstance(v, datetime):
        return int(v.timestamp() * 1000)
    return int(v or 0)


def _daynight(obj: Any) -> str:
    v = _get(obj, "day_night", None)
    if v is None:
        v = _get(obj, "daynight", "N")
    return str(v)


class FeatureEngineer:
    """Async multimodal extractor; services are injectable for tests."""

    def __init__(
        self,
        weather: WeatherService | None = None,
        population: PopulationService | None = None,
        landcover: LandCoverService | None = None,
    ) -> None:
        self.weather = weather or weather_service
        self.population = population or population_service
        self.landcover = landcover or landcover_service

    # ------------------------------------------------------------------ V1/V2
    def _facility_features(self, features: dict[str, float], lat: float, lon: float) -> None:
        if not FACILITIES:
            features["facility_distance_km"] = None  # sentinel applied at encoding
            features["nearest_facility_type_enc"] = encode_subtype(None)
            features["facility_hazard_enc"] = 0.0
            features["facilities_within_1km"] = 0
            features["facilities_within_3km"] = 0
            return
        dists = sorted((haversine_km(lat, lon, f["lat"], f["lon"]), f) for f in FACILITIES)
        nearest_d, nearest = dists[0]
        features["facility_distance_km"] = nearest_d
        features["nearest_facility_type_enc"] = encode_subtype(nearest.get("subtype"))
        features["facility_hazard_enc"] = float(HAZARD_ENC.get(nearest.get("hazard") or "", 0))
        features["facilities_within_1km"] = sum(1 for d, _ in dists if d <= 1.0)
        features["facilities_within_3km"] = sum(1 for d, _ in dists if d <= 3.0)

    def _cluster_features(self, features: dict[str, float], event: Any, nearby: list[Any]) -> None:
        lat = float(_get(event, "lat", 0.0))
        lon = float(_get(event, "lon", 0.0))
        within_500 = [
            e for e in nearby
            if e is not event
            and haversine_km(lat, lon, float(_get(e, "lat", 0.0)), float(_get(e, "lon", 0.0))) <= 0.5
        ]
        frps = [float(_get(e, "frp", 0.0)) for e in within_500]
        features["hotspots_within_500m"] = len(within_500)
        features["cluster_size"] = len(within_500) + 1
        features["cluster_frp_sum"] = sum(frps) + float(_get(event, "frp", 0.0))
        features["cluster_frp_mean"] = features["cluster_frp_sum"] / features["cluster_size"]
        features["thermal_delta"] = (
            float(_get(event, "frp", 0.0)) - (sum(frps) / len(frps)) if frps else 0.0
        )

    # ------------------------------------------------------------------ V3
    async def _environment_features(self, features: dict[str, float], event: Any, dt: datetime) -> None:
        lat = float(_get(event, "lat", 0.0))
        lon = float(_get(event, "lon", 0.0))
        for k, v in WEATHER_DEFAULTS.items():
            features[k] = v
        try:
            weather = await self.weather.get_weather(lat, lon, dt)
        except Exception as exc:  # noqa: BLE001 — enrichment fallback: must not hard-crash the pipeline; weather/landcover/population services raise assorted API/error types and are expected to degrade gracefully
            logger.warning("weather enrichment skipped: %s", exc)
            weather = None
        if weather is not None:
            features["temperature_2m"] = float(weather.temperature_2m if weather.temperature_2m is not None else WEATHER_DEFAULTS["temperature_2m"])
            features["relative_humidity"] = float(weather.relative_humidity if weather.relative_humidity is not None else WEATHER_DEFAULTS["relative_humidity"])
            features["wind_speed"] = float(weather.wind_speed if weather.wind_speed is not None else WEATHER_DEFAULTS["wind_speed"])
            features["wind_direction"] = float(weather.wind_direction if weather.wind_direction is not None else WEATHER_DEFAULTS["wind_direction"])
            features["precipitation"] = float(weather.precipitation if weather.precipitation is not None else WEATHER_DEFAULTS["precipitation"])
            features["cloud_cover"] = float(weather.cloud_cover if weather.cloud_cover is not None else WEATHER_DEFAULTS["cloud_cover"])

        try:
            pop = await self.population.get_population(lat, lon)
        except Exception as exc:  # noqa: BLE001 — enrichment fallback: must not hard-crash the pipeline; population service may raise assorted API/error types
            logger.warning("population enrichment skipped: %s", exc)
            pop = None
        features["population_density"] = float(pop.population_density) if pop is not None and pop.population_density is not None else 0.0

        try:
            lc = await self.landcover.get_landcover(lat, lon, radius_km=1.0)
        except Exception as exc:  # noqa: BLE001 — enrichment fallback: must not hard-crash the pipeline; landcover service may raise assorted API/error types
            logger.warning("landcover enrichment skipped: %s", exc)
            lc = None
        if lc is not None:
            features["forest_fraction"] = float(lc.forest_fraction)
            features["cropland_fraction"] = float(lc.cropland_fraction)
            features["grassland_fraction"] = float(lc.grassland_fraction)
            features["shrubland_fraction"] = float(lc.shrubland_fraction)
            features["builtup_fraction"] = float(lc.builtup_fraction)
            # legacy forest proxy upgrades to the real land-cover signal when available
            features["forest_proxy"] = float(lc.forest_fraction)
        else:
            for k in ("forest_fraction", "cropland_fraction", "grassland_fraction",
                      "shrubland_fraction", "builtup_fraction"):
                features[k] = 0.0

    # ------------------------------------------------------------------ V4
    def _temporal_features(self, features: dict[str, float], event: Any, history: Iterable[Any]) -> None:
        now_ms = _epoch_ms(event)
        lat = float(_get(event, "lat", 0.0))
        lon = float(_get(event, "lon", 0.0))
        cell_hist = [
            e for e in history
            if e is not event
            and haversine_km(lat, lon, float(_get(e, "lat", 0.0)), float(_get(e, "lon", 0.0))) <= 1.0
        ]
        w7 = [e for e in cell_hist if now_ms - _epoch_ms(e) <= 7 * DAY_MS]
        w30 = [e for e in cell_hist if now_ms - _epoch_ms(e) <= 30 * DAY_MS]

        features["detections_7d"] = len(w7)
        features["detections_30d"] = len(w30)
        features["detections_90d"] = len(cell_hist)
        if w7:
            frps = [float(_get(e, "frp", 0.0)) for e in w7]
            features["mean_frp_7d"] = float(np.mean(frps))
            features["max_frp_7d"] = float(np.max(frps))
            features["frp_std_7d"] = float(np.std(frps)) if len(frps) > 1 else 0.0
            features["frp_trend"] = (
                float(np.polyfit(np.arange(len(frps)), frps, 1)[0]) if len(frps) >= 3 else 0.0
            )
            nights = sum(1 for e in w7 if _daynight(e) == "N")
            features["night_ratio"] = nights / len(w7)
        else:
            features["mean_frp_7d"] = 0.0
            features["max_frp_7d"] = 0.0
            features["frp_std_7d"] = 0.0
            features["frp_trend"] = 0.0
            features["night_ratio"] = 1.0 if _daynight(event) == "N" else 0.0

        if cell_hist:
            last = max(_epoch_ms(e) for e in cell_hist)
            features["time_since_last_detection_h"] = max(0.0, (now_ms - last) / HOUR_MS)
        else:
            features["time_since_last_detection_h"] = 999.0

        features["satellite_agreement"] = len({_get(e, "satellite") for e in w7 if _get(e, "satellite")})

        # Legacy-v1 derived signals retained in the v2 contract (proven predictors).
        frps30 = [float(_get(e, "frp", 0.0)) for e in w30] or [float(_get(event, "frp", 0.0))]
        mean30 = sum(frps30) / len(frps30) or 1.0
        var30 = math.sqrt(sum((v - mean30) ** 2 for v in frps30) / len(frps30))
        features["frp_stability"] = max(0.0, min(1.0, 1 - var30 / mean30))
        persist = _get(event, "persistence", None)
        features["persist_days"] = int(_get(persist, "consecutive_days", 0) or 0)

    # ------------------------------------------------------------------ main
    async def extract_features(
        self,
        event: Any,
        nearby_events: list[Any],
        all_events_90d: list[Any],
    ) -> dict[str, float]:
        """Extract the full tw-multimodal-v2 feature dict for one detection."""
        lat = float(_get(event, "lat", 0.0))
        lon = float(_get(event, "lon", 0.0))
        dt = datetime.fromtimestamp(_epoch_ms(event) / 1000, tz=timezone.utc)

        features: dict[str, float] = {}

        # V1 raw (FIRMS) -------------------------------------------------------
        bright4 = float(_get(event, "brightness_k", _get(event, "bright_ti4", 320.0)))
        ti5 = _get(event, "brightness_ti5", None)
        features["frp"] = float(_get(event, "frp", 0.0))
        features["brightness_k"] = bright4
        features["brightness_ti5"] = float(ti5) if ti5 is not None else bright4
        features["brightness_delta"] = bright4 - features["brightness_ti5"]
        features["confidence"] = float(_get(event, "confidence", 50))
        features["scan"] = float(_get(event, "scan", 0.375))
        features["track"] = float(_get(event, "track", 0.375))
        features["satellite_enc"] = float(encode_satellite(_get(event, "satellite")))
        features["daynight_flag"] = 1.0 if _daynight(event) == "D" else 0.0

        # V1 legacy per-event fields (history-derived ones filled in _temporal_features)
        features["diurnal_variance"] = float(_get(event, "diurnal_variance", 0.4))
        features["agri_window"] = float(_get(event, "agri_window", 0.1))
        features["cluster_density"] = float(_get(event, "cluster_density", 0.3))
        # legacy forest proxy default; replaced by real land cover when enrichment succeeds
        features["forest_proxy"] = float(_get(event, "forest_proxy", 0.2))

        # V2 spatial -------------------------------------------------------------
        self._facility_features(features, lat, lon)
        self._cluster_features(features, event, nearby_events)

        # V3 environmental (async enrichment; offline-safe) ------------------------
        await self._environment_features(features, event, dt)

        # V4 spatio-temporal --------------------------------------------------------
        self._temporal_features(features, event, all_events_90d)

        return features

    async def extract_vector(
        self,
        event: Any,
        nearby_events: list[Any],
        all_events_90d: list[Any],
    ) -> list[float]:
        """Convenience: ordered tw-multimodal-v2 row ready for the classifier."""
        features = await self.extract_features(event, nearby_events, all_events_90d)
        return multimodal_feature_vector(features)

    def class_names(self) -> list[str]:
        return list(CLASSES)


feature_engineer = FeatureEngineer()