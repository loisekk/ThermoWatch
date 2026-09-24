"""Open-Meteo weather context (free, no key) for the V3 environmental features.

Offline-safe by contract:
- TW_ENRICHMENT=off (or any fetch failure) -> get_weather() returns None and the
  feature engineer applies documented climatological defaults.
- Responses are cached per (0.1 deg grid cell, day) with a TTL so a live ingest
  burst never hammers the API (near-real-time context, not a forecast product).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class WeatherData(BaseModel):
    temperature_2m: float | None = None
    relative_humidity: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    precipitation: float | None = None
    cloud_cover: float | None = None
    timestamp: datetime


def enrichment_enabled() -> bool:
    return os.environ.get("TW_ENRICHMENT", "live").strip().lower() != "off"


class WeatherService:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    TIMEOUT_S = 5.0
    TTL_S = 6 * 3600

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, WeatherData]] = {}

    @staticmethod
    def _cell_key(lat: float, lon: float) -> str:
        return f"{round(lat, 1)}:{round(lon, 1)}"

    async def get_weather(self, lat: float, lon: float, timestamp: datetime) -> WeatherData | None:
        if not enrichment_enabled():
            return None
        day = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")
        hour = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
        key = (self._cell_key(lat, lon), day)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.TTL_S:
            return hit[1]
        try:
            params: dict[str, str | float] = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation,cloud_cover",
                "timezone": "UTC",
                "start_date": day,
                "end_date": day,
            }
            async with httpx.AsyncClient(timeout=self.TIMEOUT_S) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
            hourly = data.get("hourly") or {}
            times: list[str] = hourly.get("time") or []
            if not times:
                return None
            idx = times.index(hour) if hour in times else 0  # earliest hour as fallback

            def _num(k: str) -> float | None:
                arr = hourly.get(k) or []
                v = arr[idx] if idx < len(arr) else None
                return float(v) if v is not None else None

            wd = WeatherData(
                temperature_2m=_num("temperature_2m"),
                relative_humidity=_num("relative_humidity_2m"),
                wind_speed=_num("wind_speed_10m"),
                wind_direction=_num("wind_direction_10m"),
                precipitation=_num("precipitation"),
                cloud_cover=_num("cloud_cover"),
                timestamp=timestamp,
            )
            self._cache[key] = (time.monotonic(), wd)
            return wd
        except Exception as exc:  # noqa: BLE001 — fetch fallback: network/DNS/timeout/HTTP raise assorted types; degrade to None (documented default path)
            logger.warning("weather fetch failed (%.2f, %.2f): %s", lat, lon, exc)
            return None


weather_service = WeatherService()


# ---------------------------------------------------------------------
# Phase 6: historical archive weather context (Open-Meteo ERA5) for the
# assessment pipeline. The WeatherService above serves live forecast
# context for v1 feature engineering; this serves OBSERVED conditions at
# a past timestamp for evidence fusion. Offline-safe by contract:
# any failure -> available=False, fusion proceeds without weather.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class WeatherContext:
    """Weather at a location and time (historical archive reading)."""
    available: bool
    temperature_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm: float | None = None
    cloud_cover_pct: float | None = None
    retrieved_at: datetime | None = None
    source: str = "open-meteo-archive"
    error: str | None = None


# Simple in-memory cache: (lat, lon, date) -> (WeatherContext, fetched_at)
_weather_cache: dict[tuple, tuple[WeatherContext, float]] = {}


async def get_weather_context(
    latitude: float, longitude: float, observed_at: datetime,
) -> WeatherContext:
    """Fetch weather at a location/time from the Open-Meteo archive.

    Cache TTL: settings.weather_cache_ttl_s (historical values are stable).
    Never raises — returns available=False on failure.
    """
    cache_key = (
        round(latitude, 2), round(longitude, 2),
        observed_at.strftime("%Y-%m-%d"),
    )

    now = time.monotonic()
    cached = _weather_cache.get(cache_key)
    if cached and (now - cached[1]) < settings.weather_cache_ttl_s:
        return cached[0]

    # Open-Meteo wants a date range; request just the observation date
    date_str = observed_at.strftime("%Y-%m-%d")
    params = {
        "latitude": round(latitude, 4),
        "longitude": round(longitude, 4),
        "start_date": date_str,
        "end_date": date_str,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                  "wind_direction_10m,precipitation,cloud_cover",
        "timezone": "UTC",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.weather_timeout_s) as client:
            resp = await client.get(settings.open_meteo_archive_url, params=params)
            resp.raise_for_status()
            data = resp.json()
            result = _parse_weather(data, observed_at)
            _weather_cache[cache_key] = (result, now)
            return result
    except httpx.TimeoutException:
        return WeatherContext(available=False, error="Open-Meteo timeout")
    except Exception as exc:  # noqa: BLE001 — offline-safe contract: degrade to available=False
        logger.warning(
            "weather archive fetch failed (%.2f, %.2f): %s", latitude, longitude, exc)
        return WeatherContext(available=False, error=str(exc))


def _parse_weather(data: dict, observed_at: datetime) -> WeatherContext:
    """Parse Open-Meteo response; find closest hourly reading to observation."""
    try:
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return WeatherContext(available=False, error="No hourly data in response")

        # Find the hour closest to observed_at
        obs_hour = observed_at.replace(minute=0, second=0, microsecond=0)
        target_str = obs_hour.strftime("%Y-%m-%dT%H:%M")

        idx = 0
        for i, t in enumerate(times):
            if t == target_str:
                idx = i
                break
            if t > target_str:
                idx = max(i - 1, 0)
                break

        def _val(key: str) -> float | None:
            arr = hourly.get(key, [])
            if idx < len(arr) and arr[idx] is not None:
                return float(arr[idx])
            return None

        return WeatherContext(
            available=True,
            temperature_c=_val("temperature_2m"),
            humidity_pct=_val("relative_humidity_2m"),
            wind_speed_kmh=_val("wind_speed_10m"),
            wind_direction_deg=_val("wind_direction_10m"),
            precipitation_mm=_val("precipitation"),
            cloud_cover_pct=_val("cloud_cover"),
            retrieved_at=datetime.now(timezone.utc),
        )
    except (KeyError, TypeError, IndexError) as exc:
        return WeatherContext(available=False, error=f"Parse error: {exc}")


def weather_fire_risk_score(weather: WeatherContext) -> float | None:
    """Composite fire-risk score from weather (0=low, 1=extreme).

    Combines: temperature, humidity, wind, no recent precipitation.
    Returns None if weather unavailable.
    """
    if not weather.available:
        return None

    # Normalize each factor to [0, 1]
    temp_score = (
        min(max((weather.temperature_c or 20) - 10, 0) / 30, 1.0)
        if weather.temperature_c else 0.5
    )
    humidity_score = 1.0 - min((weather.humidity_pct or 50) / 100, 1.0)
    wind_score = min((weather.wind_speed_kmh or 10) / 50, 1.0)
    rain_penalty = min((weather.precipitation_mm or 0) / 10, 1.0)

    # Weighted combination
    score = (
        0.30 * temp_score +
        0.30 * humidity_score +
        0.25 * wind_score +
        0.15 * (1.0 - rain_penalty)
    )
    return round(min(max(score, 0.0), 1.0), 4)