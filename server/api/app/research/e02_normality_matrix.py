"""E02-E07: Facility-normality ablation matrix (ladder A-H).

Rungs (matching V2 plan section 8):
    A FIRMS-only            (frozen B0 features)
    B + facility context    (frozen B1 features)
    C + persistence         (frozen B2/B3 features)
    D + facility normality  (state features + intensity residual)   <- E2/E3
    E + spatial novelty     (zone distance, new-zone flag)          <- E4
    F + temporal novelty    (hour surprise, interval z)             <- E5
    G + thermal topology    (window-vs-baseline zone change)        <- E6 (kill test)
    H + environment         (SYNTHETIC seasonal weather)            <- E7 scaffold

Two tasks per rung:
    1. Source classification (macro-F1) â€” must not regress
    2. Anomaly detection (normality task): rule detector with train-fold-tuned
       thresholds + RF-with-features detector. F1, false-alerts/facility-day.

Two splits: facility_grouped (unseen facilities -> honest cold-start) and
temporal (same facilities, future time -> where normality SHOULD help).

Usage:
    python -m app.research.e02_normality_matrix --n-days 120
    python -m app.research.e02_normality_matrix --split temporal
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score

from app.ml.normal_state import build_states_for_fold
from app.ml.residuals import (
    MAD_TO_SIGMA,
    intensity_residual,
    spatial_residual,
    temporal_residual,
)
from app.research.baselines import (
    extract_b0_features,
    extract_b1_features,
    extract_b2_features,
    get_facility_coords,
)
from app.research.config import (
    DATASET_SCHEMA_VERSION,
    FEATURE_SCHEMA_VERSION,
    MODEL_SEED,
    RF_MAX_DEPTH,
    RF_MAX_FEATURES,
    RF_MIN_SAMPLES_LEAF,
    RF_N_ESTIMATORS,
    SOURCE_CLASSES,
    SPLIT_SEED,
)
from app.research.dataset import (
    create_dataset_manifest,
    generate_synthetic_dataset,
)
from app.research.metrics import (
    classification_metrics,
    false_alerts_per_facility_day,
)
from app.research.runner import run_experiment
from app.research.splits import facility_grouped_split, temporal_split
from app.research.topology import topology_change, window_zones

CLASS_TO_IDX = {c: i for i, c in enumerate(SOURCE_CLASSES)}
IDX_TO_CLASS = {i: c for c, i in CLASS_TO_IDX.items()}


@dataclass(frozen=True)
class TopologyLite:
    """Cache-friendly topology result for the G-rung feature builder."""

    n_new_zones: int
    n_lost_zones: int
    max_centroid_shift_km: float
    zone_jaccard: float
    changed: bool


# =====================================================================
# Fixed-label-space RF (unseen-in-train classes score recall 0, never crash)
# =====================================================================
def fit_fixed_rf(X: pd.DataFrame, y: pd.Series) -> RandomForestClassifier:
    """Train an RF on integer-encoded labels; stash present codes for proba
    re-indexing so train-absent classes stay honestly unpredictable."""
    codes = y.map(CLASS_TO_IDX).to_numpy()
    present = sorted(set(np.asarray(codes).tolist()))
    rf = RandomForestClassifier(
        n_estimators=RF_N_ESTIMATORS, max_depth=RF_MAX_DEPTH,
        min_samples_leaf=RF_MIN_SAMPLES_LEAF, max_features=RF_MAX_FEATURES,
        class_weight="balanced_subsample", random_state=MODEL_SEED, n_jobs=-1,
    )
    rf.fit(X.to_numpy(dtype=float), codes)
    rf._present_codes = present  # type: ignore[attr-defined]
    return rf


def predict_fixed(rf: RandomForestClassifier, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Full 10-dim proba with zeros for train-absent classes; argmax can
    therefore never predict an untrained class (honest)."""
    proba_sub = rf.predict_proba(X.to_numpy(dtype=float))
    full = np.zeros((len(X), len(SOURCE_CLASSES)))
    present: list[int] = getattr(rf, "_present_codes", [])
    for k, c in enumerate(present):
        full[:, c] = proba_sub[:, k]
    pred = full.argmax(axis=1)
    return pred, full

# =====================================================================
# Rung D-H feature builders (aligned by index with the source df)
# =====================================================================
def add_normality_features(df: pd.DataFrame, states: dict) -> pd.DataFrame:
    """Rung D: state existence + intensity residual."""
    cols = {k: np.zeros(len(df)) for k in
            ["has_state", "state_n_obs_log", "state_log_median", "state_log_mad",
             "intensity_z", "intensity_abs_z", "frp_ratio", "night_ratio_delta"]}
    for i, row in enumerate(df.itertuples()):
        st = states.get(row.facility_id) if row.facility_id else None
        if st is None or not st.sufficient:
            continue
        cols["has_state"][i] = 1.0
        cols["state_n_obs_log"][i] = np.log1p(st.n_observations)
        if st.log_frp_median is not None:
            cols["state_log_median"][i] = st.log_frp_median
        if st.log_frp_mad is not None:
            cols["state_log_mad"][i] = st.log_frp_mad
        if st.night_ratio is not None:
            observed_at = pd.to_datetime(str(row.observed_at), errors="coerce")
            hour = int(observed_at.strftime("%H")) if not pd.isna(observed_at) else -1
            is_night = 1.0 if (hour < 6 or hour >= 18) else 0.0
            cols["night_ratio_delta"][i] = is_night - st.night_ratio
        r = intensity_residual(float(str(row.frp)), st)
        if r.z is not None:
            cols["intensity_z"][i] = r.z
            cols["intensity_abs_z"][i] = abs(r.z)
        if r.frp_ratio:
            cols["frp_ratio"][i] = min(r.frp_ratio, 20.0)
    return pd.DataFrame(cols, index=df.index)


def add_spatial_features(
    df: pd.DataFrame, states: dict, new_zone_km: float = 1.5
) -> pd.DataFrame:
    """Rung E: distance to nearest normal zone, new-zone flag."""
    cols = {k: np.zeros(len(df)) for k in
            ["nearest_zone_km", "is_new_zone", "n_zones", "zone_noise_share",
             "zones_known"]}
    for i, row in enumerate(df.itertuples()):
        st = states.get(row.facility_id) if row.facility_id else None
        if st is None or not st.sufficient:
            continue
        r = spatial_residual(
            float(str(row.latitude)),
            float(str(row.longitude)),
            st,
            new_zone_km,
        )
        cols["n_zones"][i] = len(st.zones)
        cols["zone_noise_share"][i] = st.noise_share
        cols["zones_known"][i] = r.zones_known
        if r.nearest_zone_km is not None:
            cols["nearest_zone_km"][i] = min(r.nearest_zone_km, 20.0)
        if r.is_new_zone:
            cols["is_new_zone"][i] = 1.0
    return pd.DataFrame(cols, index=df.index)


def add_temporal_features(df: pd.DataFrame, states: dict) -> pd.DataFrame:
    """Rung F: hour surprise + inter-detection interval z (causal lookback)."""
    cols = {k: np.zeros(len(df)) for k in ["hour_surprise", "interval_z", "dpd_ratio"]}
    df_sorted = df.sort_values("observed_at")
    last_seen: dict[str, pd.Timestamp] = {}
    for row in df_sorted.itertuples():
        pos = df.index.get_loc(row.Index)
        facility_id = str(row.facility_id) if row.facility_id else None
        observed_at = pd.Timestamp(str(row.observed_at))
        st = states.get(facility_id) if facility_id else None
        if st is not None and st.sufficient:
            r = temporal_residual(observed_at.hour, None, st)
            if r.hour_surprise is not None:
                cols["hour_surprise"][pos] = r.hour_surprise
            if st.detections_per_active_day:
                cols["dpd_ratio"][pos] = st.detections_per_active_day
            prev = last_seen.get(facility_id) if facility_id else None
            if (
                prev is not None
                and st.median_gap_days is not None
                and st.gap_mad_days is not None
            ):
                gap = (observed_at - prev).total_seconds() / 86400.0
                cols["interval_z"][pos] = np.clip(
                    (gap - st.median_gap_days) / (MAD_TO_SIGMA * st.gap_mad_days),
                    -10, 10,
                )
        if facility_id:
            last_seen[facility_id] = observed_at
    return pd.DataFrame(cols, index=df.index)


def add_topology_features(
    df: pd.DataFrame, states: dict, window_days: int = 14
) -> pd.DataFrame:
    """Rung G: trailing-window zone structure vs baseline zones.

    Causal: window uses only same-facility observations from the past
    ``window_days`` days INCLUDING the current one."""
    cols = {k: np.zeros(len(df)) for k in
            ["topo_new_zones", "topo_lost_zones", "topo_centroid_shift",
             "topo_jaccard", "topo_changed"]}
    df_sorted = df.sort_values("observed_at")
    cache: dict[tuple, TopologyLite] = {}
    for row in df_sorted.itertuples():
        st = states.get(row.facility_id) if row.facility_id else None
        if st is None or not st.sufficient:
            continue
        pos = df.index.get_loc(row.Index)
        observed_at = pd.Timestamp(str(row.observed_at))
        key = (row.facility_id, observed_at.date())
        if key not in cache:
            win = df_sorted[
                (df_sorted["facility_id"] == row.facility_id)
                & (df_sorted["observed_at"] <= observed_at)
                & (df_sorted["observed_at"]
                   > observed_at - pd.Timedelta(days=window_days))
            ]
            change = topology_change(st, window_zones(win))
            cache[key] = TopologyLite(
                n_new_zones=change.n_new_zones,
                n_lost_zones=change.n_lost_zones,
                max_centroid_shift_km=change.max_centroid_shift_km,
                zone_jaccard=change.zone_jaccard,
                changed=change.changed,
            )
        ch = cache[key]
        cols["topo_new_zones"][pos] = ch.n_new_zones
        cols["topo_lost_zones"][pos] = ch.n_lost_zones
        cols["topo_centroid_shift"][pos] = ch.max_centroid_shift_km
        cols["topo_jaccard"][pos] = ch.zone_jaccard
        if ch.changed:
            cols["topo_changed"][pos] = 1.0
    return pd.DataFrame(cols, index=df.index)


def add_weather_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rung H: SYNTHETIC seasonal weather (machinery validation only).

    Real integration: Open-Meteo historical API keyed on (lat, lon, date).
    Documented as synthetic in every artifact this produces."""
    lats = df["latitude"].to_numpy(dtype=float)
    doy = df["observed_at"].dt.dayofyear.to_numpy(dtype=float)
    # Crude monsoon-influenced model for the subcontinent (deterministic)
    temp = 30.0 - 12.0 * np.cos(2 * np.pi * (doy - 120) / 365) - 0.5 * (lats - 20)
    monsoon = np.clip(np.sin(2 * np.pi * (doy - 150) / 365), 0, 1)
    humidity = 45 + 45 * monsoon
    rain = 8.0 * monsoon ** 2
    return pd.DataFrame({
        "wx_temp_c": np.round(temp, 2),
        "wx_humidity": np.round(humidity, 1),
        "wx_rain_mm": np.round(rain, 2),
        "wx_frp_temp_interaction": np.round(
            np.log1p(df["frp"].clip(lower=0).to_numpy(dtype=float)) * temp, 3),
    }, index=df.index)


def tune_rule_detector(
    train_df: pd.DataFrame, states: dict
) -> tuple[tuple[float, float], float]:
    """Grid-tune (z_t, surprise_t) maximizing F1 on the TRAIN fold only."""
    feats = pd.concat([
        add_normality_features(train_df, states),
        add_spatial_features(train_df, states),
        add_temporal_features(train_df, states),
    ], axis=1)
    y_true = (train_df["label_normality"] == "abnormal").astype(int).to_numpy()
    best, best_cfg = -1.0, (3.5, 0.8)
    for zt in (2.5, 3.0, 3.5, 4.0):
        for st_ in (0.6, 0.8, 0.95):
            pred = ((feats["intensity_abs_z"].to_numpy() > zt)
                    | (feats["is_new_zone"].to_numpy() > 0)
                    | (feats["hour_surprise"].to_numpy() > st_)).astype(int)
            f1 = f1_score(y_true, pred, zero_division=0)
            if f1 > best:
                best, best_cfg = f1, (zt, st_)
    return best_cfg, float(best)


def run_matrix(
    df: pd.DataFrame, source: str, split_name: str, seed: int
) -> tuple[dict, pd.DataFrame, str]:
    """Run the full A-H ablation ladder on one split.

    Returns (metrics_dict, predictions_df, conclusion_md).
    """
    if split_name == "facility_grouped":
        train_idx, test_idx, split_manifest = facility_grouped_split(df, seed=seed)
    else:
        train_idx, test_idx, split_manifest = temporal_split(df)
    train_df, test_df = df.loc[train_idx].copy(), df.loc[test_idx].copy()

    # --- Normal states from TRAIN fold ONLY (leakage control) ---
    states = build_states_for_fold(train_df)
    n_sufficient = sum(1 for s in states.values() if s.sufficient)

    # --- Rule-detector thresholds from TRAIN only ---
    (zt, st_), train_f1 = tune_rule_detector(train_df, states)

    # --- Feature ladders ---
    facility_coords = get_facility_coords()
    base = {
        "A_firms": extract_b0_features,
        "B_context": lambda d: extract_b1_features(d, facility_coords),
        "C_persistence": extract_b2_features,
    }
    def f_D(d: pd.DataFrame) -> pd.DataFrame:
        return add_normality_features(d, states)

    def f_E(d: pd.DataFrame) -> pd.DataFrame:
        return add_spatial_features(d, states)

    def f_F(d: pd.DataFrame) -> pd.DataFrame:
        return add_temporal_features(d, states)

    def f_G(d: pd.DataFrame) -> pd.DataFrame:
        return add_topology_features(d, states)

    f_H = add_weather_features

    ladders: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    ladders["A_firms"] = (base["A_firms"](train_df), base["A_firms"](test_df))
    ladders["B_context"] = (base["B_context"](train_df), base["B_context"](test_df))

    def _stack_b3(d: pd.DataFrame) -> pd.DataFrame:
        b1 = base["B_context"](d)
        b2 = base["C_persistence"](d)
        b2_only = b2.drop(columns=[c for c in b2.columns if c in b1.columns])
        return pd.concat([b1, b2_only], axis=1)

    ladders["C_persistence"] = (_stack_b3(train_df), _stack_b3(test_df))

    def _stack(prev_tr: pd.DataFrame, prev_te: pd.DataFrame,
               fn) -> tuple[pd.DataFrame, pd.DataFrame]:
        add_tr, add_te = fn(train_df), fn(test_df)
        return (pd.concat([prev_tr, add_tr], axis=1),
                pd.concat([prev_te, add_te], axis=1))

    prev = ladders["C_persistence"]
    for name, fn in [("D_normality", f_D), ("E_spatial", f_E),
                     ("F_temporal", f_F), ("G_topology", f_G),
                     ("H_environment", f_H)]:
        prev = _stack(*prev, fn)
        ladders[name] = prev

    # --- Evaluate ladder: source classification + anomaly detection ---
    y_train = train_df["label_source_class"]
    y_test_raw = test_df["label_source_class"].astype("object").to_numpy()
    rows: list[dict] = []
    predictions: list[pd.DataFrame] = []
    prev_f1: float | None = None
    for name, (Xtr, Xte) in ladders.items():
        rf = fit_fixed_rf(Xtr, y_train)
        pred_codes, _ = predict_fixed(rf, Xte)
        y_pred = [IDX_TO_CLASS[c] for c in pred_codes]
        cls = classification_metrics(
            y_test_raw, np.asarray(y_pred, dtype=object), labels=SOURCE_CLASSES
        )

        # Anomaly detection on this rung's features (D+ have residual signal)
        anom_f1: float | None = None
        false_alert: float | None = None
        if name >= "D_normality":  # lexical order works: D < E < F < G < H
            anom_rf = RandomForestClassifier(
                n_estimators=200, max_depth=10, class_weight="balanced",
                random_state=MODEL_SEED, n_jobs=-1,
            )
            y_anom_tr = (train_df["label_normality"] == "abnormal").astype(int)
            anom_rf.fit(Xtr.to_numpy(dtype=float), y_anom_tr.to_numpy())
            anom_pred = anom_rf.predict(Xte.to_numpy(dtype=float))
            anom_f1 = round(float(f1_score(
                (test_df["label_normality"] == "abnormal").astype(int).to_numpy(),
                anom_pred, zero_division=0)), 4)
            tmp = test_df[["facility_id", "observed_at", "label_normality"]].copy()
            tmp["anom_pred"] = np.where(anom_pred == 1, "abnormal", "normal")
            fa = false_alerts_per_facility_day(tmp, tmp["anom_pred"].to_numpy())
            false_alert = fa.get("false_alert_rate_per_facility_day")

        delta = (
            round(cls["macro_f1"] - prev_f1, 4) if prev_f1 is not None else None
        )
        verdict = _verdict(name, delta, anom_f1)
        rows.append({
            "rung": name, "n_features": int(Xtr.shape[1]),
            "source_macro_f1": cls["macro_f1"],
            "facility_accuracy": _facility_acc(test_df, y_pred),
            "anomaly_f1": anom_f1, "false_alert_rate": false_alert,
            "delta_vs_prev": delta, "verdict": verdict,
        })
        prev_f1 = cls["macro_f1"]

        p = test_df[["observation_id", "facility_id", "label_source_class"]].copy()
        p["rung"] = name
        p["y_pred"] = y_pred
        predictions.append(p)

    # --- Rule detector (no ML) on D-F features ---
    rule_rows, rule_test_f1 = _rule_detector_eval(
        test_df, states, zt, st_, train_f1)

    # --- Per-anomaly-type breakdown ---
    anom_breakdown = _anomaly_type_breakdown(test_df, states, zt, st_)

    comparison = pd.DataFrame(rows)
    print(comparison.to_string(index=False))

    conclusion = _conclusion(split_name, comparison, states, n_sufficient,
                             rule_rows, anom_breakdown, source)

    metrics = {
        "experiment": "E02_normality_matrix",
        "split": split_name,
        "split_manifest_summary": {
            k: split_manifest[k] for k in
            ("split_method", "split_id", "n_train_observations",
             "n_test_observations") if k in split_manifest
        },
        "states": {"n_facilities": len(states), "n_sufficient": n_sufficient},
        "rule_detector": {
            "tuned_thresholds": {"z": zt, "surprise": st_},
            "train_f1": round(train_f1, 4),
            "test_f1": rule_test_f1,
            "results": rule_rows,
        },
        "anomaly_type_breakdown": anom_breakdown,
        "ladder": rows,
    }
    return metrics, pd.concat(predictions, ignore_index=True), conclusion


def _facility_acc(test_df: pd.DataFrame, y_pred: list[str]) -> float | None:
    """Facility-level majority-vote accuracy (context carries the signal)."""
    t = test_df[["facility_id"]].copy()
    t["true"] = test_df["label_source_class"].astype(str).to_numpy()
    t["pred"] = y_pred
    t = t[t["facility_id"] != ""]
    if t.empty:
        return None
    votes = t.groupby("facility_id").agg(
        a=("true", lambda x: x.mode().iloc[0]),
        b=("pred", lambda x: pd.Series(x).mode().iloc[0]),
    )
    return round(float((votes.a == votes.b).mean()), 4)


def _verdict(name: str, delta: float | None, anom_f1: float | None) -> str:
    if name in ("A_firms", "B_context", "C_persistence"):
        return "baseline"
    if name == "G_topology":
        return (
            "PROMOTE" if (delta is not None and delta >= 0.005)
            else "DROP (kill test)"
        )
    if delta is not None and delta >= 0.005:
        return "PROMOTE"
    if delta is not None and delta >= -0.005:
        return "KEEP (neutral)"
    return "DROP"


def _rule_detector_eval(
    test_df: pd.DataFrame, states: dict,
    zt: float, st_: float, train_f1: float,
) -> tuple[list[dict], float]:
    """Evaluate the train-tuned threshold rule on the TEST fold (no ML).

    This is the deployable detector: three threshold checks, no fitting.
    """
    feats = pd.concat([
        add_normality_features(test_df, states),
        add_spatial_features(test_df, states),
        add_temporal_features(test_df, states),
    ], axis=1)
    y_true = (test_df["label_normality"] == "abnormal").astype(int).to_numpy()
    pred = (
        (feats["intensity_abs_z"].to_numpy() > zt)
        | (feats["is_new_zone"].to_numpy() > 0)
        | (feats["hour_surprise"].to_numpy() > st_)
    ).astype(int)
    test_f1 = round(float(f1_score(y_true, pred, zero_division=0)), 4)
    tmp = test_df[["facility_id", "observed_at", "label_normality"]].copy()
    tmp["pred"] = np.where(pred == 1, "abnormal", "normal")
    fa = false_alerts_per_facility_day(tmp, tmp["pred"].to_numpy())
    rows = [{
        "detector": "rule_thresholds",
        "z_threshold": zt,
        "surprise_threshold": st_,
        "train_f1": round(float(train_f1), 4),
        "test_f1": test_f1,
        "test_precision": round(
            float(precision_score(y_true, pred, zero_division=0)), 4),
        "test_recall": round(
            float(recall_score(y_true, pred, zero_division=0)), 4),
        "false_alert_rate_per_facility_day":
            fa.get("false_alert_rate_per_facility_day"),
    }]
    return rows, test_f1


def _anomaly_type_breakdown(
    test_df: pd.DataFrame, states: dict, zt: float, st_: float,
) -> dict[str, dict]:
    """Rule recall per injected anomaly type on the TEST fold.

    Answers: which failure modes does the threshold rule actually catch?
    """
    feats = pd.concat([
        add_normality_features(test_df, states),
        add_spatial_features(test_df, states),
        add_temporal_features(test_df, states),
    ], axis=1)
    pred = (
        (feats["intensity_abs_z"].to_numpy() > zt)
        | (feats["is_new_zone"].to_numpy() > 0)
        | (feats["hour_surprise"].to_numpy() > st_)
    )
    out: dict[str, dict] = {}
    is_abn = (test_df["label_normality"] == "abnormal").to_numpy()
    atypes = test_df["anomaly_type"].astype(str).to_numpy()
    for atype in sorted(set(atypes[is_abn]) - {""}):
        mask = is_abn & (atypes == atype)
        support = int(mask.sum())
        caught = int(pred[mask].sum())
        out[atype] = {
            "support": support,
            "caught_by_rule": caught,
            "recall": round(caught / support, 4) if support else 0.0,
        }
    return out


def _conclusion(
    split_name: str,
    comparison: pd.DataFrame,
    states: dict,
    n_sufficient: int,
    rule_rows: list[dict],
    anom_breakdown: dict,
    source: str,
) -> str:
    """Markdown verdict for conclusion.md (promote/drop per rung)."""
    data_note = (
        "SYNTHETIC data — every number below is a machinery validation, "
        "not a field result."
        if source == "synthetic"
        else f"source={source}"
    )
    base_row = comparison[comparison["rung"] == "A_firms"].iloc[0]
    lines = [
        f"## E02 normality matrix — {split_name} split",
        "",
        f"**Data:** {data_note}",
        "",
        f"- Facilities: {len(states)} total, {n_sufficient} with a "
        "sufficient normal state (train-fold only).",
        f"- Baseline (A FIRMS): macro-F1 "
        f"{base_row['source_macro_f1']}.",
        "",
        "| rung | Δ macro-F1 | anomaly F1 | false-alerts/fac-day | verdict |",
        "|---|---|---|---|---|",
    ]
    for r in comparison.itertuples():
        # itertuples fields are typed object; the .4f specs prove they are numeric.
        delta = "—" if r.delta_vs_prev is None else f"{r.delta_vs_prev:+.4f}"  # type: ignore[str-bytes-safe]
        anom = "—" if r.anomaly_f1 is None else f"{r.anomaly_f1:.4f}"  # type: ignore[str-bytes-safe]
        fa = "—" if r.false_alert_rate is None else f"{r.false_alert_rate:.4f}"  # type: ignore[str-bytes-safe]
        lines.append(
            f"| {r.rung} | {delta} | {anom} | {fa} | {r.verdict} |"
        )
    rule = rule_rows[0] if rule_rows else {}
    lines += [
        "",
        "### Rule detector (deployable, no ML)",
        f"- Tuned on train, test F1={rule.get('test_f1')}, "
        f"precision={rule.get('test_precision')}, "
        f"recall={rule.get('test_recall')}, "
        f"false alerts/facility-day="
        f"{rule.get('false_alert_rate_per_facility_day')}.",
        "",
        "### Per-anomaly-type recall (rule detector)",
    ]
    for atype, m in sorted(anom_breakdown.items()):
        lines.append(
            f"- {atype}: recall {m['recall']} "
            f"({m['caught_by_rule']}/{m['support']})"
        )
    lines += [
        "",
        "Kill test: G_topology PROMOTEs only if Δ ≥ +0.005 macro-F1; "
        "otherwise DROP regardless of novelty.",
        "",
        "> Labels are synthetic ground truth from the generative process; "
        "never on-site verified.",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="E02-E07 facility-normality ablation matrix")
    ap.add_argument("--n-days", type=int, default=120)
    ap.add_argument("--split", choices=["both", "temporal", "facility_grouped"],
                    default="both")
    ap.add_argument("--seed", type=int, default=SPLIT_SEED)
    ap.add_argument("--source", default="synthetic")
    args = ap.parse_args()

    df = generate_synthetic_dataset(n_days=args.n_days, seed=MODEL_SEED)
    dataset_manifest = create_dataset_manifest(
        df, args.source, DATASET_SCHEMA_VERSION)

    splits = (["temporal", "facility_grouped"] if args.split == "both"
              else [args.split])
    for split_name in splits:
        if split_name == "facility_grouped":
            _, _, split_manifest = facility_grouped_split(df, seed=args.seed)
        else:
            _, _, split_manifest = temporal_split(df)

        def _run() -> tuple[dict, pd.DataFrame, str]:
            return run_matrix(df, args.source, split_name, seed=args.seed)

        run_experiment(
            experiment_id=f"E02_normality_matrix_{split_name}",
            hypothesis=(
                "Facility-normality, spatial/temporal novelty, and topology "
                "features improve anomaly detection over FIRMS+context "
                "baselines without regressing source classification."
            ),
            dataset_manifest=dataset_manifest,
            split_manifest=split_manifest,
            config={
                "n_days": args.n_days,
                "seed": args.seed,
                "source": args.source,
                "split": split_name,
                "feature_schema": FEATURE_SCHEMA_VERSION,
                "rf": {
                    "n_estimators": RF_N_ESTIMATORS,
                    "max_depth": RF_MAX_DEPTH,
                    "min_samples_leaf": RF_MIN_SAMPLES_LEAF,
                    "max_features": str(RF_MAX_FEATURES),
                },
            },
            experiment_fn=_run,
        )


if __name__ == "__main__":
    main()