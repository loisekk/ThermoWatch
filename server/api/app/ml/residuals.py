"""Residual computations: current observation vs facility normal state.

Pure functions. None/flagged results when state is missing or insufficient —
callers must never silently substitute zeros for unknowns.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.ml.normal_state import FacilityNormalState, _haversine_km

MAD_TO_SIGMA = 1.4826  # MAD -> equivalent sigma for normal distribution


@dataclass(frozen=True)
class IntensityResidual:
    z: float | None           # signed robust z on log1p(FRP); None = no state
    frp_ratio: float | None   # current FRP / state median FRP


@dataclass(frozen=True)
class SpatialResidual:
    nearest_zone_km: float | None  # None = no zones known
    is_new_zone: bool              # True only if zones known AND far from all
    zones_known: int


@dataclass(frozen=True)
class TemporalResidual:
    hour_surprise: float | None    # in [0,1]; 0 = most likely hour
    interval_z: float | None       # gap vs expected gap; None = first detection


def intensity_residual(frp: float, state: FacilityNormalState) -> IntensityResidual:
    if not state.sufficient or state.log_frp_median is None or state.log_frp_mad is None:
        return IntensityResidual(z=None, frp_ratio=None)
    log_frp = float(np.log1p(max(frp, 0.0)))
    z = (log_frp - state.log_frp_median) / (MAD_TO_SIGMA * state.log_frp_mad)
    median_frp = float(np.expm1(state.log_frp_median))
    ratio = frp / median_frp if median_frp > 0 else None
    return IntensityResidual(z=z, frp_ratio=ratio)


def spatial_residual(
    latitude: float, longitude: float, state: FacilityNormalState,
    new_zone_km: float = 1.5,
) -> SpatialResidual:
    if not state.sufficient or not state.zones:
        return SpatialResidual(nearest_zone_km=None, is_new_zone=False, zones_known=0)
    distances = [
        _haversine_km(latitude, longitude, z.centroid_lat, z.centroid_lon)
        for z in state.zones
    ]
    nearest = min(distances)
    # New zone = farther from EVERY known zone than the gate
    return SpatialResidual(
        nearest_zone_km=nearest,
        is_new_zone=nearest > new_zone_km,
        zones_known=len(state.zones),
    )


def temporal_residual(
    hour: int,
    days_since_previous: float | None,
    state: FacilityNormalState,
) -> TemporalResidual:
    """hour_surprise in [0,1]: 0 = most likely hour, 1 = never-seen hour.
    interval_z: robust z of the gap since the previous detection."""
    if not state.sufficient:
        return TemporalResidual(hour_surprise=None, interval_z=None)

    p = max(state.hour_probability(hour), 1e-6)
    # Normalize: uniform p=1/24 -> 0 surprise; p->0 -> 1
    surprise = 1.0 - (np.log(p) / np.log(1.0 / 24.0))  # log(p)/log(1/24) in (0,1]
    surprise = float(np.clip(surprise, 0.0, 1.0))

    if (
        days_since_previous is None
        or state.median_gap_days is None
        or state.gap_mad_days is None
    ):
        iz = None
    else:
        iz = (days_since_previous - state.median_gap_days) / (
            MAD_TO_SIGMA * state.gap_mad_days
        )

    return TemporalResidual(hour_surprise=surprise, interval_z=iz)
