"""Thermal topology deviation — RESEARCH BRANCH ONLY (experiment gate G4).

Represents a facility's recurrent thermal zones as a graph and measures
structural change between the baseline state and a current observation
window. Not imported by any production module until E06 proves value.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from app.ml.normal_state import FacilityNormalState, _haversine_km


@dataclass(frozen=True)
class TopologyChange:
    n_baseline_zones: int
    n_current_zones: int
    n_new_zones: int          # current zones with no baseline match
    n_lost_zones: int         # baseline zones with no current match
    max_centroid_shift_km: float  # max shift among matched zones
    zone_jaccard: float       # |matched| / |union| in [0,1]
    changed: bool


def window_zones(
    window_df: pd.DataFrame, eps_km: float = 1.0, min_samples: int = 2
) -> list[tuple[float, float]]:
    """DBSCAN centroids of a trailing observation window."""
    if len(window_df) < min_samples:
        return []
    coords = np.radians(window_df[["latitude", "longitude"]].to_numpy(dtype=float))
    labels = DBSCAN(
        eps=eps_km / 6371.0, min_samples=min_samples, metric="haversine"
    ).fit_predict(coords)
    zones: list[tuple[float, float]] = []
    for zid in sorted(set(labels.tolist()) - {-1}):
        m = window_df[labels == zid]
        zones.append((float(m["latitude"].mean()), float(m["longitude"].mean())))
    return zones


def topology_change(
    state: FacilityNormalState,
    current_zones: list[tuple[float, float]],
    match_km: float = 1.5,
) -> TopologyChange:
    """Compare current-window zones against the baseline state's zones.
    Matching = nearest baseline centroid within match_km."""
    baseline = [(z.centroid_lat, z.centroid_lon) for z in state.zones]
    if not state.sufficient or not baseline:
        return TopologyChange(
            len(baseline), len(current_zones), 0, 0, 0.0, 1.0, False
        )
    if not current_zones:
        # Empty window: no spatial evidence — a quiet period is not a
        # structural change (frozen E06 kill-test contract).
        return TopologyChange(len(baseline), 0, 0, 0, 0.0, 0.0, False)

    matched_baseline: set[int] = set()
    matched_current: set[int] = set()
    shifts: list[float] = []
    for i, (clat, clon) in enumerate(current_zones):
        dists = [_haversine_km(clat, clon, blat, blon) for (blat, blon) in baseline]
        j = int(np.argmin(np.asarray(dists, dtype=float)))
        if dists[j] <= match_km:
            matched_baseline.add(j)
            matched_current.add(i)
            shifts.append(dists[j])

    n_new = len(current_zones) - len(matched_current)
    n_lost = len(baseline) - len(matched_baseline)
    union = len(set(range(len(baseline))) | set(range(len(current_zones))))
    jaccard = len(matched_baseline) / union if union else 1.0

    return TopologyChange(
        n_baseline_zones=len(baseline),
        n_current_zones=len(current_zones),
        n_new_zones=n_new,
        n_lost_zones=n_lost,
        max_centroid_shift_km=round(max(shifts), 4) if shifts else 0.0,
        zone_jaccard=round(jaccard, 4),
        changed=(n_new > 0 or n_lost > 0),
    )
