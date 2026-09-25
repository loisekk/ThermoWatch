"""Shared observation-position uncertainty model — ONE source of truth.

Imported by BOTH sides of the spatial contract so the experiment generator
and the detector cannot disagree about pixel physics (plan 4.1):

  * the GENERATOR (``app/research/dataset.py``) scatters a detection around a
    fixed source using ``jitter_position`` — bounded by the pixel footprint,
  * the DETECTOR (``app/ml/residuals.py::spatial_residual``) grants an
    observation the tolerance implied by ``combined_tolerance_km``.

FIRMS ``scan``/``track`` are PIXEL DIMENSIONS IN KILOMETRES (VIIRS nominal
~0.375-1.6 km, MODIS ~1.0-2.4 km) — NOT degrees. The pre-fix generator
divided the km value by 4 and treated the result as degrees, inflating the
coordinate scatter to 4-22 km; the detector then gated raw centroid distance
at a flat 1.5 km. The two disagreed about physics by ~2 orders of magnitude,
which is the false-alert mechanism this module removes.

Pure functions, no I/O, deterministic. Positions are treated as pixel CENTRES:
the true sub-pixel source lies somewhere inside the pixel footprint, so two
observations of one source may legitimately differ by up to the full diagonal.
"""
from __future__ import annotations

import math

# Mean km per degree of latitude (WGS84-ish). Longitude shrinks with cos(lat).
KM_PER_DEG_LAT = 111.32

# Conservative per-axis pixel size used when a row carries no scan/track.
DEFAULT_PIXEL_KM = 0.4  # VIIRS I-band nominal nadir footprint

# Latitudes beyond ~75 deg collapse cos(lat); clamp so km<->deg stays stable.
_MIN_LAT_FACTOR = 0.25


def pixel_half_extent_km(scan_km: float, track_km: float) -> tuple[float, float]:
    """Half-width (scan, across-track) and half-height (track, along-track) km."""
    scan = _positive(scan_km)
    track = _positive(track_km)
    return scan / 2.0, track / 2.0


def observation_radius_km(scan_km: float, track_km: float) -> float:
    """Conservative positional uncertainty radius: half the pixel diagonal.

    Any detection of one source can sit anywhere inside its own pixel, so a
    gate comparing two observations of that source must tolerate at least the
    half-diagonal *from each side* — that is what ``combined_tolerance_km``
    adds on top of the zone's measured extent.
    """
    half_w, half_h = pixel_half_extent_km(scan_km, track_km)
    return math.hypot(half_w, half_h)


def jitter_sigma_km(pixel_extent_km: float) -> float:
    """Per-axis sigma for sampling a source position inside its pixel.

    Uniform-in-pixel per axis -> sigma = a / sqrt(12), where ``a`` is the
    half-extent. Bounded by construction: the sampled point never leaves the
    footprint, unlike the pre-fix unbounded Gaussian that reached 22 km.
    """
    return (pixel_extent_km / 2.0) / math.sqrt(12.0)


def km_to_deg_lat(km: float) -> float:
    """Kilometres -> degrees of latitude."""
    return km / KM_PER_DEG_LAT


def km_to_deg_lon(km: float, latitude: float) -> float:
    """Kilometres -> degrees of longitude at ``latitude`` (cos-clamped)."""
    factor = max(math.cos(math.radians(latitude)), _MIN_LAT_FACTOR)
    return km / (KM_PER_DEG_LAT * factor)


def jitter_position(
    latitude: float, longitude: float, scan_km: float, track_km: float, rng,
) -> tuple[float, float]:
    """Scatter a point inside its pixel: the shared GENERATOR sampler.

    ``scan``/``track`` are km. Returns (lat, lon) whose displacement from the
    source is bounded by the pixel footprint (sigma = half-extent/sqrt(12)).
    """
    sig_lat = km_to_deg_lat(jitter_sigma_km(scan_km))
    sig_lon = km_to_deg_lon(jitter_sigma_km(track_km), latitude)
    return latitude + rng.normal(0.0, sig_lat), longitude + rng.normal(0.0, sig_lon)


def combined_tolerance_km(
    zone_radius_km: float, obs_scan_km: float, obs_track_km: float,
    margin_km: float,
) -> float:
    """Full gate allowance for 'is this observation explained by this zone'.

    zone extent (built from member scatter, which already contains their own
    pixel sampling) + the CURRENT observation's pixel half-diagonal + the
    configured margin. The new-zone gate fires only BEYOND this.
    """
    return (
        max(float(zone_radius_km), 0.0)
        + observation_radius_km(obs_scan_km, obs_track_km)
        + max(float(margin_km), 0.0)
    )


def _positive(value: float) -> float:
    """Coerce a possibly-missing/absurd pixel dimension to a sane positive km."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_PIXEL_KM
    if not math.isfinite(v) or v <= 0.0:
        return DEFAULT_PIXEL_KM
    return v
