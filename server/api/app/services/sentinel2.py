"""Sentinel-2 optical corroboration via Copernicus Data Space Statistics API.

Uses SWIR bands (B12 ~2.2um, B11 ~1.6um) to detect active fire signatures
around a thermal anomaly. The Statistics API returns aggregate stats without
downloading full imagery — suitable for a corroboration check.

Auth: OAuth2 client_credentials via CDSE identity service.
Endpoint: https://sh.dataspace.copernicus.eu/api/v1/statistics

Contract: never raises — returns available=False on any failure so the
assessment pipeline can proceed without optical evidence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Active fire evalscript: flags pixels where B12 (SWIR-CIRRUS) is anomalously
# bright relative to B11 (SWIR-1), a classic active-fire spectral signature.
FIRE_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B12", "B11", "B08", "B04", "dataMask", "cloudMask"],
      units: "REFLECTANCE"
    }],
    output: {
      id: "fire_stats",
      bands: ["fire_pixel", "swir_ratio", "ndvi", "dataMask"],
      sampleType: "FLOAT32"
    }
  };
}

function evaluatePixel(samples) {
  // Skip cloudy or masked pixels
  if (samples.dataMask === 0 || samples.cloudMask > 0) {
    return { fire_pixel: 0, swir_ratio: 0, ndvi: 0, dataMask: 0 };
  }

  var b12 = Math.max(samples.B12, 1e-6);
  var b11 = Math.max(samples.B11, 1e-6);
  var b08 = Math.max(samples.B08, 1e-6);
  var b04 = Math.max(samples.B04, 1e-6);

  // Active fire: B12 >> B11 (SWIR ratio), high B12 absolute
  var swir_ratio = b12 / b11;
  var is_fire = (swir_ratio > 1.3 && b12 > 0.15) ? 1 : 0;

  // Vegetation index for context (burned area vs. active fire)
  var ndvi = (b08 - b04) / (b08 + b04);

  return {
    fire_pixel: is_fire,
    swir_ratio: swir_ratio,
    ndvi: ndvi,
    dataMask: 1
  };
}
"""


@dataclass(frozen=True)
class OpticalCorroboration:
    """Result of a Sentinel-2 statistics query around a thermal anomaly."""
    available: bool
    scene_date: datetime | None = None
    cloud_cover_pct: float | None = None
    n_pixels: int = 0
    n_fire_pixels: int = 0
    fire_pixel_ratio: float = 0.0
    mean_swir_ratio: float | None = None
    mean_ndvi: float | None = None
    corroborates: bool = False  # True if fire pixels detected
    error: str | None = None
    source: str = "sentinel-2-l2a"
    evalscript_version: str = "fire-v1.0"


class CDSEAuthClient:
    """OAuth2 client for Copernicus Data Space — caches token until expiry."""

    def __init__(self):
        self._token: str | None = None
        self._expires_at: float = 0

    async def get_token(self) -> str | None:
        """Get or refresh the access token."""
        if self._token and time.monotonic() < self._expires_at:
            return self._token

        if not settings.cdse_client_id or not settings.cdse_client_secret:
            logger.warning("cdse.no_credentials")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    settings.cdse_token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.cdse_client_id,
                        "client_secret": settings.cdse_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                data = resp.json()
                self._token = data["access_token"]
                # Refresh 60s before actual expiry
                self._expires_at = time.monotonic() + data.get("expires_in", 600) - 60
                return self._token
        except Exception as exc:
            logger.warning("cdse.token_failed", error=str(exc))
            return None


_cdse_auth = CDSEAuthClient()

async def check_optical_corroboration(
    latitude: float, longitude: float,
    observed_at: datetime,
    radius_m: float = 1000.0,
) -> OpticalCorroboration:
    """Query Sentinel-2 statistics around a thermal anomaly for fire evidence.

    Args:
        latitude, longitude: center of the thermal anomaly
        observed_at: when the thermal detection occurred
        radius_m: search radius in meters (default 1km)

    Returns:
        OpticalCorroboration with fire pixel statistics. Never raises —
        returns available=False on any failure.
    """
    token = await _cdse_auth.get_token()
    if not token:
        return OpticalCorroboration(
            available=False,
            error="CDSE credentials not configured or token fetch failed")

    # Time window: look back N days from observation
    end = observed_at
    start = observed_at - timedelta(days=settings.s2_lookback_days)

    request_body = {
        "input": {
            "bounds": {
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                "bbox": _bbox_around(latitude, longitude, radius_m),
            },
            "data": [{
                "dataFilter": {
                    "timeRange": {
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                    },
                },
                "type": settings.s2_data_source,
            }],
        },
        "aggregation": {
            "timeRange": {
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
            "aggregationInterval": {"of": "P1D"},  # daily aggregation
            "evalscript": FIRE_EVALSCRIPT,
            "resx": 20,  # 20m resolution (Sentinel-2 SWIR native)
        },
        "calculations": {"default": {}},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.s2_timeout_s) as client:
            resp = await client.post(
                settings.sh_statistics_url,
                json=request_body,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return OpticalCorroboration(
                    available=False,
                    error=f"SH Statistics API returned {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            return _parse_statistics_response(data)

    except httpx.TimeoutException:
        return OpticalCorroboration(available=False, error="Statistics API timeout")
    except Exception as exc:
        return OpticalCorroboration(available=False, error=str(exc))


def _bbox_around(lat: float, lon: float, radius_m: float) -> list[float]:
    """Bounding box [west, south, east, north] around a point."""
    import math
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _parse_statistics_response(data: dict) -> OpticalCorroboration:
    """Parse the Statistics API response into OpticalCorroboration."""
    try:
        # Response: {"data": [{"from": ..., "outputs": {"fire_stats": {"bands": ...}}}]}
        intervals = data.get("data", [])
        if not intervals:
            return OpticalCorroboration(available=False, error="No data in time range")

        # First interval with valid band statistics
        best = None
        for interval in intervals:
            outputs = interval.get("outputs", {})
            stats = outputs.get("fire_stats", {}).get("bands", {})
            if not stats:
                continue
            if best is None:
                best = interval

        if best is None:
            return OpticalCorroboration(available=False, error="No valid scenes in window")

        date_str = best.get("from", "")
        scene_date = (
            datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if date_str else None
        )

        bands = best["outputs"]["fire_stats"]["bands"]
        fire_stats = bands.get("fire_pixel", {}).get("stats", {})
        n_pixels = int(fire_stats.get("validCount", 0))
        sum_fire = fire_stats.get("sum", 0.0)
        n_fire = int(sum_fire) if sum_fire else 0

        swir_stats = bands.get("swir_ratio", {}).get("stats", {})
        ndvi_stats = bands.get("ndvi", {}).get("stats", {})

        # Valid-data share from dataMask (proxy for cloud/data gaps)
        dm = best.get("outputs", {}).get("dataMask", {})
        dm_stats = dm if isinstance(dm, dict) and "stats" in dm else {}
        valid_pixels = dm_stats.get("stats", {}).get("validCount", n_pixels)
        cloud_pct = (1 - valid_pixels / n_pixels) * 100 if n_pixels > 0 else 100.0

        fire_ratio = n_fire / n_pixels if n_pixels > 0 else 0.0

        # Corroborates if we see fire pixels AND data coverage is acceptable
        corroborates = n_fire > 0 and cloud_pct < settings.s2_max_cloud_pct

        return OpticalCorroboration(
            available=True,
            scene_date=scene_date,
            cloud_cover_pct=round(cloud_pct, 1),
            n_pixels=n_pixels,
            n_fire_pixels=n_fire,
            fire_pixel_ratio=round(fire_ratio, 6),
            mean_swir_ratio=round(swir_stats.get("mean", 0.0), 4) if swir_stats else None,
            mean_ndvi=round(ndvi_stats.get("mean", 0.0), 4) if ndvi_stats else None,
            corroborates=corroborates,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return OpticalCorroboration(available=False, error=f"Parse error: {exc}")