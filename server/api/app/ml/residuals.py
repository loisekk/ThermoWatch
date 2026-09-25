"""Residual computations: current observation vs facility normal state.

Pure functions. None/flagged results when state is missing or insufficient —
callers must never silently substitute zeros for unknowns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.ml.normal_state import FacilityNormalState, _haversine_km
from app.ml.observation_uncertainty import combined_tolerance_km

MAD_TO_SIGMA = 1.4826  # MAD -> equivalent sigma for normal distribution

# Observation pixel size used when a caller has no scan/track for the row
# (VIIRS I-band nominal nadir footprint, km). Callers that DO have the pixel
# dimensions must pass them — the gate's tolerance depends on them (plan 4.1).
DEFAULT_OBS_PIXEL_KM = 0.4

# Sustained-shift arm: robust z of the windowed mean vs the baseline, with the
# standard error shrinking as 1/sqrt(K). 3.0 mirrors the production intensity
# gate; the window is short so a slow trajectory accumulates evidence fast.
SUSTAINED_Z = 3.0
SUSTAINED_WINDOW = 8


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


@dataclass(frozen=True)
class SustainedResidual:
    z: float | None        # windowed mean vs baseline, sample-size corrected
    n_window: int


def intensity_residual(
    frp: float, state: FacilityNormalState, hour: int | None = None,
    is_night: bool | None = None,
) -> IntensityResidual:
    if not state.sufficient or state.log_frp_median is None or state.log_frp_mad is None:
        return IntensityResidual(z=None, frp_ratio=None)
    median = state.log_frp_median
    mad = state.log_frp_mad
    # Day/night bimodality guard: profiles boost night FRP (log space), so a
    # single median/MAD understates dispersion. Prefer the matching split
    # stats when the state has enough observations in that half.
    if is_night is None and hour is not None:
        h = hour % 24
        is_night = h < 6 or h >= 18
    if is_night is not None:
        suffix = "_night" if is_night else "_day"
        split_median = getattr(state, f"log_frp_median{suffix}", None)
        split_mad = getattr(state, f"log_frp_mad{suffix}", None)
        if split_median is not None and split_mad is not None:
            median, mad = split_median, split_mad
    log_frp = float(np.log1p(max(frp, 0.0)))
    z = (log_frp - median) / (MAD_TO_SIGMA * mad)
    median_frp = float(np.expm1(median))
    ratio = frp / median_frp if median_frp > 0 else None
    return IntensityResidual(z=z, frp_ratio=ratio)


def spatial_residual(
    latitude: float, longitude: float, state: FacilityNormalState,
    new_zone_km: float = 1.5,
    obs_scan_km: float = DEFAULT_OBS_PIXEL_KM,
    obs_track_km: float = DEFAULT_OBS_PIXEL_KM,
) -> SpatialResidual:
    """Zone-relative new-zone gate (plan 4.1 mechanism fix).

    An observation is EXPLAINED by a zone when it lies within the zone's
    measured extent PLUS the observation's own pixel half-diagonal PLUS the
    configured margin. ``is_new_zone`` fires only BEYOND that combined
    tolerance.

    Pre-fix, this compared the raw centroid distance against a flat
    ``new_zone_km``; because the generator scattered detections multi-km
    (scan km mis-read as degrees) the gate fired on ~81% of normal rows.
    The tolerance now absorbs the pixel physics that generator and detector
    share via ``app.ml.observation_uncertainty``.
    """
    if not state.sufficient or not state.zones:
        return SpatialResidual(nearest_zone_km=None, is_new_zone=False, zones_known=0)

    # Nearest zone BY BEYOND-TOLERANCE DISTANCE, not raw centroid distance:
    # a detection 3 km from a centroid but inside a 4 km zone is IN that zone.
    best: tuple[float, float] | None = None
    for z in state.zones:
        d = _haversine_km(latitude, longitude, z.centroid_lat, z.centroid_lon)
        beyond = d - combined_tolerance_km(
            z.radius_km, obs_scan_km, obs_track_km, new_zone_km
        )
        if best is None or beyond < best[0]:
            best = (beyond, d)

    if best is None:
        return SpatialResidual(nearest_zone_km=None, is_new_zone=False, zones_known=0)

    beyond_km, nearest = best
    return SpatialResidual(
        nearest_zone_km=nearest,
        is_new_zone=beyond_km > 0.0,
        zones_known=len(state.zones),
    )


def sustained_shift_residual(
    window_log_frps: list[float], state: FacilityNormalState,
    is_night: bool | None = None,
    min_window: int = 5,
) -> SustainedResidual:
    """Detect a SLOW SUSTAINED deviation (H5) from the existing state stats.

    Mechanism: a single drifted observation is indistinguishable from noise
    (correct behaviour — the intensity arm catches spikes). But the MEAN of
    the last K observations shifts systematically under a sustained
    trajectory, and its standard error shrinks as 1/sqrt(K) — so a modest
    per-observation drift becomes a large z over the window. Sequential
    change detection on the existing median/MAD machinery; no new model
    family (plan 4.2).

    ``window_log_frps`` must be the facility's last K observations ENDING AT
    the row under test (causal: never future values). z is None whenever the
    state or window is insufficient — callers must not read that as "normal".
    """
    n_window = len(window_log_frps)
    if not state.sufficient or n_window < min_window:
        return SustainedResidual(z=None, n_window=n_window)

    suffix = "" if is_night is None else ("_night" if is_night else "_day")
    median = getattr(state, f"log_frp_median{suffix}", None)
    mad = getattr(state, f"log_frp_mad{suffix}", None)
    if median is None:
        median = state.log_frp_median
    if mad is None:
        mad = state.log_frp_mad
    if median is None or mad is None:
        return SustainedResidual(z=None, n_window=n_window)

    w = np.asarray(window_log_frps, dtype=float)
    se = (MAD_TO_SIGMA * mad) / math.sqrt(len(w))
    z = (float(w.mean()) - median) / max(se, 1e-6)
    return SustainedResidual(z=round(z, 3), n_window=n_window)


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
