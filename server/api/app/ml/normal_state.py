"""Facility normal thermal state — PURE computation, shared by production
(assessment pipeline, DB-backed) and research (E02-E06, fold-based).

Single source of truth: build_facility_normal_state(DataFrame) -> FacilityNormalState.
No DB, no I/O, fully deterministic — same input produces the same version hash.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

STATE_SCHEMA_VERSION = "fstate-v1.0.0"


@dataclass(frozen=True)
class SpatialZone:
    """A recurrent thermal zone at a facility (flare stack, kiln cluster, etc.)."""

    zone_id: int
    centroid_lat: float
    centroid_lon: float
    radius_km: float
    n_observations: int
    share: float  # fraction of facility history in this zone


@dataclass
class FacilityNormalState:
    """Learned normal thermal regime for one facility."""

    facility_id: str
    facility_type: str
    version: str
    n_observations: int
    n_days: int
    date_start: str
    date_end: str

    # Intensity (log1p(FRP) space)
    log_frp_median: float | None = None
    log_frp_mad: float | None = None
    frp_p10: float | None = None
    frp_p90: float | None = None

    # Temporal
    hour_histogram: np.ndarray = field(default_factory=lambda: np.full(24, 1.0 / 24))
    night_ratio: float | None = None
    detections_per_active_day: float | None = None
    median_gap_days: float | None = None
    gap_mad_days: float | None = None

    # Spatial
    zones: list[SpatialZone] = field(default_factory=list)
    noise_share: float = 0.0  # fraction of history not in any zone

    # Sufficiency
    sufficient: bool = False
    insufficient_reason: str | None = None

    def hour_probability(self, hour: int) -> float:
        """Laplace-smoothed probability of a detection at this hour."""
        return float(self.hour_histogram[hour % 24])


def build_facility_normal_state(
    observations: pd.DataFrame,
    facility_id: str,
    facility_type: str = "",
    *,
    min_obs: int = 10,
    min_days: int = 14,
    zone_eps_km: float = 1.0,
    zone_min_samples: int = 3,
) -> FacilityNormalState:
    """Build the normal state from a facility's historical observations.

    Args:
        observations: DataFrame with columns latitude, longitude, frp,
            observed_at (tz-aware). Expected to be TRAIN-fold / past-only data.
    """
    n = len(observations)
    span_days = 0
    if n > 0:
        span = observations["observed_at"].max() - observations["observed_at"].min()
        span_days = int(span.days)

    state = FacilityNormalState(
        facility_id=facility_id,
        facility_type=facility_type,
        version="",  # computed below
        n_observations=n,
        n_days=span_days,
        date_start=str(observations["observed_at"].min()) if n else "",
        date_end=str(observations["observed_at"].max()) if n else "",
    )

    if n < min_obs or span_days < min_days:
        state.sufficient = False
        state.insufficient_reason = (
            f"insufficient history: {n} obs over {span_days} days "
            f"(need >={min_obs} obs and >={min_days} days)"
        )
        state.version = _version_hash(state, {})
        return state

    state.sufficient = True
    _fill_intensity(state, observations)
    _fill_temporal(state, observations)
    _fill_spatial(state, observations, zone_eps_km, zone_min_samples)

    state.version = _version_hash(state, {
        "min_obs": min_obs, "min_days": min_days,
        "zone_eps_km": zone_eps_km, "zone_min_samples": zone_min_samples,
    })
    return state


def _fill_temporal(state: FacilityNormalState, observations: pd.DataFrame) -> None:
    """Hour histogram (Laplace-smoothed), night ratio, detection cadence."""
    n = len(observations)
    hours = observations["observed_at"].dt.hour.to_numpy()
    counts = np.bincount(hours.astype(int), minlength=24).astype(float)
    state.hour_histogram = (counts + 1.0) / (counts.sum() + 24.0)  # Laplace
    state.night_ratio = float(((hours < 6) | (hours >= 18)).mean())

    dates = observations["observed_at"].dt.date
    active_days = int(dates.nunique())
    state.detections_per_active_day = n / max(active_days, 1)

    # Distinct active days as ordinal ints (object-dtype-safe under pandas 3)
    day_ordinals = np.array(sorted({d.toordinal() for d in dates}), dtype=float)
    if len(day_ordinals) > 1:
        gaps = np.diff(day_ordinals)
        state.median_gap_days = float(np.median(gaps))
        state.gap_mad_days = max(
            float(np.median(np.abs(gaps - np.median(gaps)))), 1e-6
        )
    else:
        state.median_gap_days, state.gap_mad_days = 1.0, 1.0


def _fill_spatial(
    state: FacilityNormalState,
    observations: pd.DataFrame,
    zone_eps_km: float,
    zone_min_samples: int,
) -> None:
    """DBSCAN (haversine, radians) recurrent thermal zones."""
    coords_rad = np.radians(
        observations[["latitude", "longitude"]].to_numpy(dtype=float)
    )
    labels = DBSCAN(
        eps=zone_eps_km / 6371.0, min_samples=zone_min_samples, metric="haversine"
    ).fit_predict(coords_rad)

    zones: list[SpatialZone] = []
    for zid in sorted(set(labels.tolist()) - {-1}):
        mask = labels == zid
        zone_obs = observations[mask]
        zlat = float(zone_obs["latitude"].mean())
        zlon = float(zone_obs["longitude"].mean())
        radii = np.asarray(
            [
                _haversine_km(zlat, zlon, float(r.latitude), float(r.longitude))
                for r in zone_obs.itertuples()
            ],
            dtype=float,
        )
        zones.append(SpatialZone(
            zone_id=int(zid),
            centroid_lat=zlat,
            centroid_lon=zlon,
            radius_km=float(np.quantile(radii, 0.95)),
            n_observations=int(mask.sum()),
            share=float(mask.mean()),
        ))
    zones.sort(key=lambda z: -z.n_observations)
    state.zones = zones
    state.noise_share = float((labels == -1).mean())


def build_states_for_fold(
    df: pd.DataFrame,
    *,
    min_obs: int = 10,
    min_days: int = 14,
    zone_eps_km: float = 1.0,
    zone_min_samples: int = 3,
) -> dict[str, FacilityNormalState]:
    """Build normal states for every facility in a (train) fold.
    Observations with no facility_id are skipped."""
    states: dict[str, FacilityNormalState] = {}
    fac_obs = df[df["facility_id"] != ""]
    for fid, group in fac_obs.groupby("facility_id"):
        ftype = (
            str(group["facility_type"].iloc[0])
            if "facility_type" in group.columns
            else ""
        )
        states[str(fid)] = build_facility_normal_state(
            group, str(fid), ftype,
            min_obs=min_obs, min_days=min_days,
            zone_eps_km=zone_eps_km, zone_min_samples=zone_min_samples,
        )
    return states


def _version_hash(state: FacilityNormalState, params: dict) -> str:
    """Deterministic version: same data + params -> same hash."""
    payload = {
        "schema": STATE_SCHEMA_VERSION,
        "params": params,
        "n": state.n_observations,
        "days": state.n_days,
        "median": round(state.log_frp_median, 4) if state.log_frp_median is not None else None,
        "mad": round(state.log_frp_mad, 4) if state.log_frp_mad is not None else None,
        "n_zones": len(state.zones),
        "date_end": state.date_end,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


def _fill_intensity(state: FacilityNormalState, observations: pd.DataFrame) -> None:
    """Robust intensity stats on log1p(FRP)."""
    log_frp = np.log1p(observations["frp"].clip(lower=0).to_numpy(dtype=float))
    state.log_frp_median = float(np.median(log_frp))
    state.log_frp_mad = float(np.median(np.abs(log_frp - state.log_frp_median)))
    state.log_frp_mad = max(state.log_frp_mad, 1e-6)
    state.frp_p10 = float(np.exp(np.quantile(log_frp, 0.10)))
    state.frp_p90 = float(np.exp(np.quantile(log_frp, 0.90)))
