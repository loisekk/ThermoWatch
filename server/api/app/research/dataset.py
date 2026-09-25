"""Research dataset: schema, synthetic generator, real-data loader, labeling.

The ResearchDataset is a pandas DataFrame with a fixed schema. Labels carry
provenance — we never pretend proxy labels are ground truth.

Schema (one row = one satellite observation):
    observation_id       str     unique
    facility_id          str     facility attribution ("" if none)
    facility_type        str     subtype of the facility ("" if none)
    latitude / longitude float
    observed_at          datetime (UTC)
    sensor               str     "modis" | "viirs"
    platform             str     "terra"|"aqua"|"snpp"|"noaa20"
    frp                  float   Fire Radiative Power (MW)
    brightness_ti4/ti5   float   fire/background channel brightness (K)
    scan / track         float   pixel dimensions (km) — FIRMS convention
    confidence           str     "low"|"nominal"|"high"
    day_night           str     "day"|"night"
    landcover            str     "forest"|"agriculture"|"urban"|"industrial"|...
    is_natural_fire      bool    belongs to a natural/agri fire event
    event_id             str     groups observations into fire events
    label_source_class   str     10-way target
    label_normality      str     "normal"|"abnormal" (anomaly task; may be "")
    label_provenance     str     how the label was derived
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.ml.observation_uncertainty import jitter_position, km_to_deg_lat
from app.research.config import SYNTHETIC_SEED


# =====================================================================
# Facility registry (18 facilities across India)
# =====================================================================
@dataclass(frozen=True)
class Facility:
    facility_id: str
    name: str
    facility_type: str
    latitude: float
    longitude: float
    landcover: str = "industrial"


FACILITY_REGISTRY: list[Facility] = [
    Facility("F-001", "Jamnagar Refinery", "refinery", 22.47, 70.07),
    Facility("F-002", "Reliance SEZ Refinery", "refinery", 22.30, 69.85),
    Facility("F-003", "Koyali Refinery", "refinery", 22.28, 73.17),
    Facility("F-004", "Bokaro Steel Plant", "steel", 23.67, 86.15),
    Facility("F-005", "Tata Steel Jamshedpur", "steel", 22.80, 86.20),
    Facility("F-006", "Bhilai Steel Plant", "steel", 21.19, 81.35),
    Facility("F-007", "Mumbai High Flare", "gas_flare", 19.03, 71.55),
    Facility("F-008", "KG Basin Flare", "gas_flare", 16.50, 82.30),
    Facility("F-009", "Wadi Cement Works", "cement", 17.05, 76.98),
    Facility("F-010", "Jamul Cement Plant", "cement", 21.25, 81.35),
    Facility("F-011", "Korba Aluminium Smelter", "smelter", 22.35, 82.68),
    Facility("F-012", "Hirakud Smelter", "smelter", 21.55, 83.87),
    Facility("F-013", "Delhi WtE Plant", "waste_incineration", 28.62, 77.10),
    Facility("F-014", "Mumbai WtE Facility", "waste_incineration", 19.05, 72.88),
    Facility("F-015", "Bathinda Thermal", "power_plant", 30.21, 74.95),
    Facility("F-016", "Singrauli Super Thermal", "power_plant", 24.18, 82.68),
    Facility("F-017", "Haldia Petrochemical", "chemical", 22.06, 88.11),
    Facility("F-018", "Vapi Chemical Belt", "chemical", 20.37, 72.90),
]

# =====================================================================
# Thermal signature profiles (log-FRP space)
# =====================================================================
FACILITY_PROFILES: dict[str, dict[str, Any]] = {
    "refinery":           {"frp_mu": 3.4, "frp_sigma": 0.45, "night_boost": 0.25, "diurnal_day_only": False, "persist": 0.93, "n_daily": (1, 4), "frp_trend": 1.00},
    "steel":              {"frp_mu": 4.2, "frp_sigma": 0.55, "night_boost": 0.10, "diurnal_day_only": False, "persist": 0.93, "n_daily": (1, 3), "frp_trend": 1.00},
    "gas_flare":          {"frp_mu": 3.9, "frp_sigma": 0.28, "night_boost": 0.45, "diurnal_day_only": False, "persist": 0.98, "n_daily": (2, 5), "frp_trend": 0.99},
    "cement":             {"frp_mu": 2.7, "frp_sigma": 0.50, "night_boost": -1.0, "diurnal_day_only": True,  "persist": 0.88, "n_daily": (1, 3), "frp_trend": 1.00},
    "smelter":            {"frp_mu": 4.5, "frp_sigma": 0.60, "night_boost": 0.00, "diurnal_day_only": False, "persist": 0.93, "n_daily": (1, 4), "frp_trend": 1.01},
    "waste_incineration": {"frp_mu": 2.2, "frp_sigma": 0.40, "night_boost": -0.5, "diurnal_day_only": True,  "persist": 0.85, "n_daily": (1, 2), "frp_trend": 1.00},
    "power_plant":        {"frp_mu": 1.7, "frp_sigma": 0.55, "night_boost": 0.00, "diurnal_day_only": False, "persist": 0.88, "n_daily": (0, 2), "frp_trend": 1.00},
    "chemical":           {"frp_mu": 3.1, "frp_sigma": 0.70, "night_boost": 0.10, "diurnal_day_only": False, "persist": 0.82, "n_daily": (0, 3), "frp_trend": 1.00},
}

NATURAL_FIRE_PROFILE = {"frp_mu": 4.4, "frp_sigma": 0.85, "duration_days": (1, 6), "n_daily": (2, 8), "seasonal_months": [1, 2, 3, 4, 5, 11, 12]}
AGRI_BURN_PROFILE = {"frp_mu": 2.9, "frp_sigma": 0.65, "duration_days": (1, 3), "n_daily": (1, 5), "seasonal_months": [10, 11, 12]}

# Geographic regions for natural/agri fires (lat, lon, radius_deg, landcover)
FIRE_REGIONS = {
    "forest": [(20.0, 78.5, 4.0, "forest"), (13.0, 75.5, 3.0, "forest"), (30.0, 80.0, 3.5, "forest")],
    "agriculture": [(26.0, 75.0, 5.0, "agriculture"), (21.0, 78.0, 4.5, "agriculture"), (16.0, 77.5, 3.5, "agriculture")],
}


# =====================================================================
# Synthetic generator
# =====================================================================
def generate_synthetic_dataset(
    n_days: int = 120,
    n_natural_fires: int = 35,
    n_agri_burns: int = 50,
    start_date: str = "2026-05-01",
    seed: int = SYNTHETIC_SEED,
    inject_anomalies: bool = True,
    anomaly_fraction: float = 0.03,
) -> pd.DataFrame:
    """Generate a realistic synthetic FIRMS-like dataset.

    Physics model:
      - FRP ~ log-normal per facility type (overlapping ranges create confusion)
      - brightness_ti4 = 295 + 22*ln(FRP) + noise
      - brightness_ti5 = 292 + 4*ln(FRP) + noise  (so delta_t ~ 18*ln(FRP))
      - confidence correlates with FRP and sensor resolution
      - scan/track vary by sensor (MODIS coarser than VIIRS)

    Labels:
      - label_source_class: ground truth from the generative process
      - label_normality: "normal" unless an anomaly was injected
      - label_provenance: "synthetic_truth"
    """
    rng = np.random.default_rng(seed)
    rows = []
    date_range = pd.date_range(start_date, periods=n_days, freq="D", tz="UTC")
    obs_counter = 0

    # --- Facility observations ---
    for fac in FACILITY_REGISTRY:
        prof = FACILITY_PROFILES[fac.facility_type]
        for day_idx, day in enumerate(date_range):
            if rng.random() > prof["persist"]:
                continue  # not detected today
            trend = prof["frp_trend"] ** (day_idx / 30.0)
            n_dets = rng.integers(prof["n_daily"][0], prof["n_daily"][1] + 1)
            for _ in range(n_dets):
                hour = int(rng.integers(6, 18)) if prof["diurnal_day_only"] else int(rng.integers(0, 24))
                is_night = hour < 6 or hour >= 18
                mu = prof["frp_mu"] + (prof["night_boost"] if is_night else 0.0) + np.log(trend)
                frp = max(float(np.exp(rng.normal(mu, prof["frp_sigma"]))), 0.1)
                obs_counter += 1
                rows.append(_make_observation(
                    rng, obs_counter, fac.facility_id, fac.facility_type,
                    fac.latitude, fac.longitude, day, hour, frp,
                    landcover="industrial", is_natural=False, event_id="",
                ))

    # --- Natural fires ---
    for i in range(n_natural_fires):
        region = FIRE_REGIONS["forest"][int(rng.integers(0, len(FIRE_REGIONS["forest"])))]
        rows += _generate_fire_event(
            rng, len(rows), f"NF-{i:04d}", region, date_range,
            NATURAL_FIRE_PROFILE, label="natural_fire", landcover="forest",
        )

    # --- Agricultural burns ---
    for i in range(n_agri_burns):
        region = FIRE_REGIONS["agriculture"][int(rng.integers(0, len(FIRE_REGIONS["agriculture"])))]
        rows += _generate_fire_event(
            rng, len(rows), f"AG-{i:04d}", region, date_range,
            AGRI_BURN_PROFILE, label="natural_fire", landcover="agriculture",
        )

    df = pd.DataFrame(rows)

    # --- Inject anomalies (for the normality task) ---
    if inject_anomalies and len(df) > 0:
        df = _inject_anomalies(df, rng, anomaly_fraction)

    df = df.sort_values("observed_at").reset_index(drop=True)
    return df


def _make_observation(
    rng, obs_id, facility_id, facility_type, lat, lon, day, hour, frp,
    landcover, is_natural, event_id, label_override=None, normality="normal",
) -> dict:
    """Create a single observation row with realistic sensor physics."""
    ln_frp = np.log(max(frp, 0.1))
    brightness_ti4 = 295.0 + 22.0 * ln_frp + rng.normal(0, 6.0)
    brightness_ti5 = 292.0 + 4.0 * ln_frp + rng.normal(0, 4.0)
    delta_t = brightness_ti4 - brightness_ti5

    # Sensor assignment: VIIRS more common
    if rng.random() < 0.65:
        sensor = "viirs"
        platform = "snpp" if rng.random() < 0.6 else "noaa20"
        scan = float(rng.uniform(0.30, 0.80))
        track = float(rng.uniform(0.30, 0.70))
    else:
        sensor = "modis"
        platform = "terra" if rng.random() < 0.5 else "aqua"
        scan = float(rng.uniform(0.90, 2.40))
        track = float(rng.uniform(0.90, 2.10))

    # Confidence: higher FRP and delta_t -> higher confidence
    conf_score = 0.35 * min(ln_frp / 5.0, 1.0) + 0.45 * min(delta_t / 30.0, 1.0) + rng.normal(0, 0.12)
    confidence = "high" if conf_score > 0.55 else ("nominal" if conf_score > 0.30 else "low")

    # Coordinate jitter INSIDE the pixel footprint, via the SHARED model
    # (plan 4.1). scan/track are km: the pre-fix code divided the km value by
    # 4 and added it as DEGREES, scattering a fixed source across 4-22 km —
    # the generator half of the false-alert mechanism. sigma is now
    # half-extent/sqrt(12), bounded by the footprint.
    lat_j, lon_j = jitter_position(lat, lon, scan, track, rng)

    is_night = hour < 6 or hour >= 18
    observed_at = day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)))
    label = label_override or facility_type

    return {
        "observation_id": f"OBS-{obs_id:07d}",
        "facility_id": facility_id,
        "facility_type": facility_type if facility_id else "",
        "latitude": round(float(lat_j), 6),
        "longitude": round(float(lon_j), 6),
        "observed_at": observed_at,
        "sensor": sensor,
        "platform": platform,
        "frp": round(float(frp), 2),
        "brightness_ti4": round(float(brightness_ti4), 2),
        "brightness_ti5": round(float(brightness_ti5), 2),
        "scan": round(float(scan), 3),
        "track": round(float(track), 3),
        "confidence": confidence,
        "day_night": "night" if is_night else "day",
        "landcover": landcover,
        "is_natural_fire": is_natural,
        "event_id": event_id,
        "label_source_class": label,
        "label_normality": normality,
        "anomaly_type": "",
        "label_provenance": "synthetic_truth",
    }


def _generate_fire_event(rng, start_counter, event_id, region, date_range, profile, label, landcover):
    """Generate a transient fire event (natural or agricultural)."""
    clat, clon, radius, lc = region
    # Seasonal filter
    valid_days = [d for d in date_range if d.month in profile["seasonal_months"]]
    if not valid_days:
        return []
    start_day = valid_days[int(rng.integers(0, len(valid_days)))]
    duration = int(rng.integers(*profile["duration_days"]))
    rows = []
    counter = start_counter
    elat = clat + rng.normal(0, radius * 0.25)
    elon = clon + rng.normal(0, radius * 0.25)
    for d in range(duration):
        day = start_day + pd.Timedelta(days=d)
        if day > date_range[-1]:
            break
        # FRP peaks mid-event, decays at edges
        intensity_factor = float(np.sin(np.pi * (d + 1) / (duration + 1))) if duration > 1 else 1.0
        n_dets = int(rng.integers(*profile["n_daily"]))
        for _ in range(n_dets):
            counter += 1
            frp = float(np.exp(rng.normal(profile["frp_mu"], profile["frp_sigma"]))) * intensity_factor
            frp = max(frp, 0.5)
            hour = int(rng.integers(10, 17))  # fires detected mostly during day
            # Spread within event area
            spread = 0.05 * (d + 1)
            rlat = elat + rng.normal(0, spread)
            rlon = elon + rng.normal(0, spread)
            rows.append(_make_observation(
                rng, counter, "", "", rlat, rlon, day, hour, frp,
                landcover=lc, is_natural=True, event_id=event_id,
                label_override=label, normality="normal",
            ))
    return rows


def _inject_anomalies(df: pd.DataFrame, rng, fraction: float) -> pd.DataFrame:
    """Inject hard-case anomalies into facility observations.

    Anomaly types (matching H2/H4):
      - intensity_spike: FRP multiplied by 3-8x
      - displaced_source: coordinates shifted 1.5-4 km (physically detectable)
    Marked as label_normality="abnormal".
    """
    df = df.copy()
    df["anomaly_type"] = ""
    facility_obs = df[df["facility_id"] != ""].index
    n_anomalies = int(len(facility_obs) * fraction)
    if n_anomalies == 0:
        return df

    # Pick affected facility-days (one anomaly per facility-day),
    # stratified UNIFORMLY ACROSS THE DATE RANGE: sampling rows uniformly
    # front-loads anomalies whenever detection density drifts over time, and
    # a future window that lands after all injected spikes has no positives
    # to score. Equal-count date strata guarantee both windows carry spikes.
    observed_dates = pd.to_datetime(
        df["observed_at"], errors="coerce"
    ).dt.date
    candidates = df.loc[facility_obs, ["facility_id"]].copy()
    candidates["date"] = observed_dates.loc[facility_obs]
    unique_fd = candidates.drop_duplicates().index.to_numpy()
    n_anom = min(n_anomalies, len(unique_fd))
    if n_anom == 0:
        return df

    # Order unique facility-days by date and split into equal-count strata.
    fd_dates = candidates.loc[unique_fd, "date"].to_numpy()
    sorted_fd = unique_fd[np.argsort(fd_dates, kind="stable")]
    n_strata = max(1, min(10, len(sorted_fd)))
    strata = [list(s) for s in np.array_split(sorted_fd, n_strata) if len(s)]

    # Even allocation across strata (+1 each to the first remainders), with
    # shortfall carried forward and any residual filled from leftovers.
    base, rem = divmod(n_anom, len(strata))
    targets = [base + (1 if i < rem else 0) for i in range(len(strata))]
    selected: list = []
    carry = 0
    for i, lst in enumerate(strata):
        want = targets[i] + carry
        take = min(want, len(lst))
        carry = want - take
        if take:
            picked = rng.choice(np.asarray(lst), size=take, replace=False)
            selected.extend(picked.tolist())
            strata[i] = [x for x in lst if x not in set(picked.tolist())]
    if carry:
        leftover = [i for lst in strata for i in lst]
        selected.extend(leftover[:carry])

    anomalous_indices = set()
    for idx in selected:
        fid = df.loc[idx, "facility_id"]
        dt = observed_dates.loc[idx]
        mask = (df["facility_id"] == fid) & (observed_dates == dt)
        anomalous_indices.update(df.index[mask].tolist())

    anom_type = rng.choice(
        ["intensity_spike", "intensity_spike", "displaced_source"],
        size=len(anomalous_indices),
    )

    for (idx, atype) in zip(sorted(anomalous_indices), anom_type):
        if atype == "intensity_spike":
            mult = float(rng.uniform(3.0, 8.0))
            frp_value = pd.to_numeric(df.at[idx, "frp"], errors="coerce")
            if pd.notna(frp_value):
                df.at[idx, "frp"] = round(float(frp_value) * mult, 2)
            df.loc[idx, "brightness_ti4"] = round(
                df.loc[idx, "brightness_ti4"] + 22.0 * np.log(mult), 2)
        elif atype == "displaced_source":
            # Physically DETECTABLE displacement (plan 4.1/4.6): a sub-pixel
            # shift is unresolvable by construction, so the old 0.5-2 km
            # range tested physics the mission cannot deliver. 1.5-4 km is a
            # genuinely different unit within a large facility.
            shift = km_to_deg_lat(float(rng.uniform(1.5, 4.0)))
            latitude_value = pd.to_numeric(df.at[idx, "latitude"], errors="coerce")
            longitude_value = pd.to_numeric(df.at[idx, "longitude"], errors="coerce")
            latitude = float(latitude_value) if pd.notna(latitude_value) else 0.0
            longitude = float(longitude_value) if pd.notna(longitude_value) else 0.0
            df.at[idx, "latitude"] = round(latitude + shift, 6)
            df.at[idx, "longitude"] = round(longitude + shift, 6)
        df.loc[idx, "label_normality"] = "abnormal"
        df.loc[idx, "anomaly_type"] = str(atype)

    return df


# =====================================================================
# Real data loader (FIRMS archive CSV + OSM-derived labels)
# =====================================================================
def load_real_dataset(firms_csv_path: str, label_method: str = "osm_proximity") -> pd.DataFrame:
    """Load a real FIRMS archive CSV and attach proxy labels.

    Label provenance is recorded — these are NOT ground truth.
    'osm_proximity': observations within 2 km of a known facility get the
    facility's subtype; others get a coarse default.
    """
    df = pd.read_csv(firms_csv_path, low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]

    # Normalize to research schema
    out = pd.DataFrame()
    out["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    out["frp"] = pd.to_numeric(
        df["frp"] if "frp" in df.columns else pd.Series(index=df.index, dtype="float64"),
        errors="coerce",
    )
    brightness_ti4 = df["bright_ti4"] if "bright_ti4" in df.columns else (
        df["brightness"] if "brightness" in df.columns else pd.Series(index=df.index, dtype="float64")
    )
    out["brightness_ti4"] = pd.to_numeric(brightness_ti4, errors="coerce")
    brightness_ti5 = df["bright_ti5"] if "bright_ti5" in df.columns else (
        df["bright_t31"] if "bright_t31" in df.columns else pd.Series(index=df.index, dtype="float64")
    )
    out["brightness_ti5"] = pd.to_numeric(brightness_ti5, errors="coerce")
    out["scan"] = pd.to_numeric(df["scan"], errors="coerce")
    out["track"] = pd.to_numeric(df["track"], errors="coerce")
    out["sensor"] = df["instrument"].astype(str).str.lower().map(
        {"viirs": "viirs", "modis": "modis"}).fillna("unknown")
    out["platform"] = df["satellite"].astype(str).str.lower()
    out["confidence"] = _normalize_confidence(df["confidence"])
    out["day_night"] = df["daynight"].astype(str).str.lower().map(
        {"d": "day", "n": "night"}).fillna("unknown")
    out["observed_at"] = _parse_firms_datetime(df["acq_date"], df["acq_time"])
    out = out.dropna(subset=["latitude", "longitude", "observed_at"])

    # Assign observations to nearest facility within 2 km
    assignments = []
    for _, row in out.iterrows():
        nearest, dist = _nearest_facility(row["latitude"], row["longitude"])
        if nearest is not None and dist <= 2.0:
            assignments.append((nearest.facility_id, nearest.facility_type, "osm_proximity"))
        else:
            assignments.append(("", "", "unlabeled"))
    out["facility_id"] = [a[0] for a in assignments]
    out["facility_type"] = [a[1] for a in assignments]
    out["label_provenance"] = [a[2] for a in assignments]
    out["label_source_class"] = out["facility_type"].where(
        out["facility_type"] != "", "natural_fire")  # coarse default for unlabeled
    out["label_normality"] = ""  # unknown for real data without validation
    out["is_natural_fire"] = out["facility_id"] == ""
    out["event_id"] = ""
    out["observation_id"] = [f"OBS-{i:07d}" for i in range(len(out))]
    out["landcover"] = "unknown"

    return out


def _nearest_facility(lat: float, lon: float) -> tuple[Facility | None, float]:
    """Find nearest facility and distance in km."""
    best, best_d = None, float("inf")
    for fac in FACILITY_REGISTRY:
        d = _haversine_km(lat, lon, fac.latitude, fac.longitude)
        if d < best_d:
            best, best_d = fac, d
    return best, best_d


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _normalize_confidence(series):
    def _norm(v):
        try:
            n = int(v)
            return "low" if n < 30 else ("nominal" if n < 80 else "high")
        except (ValueError, TypeError):
            return str(v).strip().lower()
    return series.map(_norm)


def _parse_firms_datetime(dates, times):
    def _parse(d, t):
        try:
            t = str(t).zfill(4)
            return pd.Timestamp(f"{d} {t[:2]}:{t[2:]}:00", tz="UTC")
        except Exception:
            return pd.NaT
    return pd.Series([_parse(d, t) for d, t in zip(dates, times)])


# =====================================================================
# Dataset manifest
# =====================================================================
def create_dataset_manifest(df: pd.DataFrame, source: str, version: str) -> dict:
    """Create a frozen dataset manifest for reproducibility."""
    return {
        "dataset_version": version,
        "source": source,
        "n_observations": len(df),
        "n_facilities": int(df["facility_id"].nunique()),
        "date_range": [str(df["observed_at"].min()), str(df["observed_at"].max())],
        "class_distribution": df["label_source_class"].value_counts().to_dict(),
        "label_provenance": df["label_provenance"].value_counts().to_dict(),
        "schema_hash": _hash_dataframe_schema(df),
        "content_hash": _hash_dataframe_content(df),
    }


def _hash_dataframe_schema(df):
    return hashlib.sha256(
        json.dumps({c: str(df[c].dtype) for c in df.columns}, sort_keys=True).encode()
    ).hexdigest()[:16]


def _hash_dataframe_content(df):
    row_hashes = np.asarray(pd.util.hash_pandas_object(df, index=True))
    return hashlib.sha256(
        row_hashes.tobytes()
    ).hexdigest()[:16]


