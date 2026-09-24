"""Probability calibration and abstention via risk-coverage optimization.

Temperature scaling (Guo et al. 2017) for multiclass calibration, plus
conformal-inspired abstention thresholds tuned on held-out validation.
Pure functions — no DB, no I/O, fully deterministic.

References:
- Temperature scaling: https://arxiv.org/abs/1706.04599
- MAPIE (conformal prediction): https://mapie.readthedocs.io
- scikit-learn temperature scaling discussion: https://virchan.github.io/2025/
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar


@dataclass(frozen=True)
class CalibrationResult:
    """Fitted calibration parameters."""
    temperature: float
    method: str = "temperature_scaling"
    n_val: int = 0
    n_classes: int = 0


@dataclass(frozen=True)
class AbstentionPolicy:
    """Coverage-risk-tuned abstention threshold."""
    confidence_threshold: float
    target_coverage: float
    achieved_coverage: float
    selective_risk_at_threshold: float
    aurc: float  # Area Under Risk-Coverage curve (lower = better)
    n_abstained: int
    n_total: int


def fit_temperature_scaling(
    logits: np.ndarray, labels: np.ndarray, max_iter: int = 100,
) -> CalibrationResult:
    """Fit T on validation logits by minimizing NLL.

    Args:
        logits: (n_samples, n_classes) raw model logits (pre-softmax)
        labels: (n_samples,) integer class indices

    Returns:
        CalibrationResult with optimal temperature.
    """
    n_classes = logits.shape[1]
    if n_classes < 2:
        return CalibrationResult(temperature=1.0, n_val=len(labels), n_classes=n_classes)

    def nll_loss(T: float) -> float:
        scaled = logits / max(T, 1e-8)
        # log-softmax (numerically stable)
        shifted = scaled - scaled.max(axis=1, keepdims=True)
        log_probs = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
        return -float(log_probs[np.arange(len(labels)), labels].mean())

    result = minimize_scalar(
        nll_loss, bounds=(0.05, 20.0), method="bounded",
        options={"maxiter": max_iter},
    )
    return CalibrationResult(
        temperature=float(result.x),
        n_val=len(labels),
        n_classes=n_classes,
    )


def apply_temperature_scaling(
    logits: np.ndarray, temperature: float,
) -> np.ndarray:
    """Apply softmax(logits / T) — returns calibrated probabilities."""
    scaled = logits / max(temperature, 1e-8)
    shifted = scaled - scaled.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def tune_abstention_threshold(
    y_true: np.ndarray, y_pred: np.ndarray, confidence: np.ndarray,
    target_coverage: float = 0.90,
) -> AbstentionPolicy:
    """Find confidence threshold that achieves target coverage while
    minimizing selective risk.

    Selective risk = error rate on the non-abstained subset.
    Coverage = fraction of samples NOT abstained.
    """
    n = len(y_true)
    order = np.argsort(-confidence)  # highest confidence first
    y_sorted = y_true[order]
    pred_sorted = y_pred[order]
    conf_sorted = confidence[order]

    # Coverage at each rank: k/n for top-k most confident
    k_target = int(np.ceil(target_coverage * n))
    threshold = float(conf_sorted[k_target - 1]) if k_target > 0 else 1.0

    # Metrics at threshold
    mask = confidence >= threshold
    n_covered = mask.sum()
    n_abstained = n - n_covered
    if n_covered > 0:
        selective_risk = float((y_true[mask] != y_pred[mask]).mean())
    else:
        selective_risk = 1.0

    # AURC: integrate risk over all coverage levels
    coverages = np.arange(1, n + 1) / n
    risks = np.cumsum(y_sorted != pred_sorted) / np.arange(1, n + 1)
    aurc = float(np.trapezoid(risks, coverages))

    return AbstentionPolicy(
        confidence_threshold=threshold,
        target_coverage=target_coverage,
        achieved_coverage=n_covered / n if n > 0 else 0.0,
        selective_risk_at_threshold=selective_risk,
        aurc=aurc,
        n_abstained=n_abstained,
        n_total=n,
    )


def risk_coverage_curve(
    y_true: np.ndarray, y_pred: np.ndarray, confidence: np.ndarray,
    n_points: int = 20,
) -> list[dict]:
    """Full risk-coverage curve for plotting/reporting."""
    order = np.argsort(-confidence)
    y_s = y_true[order]
    p_s = y_pred[order]
    n = len(y_true)
    coverages = np.linspace(0.05, 1.0, n_points)
    curve = []
    for cov in coverages:
        k = max(1, int(n * cov))
        risk = float((y_s[:k] != p_s[:k]).mean())
        curve.append({"coverage": round(float(cov), 3), "selective_risk": round(risk, 4)})
    return curve


def expected_calibration_error(
    y_true: np.ndarray, y_proba: np.ndarray, n_bins: int = 10,
) -> float:
    """ECE after calibration (should decrease vs. pre-calibration)."""
    predictions = y_proba.argmax(axis=1)
    max_proba = y_proba.max(axis=1)
    correct = (predictions == y_true).astype(float)
    edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (max_proba > edges[i]) & (max_proba <= edges[i + 1])
        if mask.sum() == 0:
            continue
        ece += (mask.sum() / len(y_true)) * abs(
            correct[mask].mean() - max_proba[mask].mean()
        )
    return float(ece)