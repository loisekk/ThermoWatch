"""Land-cover composition for the V2 spatial features.

Honest provenance: this is a deterministic facility-proximity PROXY for the ESA
WorldCover 10 m raster, not the raster itself (that integration needs rasterio +
GeoTIFF tiles and is the documented upgrade path). It is a pure function of the
OSM registry distance, so it is offline-safe, reproducible and fast. The feature
registry labels these features "WorldCover (proxy)" for exactly this reason.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from app.data.facilities import FACILITIES
from app.services.geo import haversine_km

logger = logging.getLogger(__name__)


class LandCoverData(BaseModel):
    forest_fraction: float = 0.0
    cropland_fraction: float = 0.0
    grassland_fraction: float = 0.0
    shrubland_fraction: float = 0.0
    builtup_fraction: float = 0.0
    bareland_fraction: float = 0.0
    water_fraction: float = 0.0
    wetland_fraction: float = 0.0
    dominant_class: str = "unknown"


class LandCoverService:
    """Composition by distance band to the nearest OSM industrial facility.

    <= 2 km  : industrial estate -> built-up dominant
    2-5 km   : mixed peri-industrial fringe
    > 5 km   : rural -> cropland/forest mosaic (agri-burn + wildfire regime)
    """

    async def get_landcover(self, lat: float, lon: float, radius_km: float = 1.0) -> LandCoverData | None:
        try:
            dist = min(haversine_km(lat, lon, f["lat"], f["lon"]) for f in FACILITIES) if FACILITIES else 999.0
            if dist <= 2.0:
                return LandCoverData(
                    forest_fraction=0.08, cropland_fraction=0.10, grassland_fraction=0.05,
                    shrubland_fraction=0.07, builtup_fraction=0.70, dominant_class="builtup",
                )
            if dist <= 5.0:
                return LandCoverData(
                    forest_fraction=0.25, cropland_fraction=0.35, grassland_fraction=0.15,
                    shrubland_fraction=0.15, builtup_fraction=0.10, dominant_class="cropland",
                )
            return LandCoverData(
                forest_fraction=0.55, cropland_fraction=0.28, grassland_fraction=0.07,
                shrubland_fraction=0.10, builtup_fraction=0.0, dominant_class="forest",
            )
        except Exception as exc:  # noqa: BLE001 — defensive: landcover lookup must never break feature extraction; upstream raises assorted parse/API errors
            logger.warning("landcover lookup failed (%.2f, %.2f): %s", lat, lon, exc)
            return None


landcover_service = LandCoverService()