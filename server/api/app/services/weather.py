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
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

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
            params = {
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