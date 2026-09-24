"""Evaluation metrics for ThermoWatch research experiments.

Reporting principles:
  - Always report class support alongside metrics
  - Event-level AND facility-level metrics
  - False alerts per facility-day (operational burden)
  - Risk-coverage for abstention evaluation
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_fscore_support,
)


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: list[str] | None = None,
) -> dict:
    """Comprehensive classification metrics with per-class support."""
    if labels is None:
        labels = sorted(set(y_true) | set(y_pred))

    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    precision_values = np.asarray(p)
    recall_values = np.asarray(r)
    f1_values = np.asarray(f1)
    support_values = np.asarray(
        support if support is not None else np.zeros(len(labels), dtype=int)
    )

    per_class = {
        label: {
            "precision": round(float(precision_values[i]), 4),
            "recall": round(float(recall_values[i]), 4),
            "f1": round(float(f1_values[i]), 4),
            "support": int(support_values[i]),
        }
        for i, label in enumerate(labels)
    }

    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)), 4),
        "mcc": round(float(matthews_corrcoef(y_true, y_pred)), 4) if len(set(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "confusion_labels": labels,
        "per_class": per_class,
        "low_support_classes": [
            label for label in per_class if per_class[label]["support"] < 20
        ],
    }


def facility_level_metrics(
    df: pd.DataFrame,
    y_pred: np.ndarray,
    label_col: str = "label_source_class",
) -> dict:
    """Aggregate predictions to facility level: majority vote per facility.

    This measures whether the system correctly characterizes a facility,
    not just individual observations.
    """
    temp = df[["facility_id"]].copy()
    temp["y_true"] = df[label_col].values
    temp["y_pred"] = y_pred

    # Only facility-attributed observations
    facility_obs = temp[temp["facility_id"] != ""]
    if facility_obs.empty:
        return {"n_facilities": 0, "facility_accuracy": None}

    # Majority vote per facility
    facility_votes = (
        facility_obs.groupby("facility_id")
        .agg(
            true_label=("y_true", lambda x: x.mode().iloc[0]),
            pred_label=("y_pred", lambda x: pd.Series(x).mode().iloc[0]),
            n_obs=("y_pred", "count"),
        )
    )
    correct = (facility_votes["true_label"] == facility_votes["pred_label"]).sum()

    return {
        "n_facilities": len(facility_votes),
        "facility_accuracy": round(float(correct / len(facility_votes)), 4),
        "misclassified": [
            {
                "facility_id": fid,
                "true": row["true_label"],
                "pred": row["pred_label"],
                "n_obs": int(row["n_obs"]),
            }
            for fid, row in facility_votes.iterrows()
            if row["true_label"] != row["pred_label"]
        ],
    }


def false_alerts_per_facility_day(
    df: pd.DataFrame,
    y_pred_normality: np.ndarray,
    normal_label: str = "normal",
) -> dict:
    """False alerts per facility-day — the operational burden metric.

    A false alert = predicting "abnormal" on a facility-day that is
    actually normal. This directly measures analyst workload.
    """
    temp = df[["facility_id", "observed_at"]].copy()
    temp["y_pred"] = y_pred_normality
    temp["y_true"] = df["label_normality"].values
    temp["date"] = temp["observed_at"].dt.date

    facility_obs = temp[temp["facility_id"] != ""]
    if facility_obs.empty:
        return {"false_alert_rate_per_facility_day": None, "n_facility_days": 0}

    # Aggregate to facility-day: abnormal if ANY observation that day is flagged
    fd = facility_obs.groupby(["facility_id", "date"]).agg(
        true_normality=("y_true", lambda x: "abnormal" if "abnormal" in x.values else "normal"),
        pred_normality=("y_pred", lambda x: "abnormal" if "abnormal" in x.values else "normal"),
    )

    true_normal_days = fd[fd["true_normality"] == normal_label]
    false_alerts = int((true_normal_days["pred_normality"] == "abnormal").sum())

    return {
        "n_facility_days": len(fd),
        "n_normal_facility_days": len(true_normal_days),
        "false_alerts": false_alerts,
        "false_alert_rate_per_facility_day": round(
            float(false_alerts / len(true_normal_days)) if len(true_normal_days) > 0 else 0.0, 4
        ),
    }


def risk_coverage_curve(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    confidence: np.ndarray,
    n_points: int = 20,
) -> dict:
    """Risk-coverage curve for abstention evaluation.

    Sort by confidence (descending), compute selective risk (error rate)
    at each coverage level. Lower risk at higher coverage = better.
    """
    order = np.argsort(-np.asarray(confidence))
    y_true_sorted = np.asarray(y_true)[order]
    y_pred_sorted = np.asarray(y_pred)[order]

    n = len(y_true_sorted)
    coverages = np.linspace(0.05, 1.0, n_points)
    curve = []
    for cov in coverages:
        k = max(1, int(n * cov))
        errors = int((y_true_sorted[:k] != y_pred_sorted[:k]).sum())
        curve.append({
            "coverage": round(float(cov), 3),
            "selective_risk": round(float(errors / k), 4),
        })

    # AURC (Area Under Risk-Coverage curve) — lower is better
    # np.trapz was removed in NumPy 2; use np.trapezoid
    aurc = np.trapezoid(
        [c["selective_risk"] for c in curve], [c["coverage"] for c in curve]
    )

    return {
        "curve": curve,
        "aurc": round(float(aurc), 4),
        "risk_at_full_coverage": curve[-1]["selective_risk"],
        "risk_at_80pct_coverage": curve[int(0.8 * (n_points - 1))]["selective_risk"],
    }


def calibration_metrics(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """ECE (Expected Calibration Error) and Brier score."""
    n_classes = y_proba.shape[1] if y_proba.ndim > 1 else 2
    predictions = y_proba.argmax(axis=1) if y_proba.ndim > 1 else (y_proba > 0.5).astype(int)
    max_proba = y_proba.max(axis=1) if y_proba.ndim > 1 else np.maximum(y_proba, 1 - y_proba)
    correct = (predictions == y_true).astype(float)

    # ECE
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (max_proba > lo) & (max_proba <= hi)
        if mask.sum() == 0:
            continue
        bin_acc = correct[mask].mean()
        bin_conf = max_proba[mask].mean()
        ece += (mask.sum() / len(y_true)) * abs(bin_acc - bin_conf)

    # Multiclass Brier
    onehot = np.zeros_like(y_proba)
    for i, yt in enumerate(y_true):
        if 0 <= yt < n_classes:
            onehot[i, yt] = 1.0
    brier = float(np.mean(np.sum((y_proba - onehot) ** 2, axis=1)))

    return {
        "ece": round(float(ece), 4),
        "brier_multiclass": round(brier, 4),
        "mean_max_probability": round(float(max_proba.mean()), 4),
        "n_bins": n_bins,
    }

