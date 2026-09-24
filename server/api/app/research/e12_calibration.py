"""E12: Calibration and abstention evaluation.

Three-way split: train / calibration / test.
- Train: fit the RF classifier
- Calibration: fit temperature T and abstention threshold
- Test: report final metrics with calibration applied

Outputs: ECE before/after, Brier, risk-coverage curve, AURC,
coverage at 90%, selective risk at 90% coverage.

Usage:
    python -m app.research.e12_calibration --n-days 120
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score

from app.ml.calibration import (
    AbstentionPolicy,
    apply_temperature_scaling,
    expected_calibration_error,
    fit_temperature_scaling,
    risk_coverage_curve,
    tune_abstention_threshold,
)
from app.research.baselines import extract_b1_features, get_facility_coords
from app.research.config import (DATASET_SCHEMA_VERSION, MODEL_SEED,
                                 SOURCE_CLASSES, SPLIT_SEED)
from app.research.dataset import create_dataset_manifest, generate_synthetic_dataset
from app.research.runner import run_experiment
from app.research.splits import facility_grouped_split

CLASS_TO_IDX = {c: i for i, c in enumerate(SOURCE_CLASSES)}


def run_calibration_experiment(
    df: pd.DataFrame, source: str, seed: int,
) -> tuple[dict, pd.DataFrame, str]:
    """Three-way split: train -> calibrate -> test."""
    facility_coords = get_facility_coords()

    # --- Split: 60% train, 20% calibration, 20% test (facility-grouped) ---
    train_idx, rest_idx, _ = facility_grouped_split(df, test_size=0.4, seed=seed)
    cal_idx, test_idx, _ = facility_grouped_split(df.loc[rest_idx], test_size=0.5, seed=seed)

    train_df = df.loc[train_idx].copy()
    cal_df = df.loc[cal_idx].copy()
    test_df = df.loc[test_idx].copy()

    # --- Features ---
    X_train = extract_b1_features(train_df, facility_coords)
    X_cal = extract_b1_features(cal_df, facility_coords)
    X_test = extract_b1_features(test_df, facility_coords)

    y_train = train_df["label_source_class"].map(CLASS_TO_IDX).to_numpy()
    y_cal = cal_df["label_source_class"].map(CLASS_TO_IDX).to_numpy()
    y_test = test_df["label_source_class"].map(CLASS_TO_IDX).to_numpy()

    # --- Train RF ---
    present = sorted(set(y_train.tolist()))
    rf = RandomForestClassifier(
        n_estimators=300, max_depth=12, min_samples_leaf=5,
        max_features="sqrt", class_weight="balanced_subsample",
        random_state=MODEL_SEED, n_jobs=-1)
    rf.fit(X_train.to_numpy(dtype=float), y_train)

    # --- Predictions, re-indexed to the full 10-class label space ---
    proba_cal = rf.predict_proba(X_cal.to_numpy(dtype=float))
    proba_test = rf.predict_proba(X_test.to_numpy(dtype=float))

    full_proba_cal = np.zeros((len(cal_df), len(SOURCE_CLASSES)))
    full_proba_test = np.zeros((len(test_df), len(SOURCE_CLASSES)))
    col_map = {c: k for k, c in enumerate(present)}
    for c, k in col_map.items():
        full_proba_cal[:, c] = proba_cal[:, k]
        full_proba_test[:, c] = proba_test[:, k]

    # Convert probabilities to logits for temperature scaling
    logits_cal = np.log(np.clip(full_proba_cal, 1e-10, 1.0))
    logits_test = np.log(np.clip(full_proba_test, 1e-10, 1.0))

    # --- Pre-calibration metrics ---
    pred_test_raw = full_proba_test.argmax(axis=1)
    ece_before = expected_calibration_error(y_test, full_proba_test)
    f1_before = float(f1_score(y_test, pred_test_raw, average="macro", zero_division=0))
    # Same metrics on the subset the model's label space can represent
    # (true class seen in training) — the population T was fit for.
    test_in_space = np.isin(y_test, np.array(list(present), dtype=int))

    # --- Fit temperature on calibration set ---
    # Fit only on rows whose true class is in the model's output space:
    # classes absent from the grouped training fold are zero-padded columns
    # (constant logit = log(1e-10)), and NO temperature can rescue them —
    # including them in the NLL just pushes T to its search bound and ruins
    # calibration for rows the model can actually predict. Out-of-space rows
    # stay in the reported metrics (honest full-set view).
    in_space = np.isin(y_cal, np.array(list(present), dtype=int))
    cal_result = fit_temperature_scaling(logits_cal[in_space], y_cal[in_space])

    # --- Apply calibration ---
    calibrated_proba_test = apply_temperature_scaling(logits_test, cal_result.temperature)
    pred_test_cal = calibrated_proba_test.argmax(axis=1)
    ece_after = expected_calibration_error(y_test, calibrated_proba_test)
    f1_after = float(f1_score(y_test, pred_test_cal, average="macro", zero_division=0))
    # In-space ECE: isolates temperature-scaling quality from the
    # open-set effect of grouped folds (classes never seen in training).
    ece_before_inspace = (
        expected_calibration_error(y_test[test_in_space],
                                   full_proba_test[test_in_space])
        if test_in_space.any() else None
    )
    ece_after_inspace = (
        expected_calibration_error(y_test[test_in_space],
                                   calibrated_proba_test[test_in_space])
        if test_in_space.any() else None
    )

    # --- Tune abstention on calibration set (calibrated confidences) ---
    proba_cal_calibrated = apply_temperature_scaling(logits_cal, cal_result.temperature)
    conf_cal_cal = proba_cal_calibrated.max(axis=1)
    pred_cal_cal = proba_cal_calibrated.argmax(axis=1)

    abstention_80 = tune_abstention_threshold(y_cal, pred_cal_cal, conf_cal_cal, 0.80)
    abstention_90 = tune_abstention_threshold(y_cal, pred_cal_cal, conf_cal_cal, 0.90)
    abstention_95 = tune_abstention_threshold(y_cal, pred_cal_cal, conf_cal_cal, 0.95)

    # --- Evaluate abstention on TEST set (apply the CAL-tuned threshold —
    # no test-set peeking; test only measures achieved coverage/risk) ---
    conf_test = calibrated_proba_test.max(axis=1)
    abstention_test_90 = _apply_threshold(
        y_test, pred_test_cal, conf_test,
        abstention_90.confidence_threshold, target_coverage=0.90)

    # --- Risk-coverage curve on test ---
    rc_curve = risk_coverage_curve(y_test, pred_test_cal, conf_test)

    # --- Brier score ---
    onehot_test = np.zeros_like(calibrated_proba_test)
    for i, yt in enumerate(y_test):
        if 0 <= yt < len(SOURCE_CLASSES):
            onehot_test[i, yt] = 1.0
    brier = float(np.mean(np.sum((calibrated_proba_test - onehot_test) ** 2, axis=1)))

    # --- Predictions for artifact ---
    pred_df = test_df[["observation_id", "facility_id", "label_source_class"]].copy()
    pred_df["y_pred"] = [SOURCE_CLASSES[int(c)] for c in pred_test_cal]
    pred_df["confidence"] = conf_test
    pred_df["abstained_90"] = conf_test < abstention_90.confidence_threshold

    metrics = {
        "experiment": "E12_calibration_abstention",
        "split": {"train": len(train_df), "calibration": len(cal_df), "test": len(test_df)},
        "temperature_scaling": {
            "fitted_temperature": round(cal_result.temperature, 4),
            "ece_before": round(ece_before, 4),
            "ece_after": round(ece_after, 4),
            "ece_improvement": round(ece_before - ece_after, 4),
            "ece_before_inspace": (
                round(ece_before_inspace, 4)
                if ece_before_inspace is not None else None),
            "ece_after_inspace": (
                round(ece_after_inspace, 4)
                if ece_after_inspace is not None else None),
            "n_test_inspace": int(test_in_space.sum()),
            "n_test_total": int(len(y_test)),
            "f1_before": round(f1_before, 4),
            "f1_after": round(f1_after, 4),
            "brier_multiclass": round(brier, 4),
        },
        "abstention_policies": {
            "80pct": _policy_dict(abstention_80),
            "90pct": _policy_dict(abstention_90),
            "95pct": _policy_dict(abstention_95),
        },
        "test_evaluation_90pct": _policy_dict(abstention_test_90),
        "risk_coverage_curve": rc_curve,
        "aurc": abstention_test_90.aurc,
    }

    conclusion = _conclusion(metrics, source)
    return metrics, pred_df, conclusion


def _apply_threshold(
    y_true: "np.ndarray", y_pred: "np.ndarray", confidence: "np.ndarray",
    threshold: float, target_coverage: float,
) -> AbstentionPolicy:
    """Apply an already-tuned confidence threshold to new data.

    Reports what coverage/risk that fixed threshold ACHIEVES on this split —
    the threshold itself is never re-tuned here (no test-set peeking).
    AURC is threshold-independent (integral over all coverages), so it is
    computed on this split directly.
    """
    mask = confidence >= threshold
    n = len(y_true)
    n_covered = int(mask.sum())
    selective_risk = (
        float((y_true[mask] != y_pred[mask]).mean()) if n_covered else 1.0
    )
    order = np.argsort(-confidence)
    y_sorted = y_true[order]
    p_sorted = y_pred[order]
    coverages = np.arange(1, n + 1) / n if n else np.array([1.0])
    errors = (y_sorted != p_sorted).astype(float)
    risks = np.cumsum(errors) / np.arange(1, n + 1)
    aurc = float(np.trapezoid(risks, coverages))
    return AbstentionPolicy(
        confidence_threshold=threshold,
        target_coverage=target_coverage,
        achieved_coverage=n_covered / n if n else 0.0,
        selective_risk_at_threshold=selective_risk,
        aurc=aurc,
        n_abstained=n - n_covered,
        n_total=n,
    )


def _policy_dict(p) -> dict:
    return {
        "confidence_threshold": round(p.confidence_threshold, 4),
        "target_coverage": p.target_coverage,
        "achieved_coverage": round(p.achieved_coverage, 4),
        "selective_risk": round(p.selective_risk_at_threshold, 4),
        "n_abstained": p.n_abstained,
        "n_total": p.n_total,
        "aurc": round(p.aurc, 4),
    }


def _conclusion(metrics, source):
    ts = metrics["temperature_scaling"]
    te = metrics["test_evaluation_90pct"]

    lines = [
        "## E12 Calibration & Abstention Results", "",
        f"**Data source:** {source}", "",
        "### Temperature Scaling", "",
        f"- Fitted T = **{ts['fitted_temperature']}**"
        + (" (lower search bound — in-space rows are near-perfectly"
           " predicted, so NLL keeps falling as T→0)" if ts['fitted_temperature'] <= 0.05 else ""),
        (f"- ECE (full test set): {ts['ece_before']} -> "
         f"**{ts['ece_after']}** (delta {ts['ece_improvement']:+.4f})"),
        (f"- ECE (in label space, {ts['n_test_inspace']}/{ts['n_test_total']} rows): "
         f"{ts['ece_before_inspace']} -> **{ts['ece_after_inspace']}**"),
        f"- Macro-F1: {ts['f1_before']} → **{ts['f1_after']}**",
        f"- Brier (multiclass): **{ts['brier_multiclass']}**", "",
        "### Abstention (tuned on calibration, evaluated on test @ 90% coverage)", "",
        f"- Confidence threshold: **{te['confidence_threshold']}**",
        f"- Achieved coverage: **{te['achieved_coverage']}**",
        f"- Selective risk (error on non-abstained): **{te['selective_risk']}**",
        f"- AURC: **{te['aurc']}** (lower = better)", "",
        "### Interpretation", "",
        "- In-space ECE is the temperature-scaling verdict: it isolates",
        "  calibration quality from grouped-fold open-set rows (test classes",
        "  the training fold never saw cannot be calibrated by any T).",
        "- Full-set ECE also counts those open-set rows and is reported for",
        "  completeness; expect it to stay above the in-space figure.",
        "- In-space ECE after calibration should be < 0.05 for well-calibrated",
        "  models.",
        "- Selective risk at 90% coverage should be LOWER than full-coverage risk",
        "  (abstention is working if it removes hard/wrong predictions).",
        "- The confidence threshold becomes a production parameter: any prediction",
        f"  below {te['confidence_threshold']} gets INSUFFICIENT_EVIDENCE status.",
        "- AURC summarizes the risk-coverage tradeoff in one number.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["synthetic", "real"], default="synthetic")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--n-days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=SPLIT_SEED)
    args = ap.parse_args()

    if args.source == "synthetic":
        df = generate_synthetic_dataset(n_days=args.n_days, seed=args.seed)
        source = "synthetic"
    else:
        if not args.csv:
            raise SystemExit("--csv required for --source real")
        from app.research.dataset import load_real_dataset
        df = load_real_dataset(args.csv)
        source = f"real:{args.csv}"

    ds_manifest = create_dataset_manifest(df, source, DATASET_SCHEMA_VERSION)
    run_experiment(
        experiment_id="E12_calibration",
        hypothesis="Does temperature scaling improve calibration, and does abstention reduce selective risk?",
        dataset_manifest=ds_manifest,
        split_manifest={"split_method": "three_way_facility_grouped"},
        config={"source": source, "n_days": args.n_days, "seed": args.seed},
        experiment_fn=lambda: run_calibration_experiment(df, source, args.seed),
    )


if __name__ == "__main__":
    main()