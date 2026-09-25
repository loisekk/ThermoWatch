"""Baseline implementations B0-B4 for experiment E1.

Feature ladder (ablation-ready):
    B0: FIRMS observation features only
    B1: B0 + facility proximity/context
    B2: B0 + persistence/history
    B3: B1 + B2 (all combined)
    B4: Facility-specific robust z-score (anomaly task)

B0-B3 use the same RandomForest classifier — only features differ.
B4 is a statistical method, no ML training required.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

from app.research.config import (
    B4_MIN_HISTORY_DAYS,
    B4_MIN_HISTORY_OBS,
    B4_ZSCORE_THRESHOLDS,
    BASELINE_MODEL_VERSION,
    FEATURE_SCHEMA_VERSION,
    MODEL_SEED,
    RF_MAX_DEPTH,
    RF_MAX_FEATURES,
    RF_MIN_SAMPLES_LEAF,
    RF_N_ESTIMATORS, 
)

# =====================================================================
# Feature extraction
# =====================================================================


def extract_b0_features(df: pd.DataFrame) -> pd.DataFrame:
    """B0: FIRMS observation features only — no external context."""
    out = pd.DataFrame(index=df.index)
    ln_frp = np.log1p(df["frp"].clip(lower=0))
    out["frp"] = df["frp"].fillna(0)
    out["log_frp"] = ln_frp
    out["brightness_ti4"] = df["brightness_ti4"].fillna(df["brightness_ti4"].median())
    out["brightness_ti5"] = df["brightness_ti5"].fillna(df["brightness_ti5"].median())
    out["delta_t"] = out["brightness_ti4"] - out["brightness_ti5"]
    out["bright_ratio"] = out["brightness_ti5"] / out["brightness_ti4"].clip(lower=1)
    out["scan"] = df["scan"]
    out["track"] = df["track"]
    out["scan_x_track"] = df["scan"] * df["track"]
    out["frp_density"] = df["frp"] / (df["scan"] * df["track"]).clip(lower=0.01)

    hour = df["observed_at"].dt.hour
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["is_night"] = (df["day_night"] == "night").astype(int)
    doy = df["observed_at"].dt.dayofyear
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365)

    # Categorical encodings
    out["is_viirs"] = (df["sensor"] == "viirs").astype(int)
    out["conf_enc"] = df["confidence"].map({"low": 0, "nominal": 1, "high": 2}).fillna(1)
    return out


def extract_b1_features(df: pd.DataFrame, facility_coords: list[tuple[float, float, str]]) -> pd.DataFrame:
    """B1: B0 + facility proximity/context (distance, nearest type, landcover)."""
    b0 = extract_b0_features(df)
    distances, types = [], []
    for _, row in df.iterrows():
        best_d, best_t = 999.0, "none"
        for flat, flon, ftype in facility_coords:
            d = _haversine(row["latitude"], row["longitude"], flat, flon)
            if d < best_d:
                best_d, best_t = d, ftype
        distances.append(best_d)
        types.append(best_t)

    b1 = b0.copy()
    dists = np.asarray(distances, dtype=float)
    types_arr = np.asarray(types, dtype=object)
    b1["facility_distance_km"] = dists
    b1["near_facility"] = (dists < 2.0).astype(int)
    # Continuous proximity signal — the one-hots below are gated at 2 km so a
    # wildfire 3 km from a refinery can never inherit near_refinery=1 (H6/H7).
    b1["facility_distance_decay"] = np.exp(-dists / 5.0)

    # One-hot encode nearest facility type — ONLY when actually near it
    for ftype in ["refinery", "steel", "gas_flare", "cement", "smelter",
                  "waste_incineration", "power_plant", "chemical", "none"]:
        b1[f"near_{ftype}"] = ((types_arr == ftype) & (dists <= 2.0)).astype(int)

    # Landcover one-hot
    for lc in ["forest", "agriculture", "industrial", "urban", "water", "barren", "unknown"]:
        b1[f"lc_{lc}"] = (df["landcover"] == lc).astype(int)
    return b1


def extract_b2_features(df: pd.DataFrame) -> pd.DataFrame:
    """B2: B0 + persistence/history features.

    Temporal lookback features computed strictly from PAST observations
    at nearby locations (no future information — temporal leakage safe).
    """
    b0 = extract_b0_features(df)
    df_sorted = df.sort_values("observed_at").copy()

    # Grid-cell key (0.1 degree ~ 11 km cells)
    df_sorted["grid_key"] = (
        (df_sorted["latitude"] / 0.1).round(1).astype(str) + "_"
        + (df_sorted["longitude"] / 0.1).round(1).astype(str)
    )

    persist_7d, persist_30d, frp_mean_30d, frp_std_30d = [], [], [], []
    grid_history: dict[str, list[tuple[pd.Timestamp, float]]] = {}

    for idx, row in df_sorted.iterrows():
        key = row["grid_key"]
        now = row["observed_at"]
        history = grid_history.get(key, [])

        # Filter to past 30 days
        recent = [(t, f) for (t, f) in history if (now - t).days <= 30]
        frps = [f for _, f in recent]

        persist_7d.append(sum(1 for t, _ in recent if (now - t).days <= 7))
        persist_30d.append(len(recent))
        frp_mean_30d.append(np.mean(frps) if frps else 0.0)
        frp_std_30d.append(np.std(frps) if len(frps) > 1 else 0.0)

        # Add current observation to history
        history.append((now, row["frp"]))
        grid_history[key] = history

    b2 = b0.copy()
    b2.loc[df_sorted.index, "persist_7d"] = persist_7d
    b2.loc[df_sorted.index, "persist_30d"] = persist_30d
    b2.loc[df_sorted.index, "frp_mean_30d"] = frp_mean_30d
    b2.loc[df_sorted.index, "frp_std_30d"] = frp_std_30d
    b2["frp_vs_history"] = b2["log_frp"] - np.log1p(b2["frp_mean_30d"].clip(lower=0))
    return b2


def extract_b3_features(df: pd.DataFrame, facility_coords: list[tuple[float, float, str]]) -> pd.DataFrame:
    """B3: All features combined (B1 + B2)."""
    b1 = extract_b1_features(df, facility_coords)
    b2 = extract_b2_features(df)
    # Merge on index, dropping duplicate B0 columns from b2
    b2_only = b2.drop(columns=[c for c in b2.columns if c in b1.columns])
    return pd.concat([b1, b2_only], axis=1)


def get_facility_coords() -> list[tuple[float, float, str]]:
    """Extract facility coordinates from the registry."""
    from app.research.dataset import FACILITY_REGISTRY
    return [(f.latitude, f.longitude, f.facility_type) for f in FACILITY_REGISTRY]


# =====================================================================
# Baseline models (B0-B3: RandomForest with frozen hyperparams)
# =====================================================================
def build_baseline_classifier() -> RandomForestClassifier:
    """Frozen RandomForest — no tuning in E1 (that would contaminate baselines)."""
    return RandomForestClassifier(
        n_estimators=RF_N_ESTIMATORS,
        max_depth=RF_MAX_DEPTH,
        min_samples_leaf=RF_MIN_SAMPLES_LEAF,
        max_features=RF_MAX_FEATURES,
        class_weight="balanced_subsample",
        random_state=MODEL_SEED,
        n_jobs=-1,
    )


def run_baseline(
    name: str,
    X_train: pd.DataFrame, y_train: np.ndarray,
    X_test: pd.DataFrame, y_test: np.ndarray,
    train_df: pd.DataFrame, test_df: pd.DataFrame,
) -> dict:
    """Train and evaluate a baseline classifier (B0-B3 pattern).

    The label space is FIXED to SOURCE_CLASSES so a facility-grouped split
    that holds out an entire class is scored honestly (recall 0 + flagged
    support) instead of crashing the encoder.
    """
    from app.research.config import SOURCE_CLASSES

    le = LabelEncoder().fit(SOURCE_CLASSES)
    y_train_enc = le.transform(y_train)
    y_test_enc = le.transform(y_test)

    clf = build_baseline_classifier()
    clf.fit(X_train, y_train_enc)

    y_pred_enc = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)
    y_pred = le.inverse_transform(y_pred_enc)
    y_true = le.inverse_transform(y_test_enc)

    from app.research.metrics import (
        calibration_metrics,
        classification_metrics,
        facility_level_metrics,
        risk_coverage_curve,
    )

    return {
        "baseline": name,
        "model_version": BASELINE_MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "n_features": int(X_train.shape[1]),
        "classification": classification_metrics(y_true, y_pred, labels=list(le.classes_)),
        "facility_level": facility_level_metrics(test_df, y_pred),
        "risk_coverage": risk_coverage_curve(
            np.asarray(y_test_enc), np.asarray(y_pred_enc), y_proba.max(axis=1)
        ),
        "calibration": calibration_metrics(np.asarray(y_test_enc), y_proba),
    }


# =====================================================================
# B4: Facility-specific statistical anomaly baseline
# =====================================================================
def run_b4_statistical_anomaly(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> dict:
    """B4: Robust z-score on log(FRP) per facility.

    For each facility, learn median and MAD of log(FRP) from TRAIN fold.
    Flag test observations with |z| > threshold as abnormal.

    Threshold is selected on train fold — no test leakage.
    """
    # Build facility statistics from train
    facility_stats: dict[str, dict | None] = {}
    for raw_fid, group in train_df[train_df["facility_id"] != ""].groupby("facility_id"):
        fid = str(raw_fid)
        if len(group) < B4_MIN_HISTORY_OBS:
            facility_stats[fid] = None
            continue
        log_frp = np.log1p(group["frp"].clip(lower=0))
        median = float(np.median(log_frp))
        mad = float(np.median(np.abs(log_frp - median)))
        n_days = (group["observed_at"].max() - group["observed_at"].min()).days
        facility_stats[fid] = {
            "median": median,
            "mad": max(mad, 1e-6),  # avoid division by zero
            "n_obs": len(group),
            "n_days": n_days,
            "sufficient_history": n_days >= B4_MIN_HISTORY_DAYS and len(group) >= B4_MIN_HISTORY_OBS,
        }

    # Select best threshold on train fold
    best_threshold, best_f1 = B4_ZSCORE_THRESHOLDS[0], -1.0
    for thresh in B4_ZSCORE_THRESHOLDS:
        y_pred_train = _b4_predict(train_df, facility_stats, thresh)
        mask = ~pd.isna(y_pred_train)
        if mask.sum() == 0:
            continue
        from sklearn.metrics import f1_score
        y_true_train = np.asarray(
            (train_df.loc[mask, "label_normality"] == "abnormal").astype(int),
            dtype=int,
        )
        f1 = f1_score(y_true_train, y_pred_train[mask].astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_threshold = f1, thresh

    # Final prediction on test with selected threshold
    test_facility = test_df[test_df["facility_id"] != ""].copy()
    y_pred_test = _b4_predict(test_facility, facility_stats, best_threshold)

    # Filter to observations where B4 can make a prediction (has facility history)
    evaluable = ~pd.isna(y_pred_test)
    n_evaluable = int(evaluable.sum())
    n_insufficient = len(test_facility) - n_evaluable

    if n_evaluable == 0:
        return {"baseline": "B4_statistical", "error": "No evaluable test observations"}

    y_true_bin = np.asarray(
        (test_facility.loc[evaluable, "label_normality"] == "abnormal").astype(int),
        dtype=int,
    )
    y_pred_bin = np.asarray(y_pred_test[evaluable].astype(int), dtype=int)

    from sklearn.metrics import f1_score, precision_score, recall_score

    from app.research.metrics import false_alerts_per_facility_day

    # Also compute facility-day false alert rate
    evaluable_df = test_facility[evaluable].copy()
    evaluable_df["b4_pred"] = np.where(y_pred_bin == 1, "abnormal", "normal")

    return {
        "baseline": "B4_statistical",
        "model_version": BASELINE_MODEL_VERSION,
        "method": f"robust z-score on log(FRP), threshold={best_threshold} (tuned on train)",
        "thresholds_tried": B4_ZSCORE_THRESHOLDS,
        "selected_threshold": best_threshold,
        "train_best_f1": round(float(best_f1), 4),
        "n_facilities_with_stats": sum(1 for v in facility_stats.values() if v),
        "n_evaluable": n_evaluable,
        "n_insufficient_history": int(n_insufficient),
        "abnormal_recall": round(float(recall_score(y_true_bin, y_pred_bin, zero_division=0)), 4),
        "abnormal_precision": round(float(precision_score(y_true_bin, y_pred_bin, zero_division=0)), 4),
        "abnormal_f1": round(float(f1_score(y_true_bin, y_pred_bin, zero_division=0)), 4),
        "false_alert_metrics": false_alerts_per_facility_day(
            evaluable_df, evaluable_df["b4_pred"].to_numpy()
        ),
        "note": "B4 abstains on facilities with insufficient history (reported separately)",
    }


def _b4_predict(df: pd.DataFrame, facility_stats: dict, threshold: float) -> pd.Series:
    """Predict abnormal (1) / normal (0) / abstain (NaN) per observation."""
    preds = pd.Series(np.nan, index=df.index)
    for position, (_, row) in enumerate(df.iterrows()):
        fid = row["facility_id"]
        stats = facility_stats.get(fid)
        if stats is None or not stats.get("sufficient_history"):
            continue  # abstain
        z = (np.log1p(max(row["frp"], 0)) - stats["median"]) / (1.4826 * stats["mad"])
        preds.iloc[position] = 1 if abs(z) > threshold else 0
    return preds


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


