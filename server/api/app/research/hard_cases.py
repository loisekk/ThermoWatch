"""Hard-case scenario generators H1-H12.

Each generator produces a synthetic overlay that can be appended to
the research dataset for stress-testing. Scenarios are tagged with
their hard_case_id for per-scenario evaluation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.research.dataset import FACILITY_PROFILES, FACILITY_REGISTRY, _make_observation


def generate_hard_case_dataset(seed: int = 123, n_days: int = 60) -> pd.DataFrame:
    """Generate all hard-case scenarios as a single dataset.

    Each row is tagged with hard_case_id for per-scenario metrics.
    """
    rng = np.random.default_rng(seed)
    rows = []
    date_range = pd.date_range("2026-07-01", periods=n_days, freq="D", tz="UTC")
    counter = 0

    for fac in FACILITY_REGISTRY:
        prof = FACILITY_PROFILES[fac.facility_type]
        for day in date_range:
            if rng.random() > prof["persist"]:
                continue
            n = int(rng.integers(prof["n_daily"][0], prof["n_daily"][1] + 1))
            for _ in range(n):
                counter += 1
                hour = int(rng.integers(6, 18)) if prof["diurnal_day_only"] else int(rng.integers(0, 24))
                mu = prof["frp_mu"] + (prof["night_boost"] if hour < 6 or hour >= 18 else 0)
                frp = max(float(np.exp(rng.normal(mu, prof["frp_sigma"]))), 0.1)
                rows.append(_make_observation(
                    rng, counter, fac.facility_id, fac.facility_type,
                    fac.latitude, fac.longitude, day, hour, frp,
                    landcover="industrial", is_natural=False, event_id="",
                ))

    df = pd.DataFrame(rows)

    # Apply hard-case modifications
    df = _apply_h1_normal_persistent(df, rng)
    df = _apply_h2_intensity_spike(df, rng)
    df = _apply_h3_new_zone(df, rng)
    df = _apply_h4_displacement(df, rng)
    df = _apply_h5_duration_anomaly(df, rng)
    # H6-H7 require natural/agri fire proximity — evaluated as data conditions
    df = _apply_h8_overlapping(df, rng)
    # H9-H11 are data-condition scenarios (applied at evaluation, not generation)
    # H12 is a regime shift

    return df


def _apply_h1_normal_persistent(df, rng):
    """H1: Long-running flare/process heat — should remain NORMAL."""
    df["hard_case_id"] = ""
    persistent = df["facility_type"].isin(["gas_flare", "refinery"])
    df.loc[persistent, "hard_case_id"] = "H1_normal_persistent"
    return df


def _apply_h2_intensity_spike(df, rng):
    """H2: Existing source becomes unusually intense — should be ABNORMAL."""
    facility_ids = [f for f in df["facility_id"].unique() if f]
    for fid in facility_ids[:5]:  # first 5 facilities get spikes
        idx = df.index[df["facility_id"] == fid].to_numpy()
        if len(idx) < 10:
            continue
        spike_start = int(rng.integers(len(idx) // 2, len(idx) - 3))
        spike_indices = idx[spike_start:spike_start + 3]
        mult = float(rng.uniform(4.0, 8.0))
        df.loc[spike_indices, "frp"] = (df.loc[spike_indices, "frp"] * mult).round(2)
        df.loc[spike_indices, "brightness_ti4"] = (
            df.loc[spike_indices, "brightness_ti4"] + 22 * np.log(mult)).round(2)
        df.loc[spike_indices, "label_normality"] = "abnormal"
        df.loc[spike_indices, "hard_case_id"] = "H2_intensity_spike"
    return df


def _apply_h3_new_zone(df, rng):
    """H3: New hotspot outside recurrent zones — should be ABNORMAL."""
    facility_ids = [f for f in df["facility_id"].unique() if f]
    for fac_id in facility_ids[5:10]:
        fac_rows = df[df["facility_id"] == fac_id]
        if fac_rows.empty:
            continue
        base_lat = fac_rows["latitude"].mode().iloc[0]
        base_lon = fac_rows["longitude"].mode().iloc[0]
        # Place new detections 3-5 km away mid-series
        day = fac_rows["observed_at"].iloc[len(fac_rows) // 2]
        ftype = fac_rows["facility_type"].iloc[0]
        profile = FACILITY_PROFILES.get(ftype, FACILITY_PROFILES["chemical"])
        for i in range(4):
            new_lat = base_lat + rng.uniform(0.03, 0.05)
            new_lon = base_lon + rng.uniform(0.03, 0.05)
            frp = float(np.exp(rng.normal(profile["frp_mu"] + 1.0, profile["frp_sigma"])))
            new_row = _make_observation(
                rng, len(df) + i, fac_id, ftype,
                new_lat, new_lon, day, 14, frp,
                landcover="industrial", is_natural=False, event_id="",
            )
            new_row["label_normality"] = "abnormal"
            new_row["hard_case_id"] = "H3_new_zone"
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return df


def _apply_h4_displacement(df, rng):
    """H4: Thermal activity shifts away from learned zone — should be ABNORMAL."""
    facility_ids = [f for f in df["facility_id"].unique() if f]
    for fid in facility_ids[10:14]:
        mask = (df["facility_id"] == fid) & (df["label_normality"] == "normal")
        idx = df.index[mask].to_numpy()
        if len(idx) < 10:
            continue
        shift_start = int(rng.integers(len(idx) // 2, len(idx) - 5))
        displaced = idx[shift_start:shift_start + 5]
        shift = float(rng.uniform(0.02, 0.04))
        df.loc[displaced, "latitude"] = (df.loc[displaced, "latitude"] + shift).round(6)
        df.loc[displaced, "longitude"] = (df.loc[displaced, "longitude"] + shift).round(6)
        df.loc[displaced, "label_normality"] = "abnormal"
        df.loc[displaced, "hard_case_id"] = "H4_displacement"
    return df


def _apply_h5_duration_anomaly(df, rng):
    """H5: Unexpected sustained trajectory — should be ABNORMAL."""
    facility_ids = [f for f in df["facility_id"].unique() if f]
    for fid in facility_ids[14:16]:
        mask = (df["facility_id"] == fid) & (df["label_normality"] == "normal")
        idx = df.index[mask].to_numpy()
        if len(idx) < 20:
            continue
        # Sustained elevated FRP for 10 consecutive observations
        start = int(rng.integers(0, max(1, len(idx) - 10)))
        sustained = idx[start:start + 10]
        mult = float(rng.uniform(2.0, 3.5))
        df.loc[sustained, "frp"] = (df.loc[sustained, "frp"] * mult).round(2)
        df.loc[sustained, "label_normality"] = "abnormal"
        df.loc[sustained, "hard_case_id"] = "H5_duration_anomaly"
    return df


def _apply_h8_overlapping(df, rng):
    """H8: Multiple sources overlapping spatially — tests association."""
    fac1 = FACILITY_REGISTRY[0]  # Jamnagar refinery
    fac2 = FACILITY_REGISTRY[1]  # Reliance SEZ refinery (~25 km away)
    if abs(fac1.latitude - fac2.latitude) < 0.5:
        # Overlapping — tag a sample as H8
        mask = df["facility_id"].isin([fac1.facility_id, fac2.facility_id])
        sample_idx = df.index[mask][:10]
        df.loc[sample_idx, "hard_case_id"] = "H8_overlapping"
    return df


HARD_CASE_DESCRIPTIONS = {
    "H1_normal_persistent": "Long-running flare/process heat — should remain NORMAL",
    "H2_intensity_spike": "Existing source becomes unusually intense — tests intensity residual",
    "H3_new_zone": "New hotspot outside recurrent zones — tests spatial novelty",
    "H4_displacement": "Thermal activity shifts from learned zone — tests spatial/topology deviation",
    "H5_duration_anomaly": "Unexpected sustained trajectory — tests temporal novelty",
    "H6_natural_near_facility": "Wildfire within facility influence area — tests context discrimination",
    "H7_agri_near_facility": "Agricultural burn near industrial asset — tests land-cover robustness",
    "H8_overlapping": "Multiple sources overlap spatially — tests association",
    "H9_sparse": "Gaps from orbit/cloud — tests uncertainty and abstention",
    "H10_missing_corroboration": "No optical/environmental confirmation — tests degradation",
    "H11_cold_start": "No historical thermal history — tests cold-start handling",
    "H12_regime_shift": "Facility behavior changes for legitimate reasons — tests adaptation",
}

