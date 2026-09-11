"""WorldPop population-exposure context for the V2 spatial features.

The public WorldPop endpoint is best-effort (token-gated in some deployments);
any failure returns None and the feature engineer applies documented defaults.
Cached per 0.1 deg cell with a TTL.
"""
from __future__ import annotations

import logging
import math
import os
import time

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PopulationData(BaseModel):
    population_density: float | None = None  # people / km^2
    population_within_1km: int | None = None
    population_within_5km: int | None = None


def enrichment_enabled() -> bool:
    return os.environ.get("TW_ENRICHMENT", "live").strip().lower() != "off"


class PopulationService:
    BASE_URL = "https://api.worldpop.org/v1/data/population"
    TIMEOUT_S = 5.0
    TTL_S = 24 * 3600

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, PopulationData]] = {}

    async def get_population(self, lat: float, lon: float) -> PopulationData | None:
        if not enrichment_enabled():
            return None
        key = f"{round(lat, 1)}:{round(lon, 1)}"
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.TTL_S:
            return hit[1]
        try:
            params = {"lat": lat, "lon": lon, "dataset": "wpgp_2020"}
            async with httpx.AsyncClient(timeout=self.TIMEOUT_S) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
            density = None
            if isinstance(data, dict):
                pop = data.get("population")
                if isinstance(pop, dict):
                    density = pop.get("density")
            if density is None:
                return None
            density = float(density)
            pd_ = PopulationData(
                population_density=density,
                population_within_1km=int(density * math.pi),          # pi * 1^2 km^2
                population_within_5km=int(density * math.pi * 25.0),   # pi * 5^2 km^2
            )
            self._cache[key] = (time.monotonic(), pd_)
            return pd_
        except Exception as exc:  # noqa: BLE001 — fetch fallback: network/DNS/HTTP raise assorted types; degrade to None (documented default path)
            logger.warning("population fetch failed (%.2f, %.2f): %s", lat, lon, exc)
            return None


population_service = PopulationService()