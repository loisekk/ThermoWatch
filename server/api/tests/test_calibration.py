"""Phase 5 calibration tests — temperature scaling, abstention, ECE (E12)."""
import numpy as np

from app.ml.calibration import (
    apply_temperature_scaling,
    expected_calibration_error,
    fit_temperature_scaling,
    risk_coverage_curve,
    tune_abstention_threshold,
)


def _sample_labels(logits: np.ndarray, t_true: float, seed: int = 0):
    """Sample labels from softmax(logits / t_true) — the data-generating process."""
    rng = np.random.default_rng(seed)
    probs = np.exp(logits / t_true)
    probs /= probs.sum(axis=1, keepdims=True)
    labels = np.array([rng.choice(probs.shape[1], p=p) for p in probs])
    return labels


class TestTemperatureScaling:
    def test_recovers_true_temperature(self):
        rng = np.random.default_rng(1)
        logits = rng.normal(0, 3, size=(2000, 3))
        labels = _sample_labels(logits, t_true=4.0, seed=2)
        cal = fit_temperature_scaling(logits, labels)
        assert 2.5 < cal.temperature < 6.5  # recovers T_true ~= 4
        assert cal.n_val == 2000
        assert cal.n_classes == 3
        assert cal.method == "temperature_scaling"

    def test_single_class_returns_unity(self):
        logits = np.zeros((10, 1))
        cal = fit_temperature_scaling(logits, np.zeros(10, dtype=int))
        assert cal.temperature == 1.0

    def test_apply_scaling_rows_are_probabilities(self):
        rng = np.random.default_rng(3)
        logits = rng.normal(0, 5, size=(50, 4))
        probs = apply_temperature_scaling(logits, temperature=2.5)
        assert probs.shape == (50, 4)
        assert np.all(probs >= 0) and np.all(probs <= 1)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-9)

    def test_scaling_reduces_confidence_for_t_greater_than_1(self):
        logits = np.array([[4.0, 0.0, -1.0]])
        p1 = apply_temperature_scaling(logits, 1.0)
        p2 = apply_temperature_scaling(logits, 3.0)
        assert p2.max() < p1.max()

    def test_ece_decreases_after_calibration(self):
        rng = np.random.default_rng(0)
        logits = rng.normal(0, 3, size=(1500, 3))
        labels = _sample_labels(logits, t_true=4.0, seed=5)
        cal = fit_temperature_scaling(logits, labels)
        ece_before = expected_calibration_error(
            labels, apply_temperature_scaling(logits, 1.0))
        ece_after = expected_calibration_error(
            labels, apply_temperature_scaling(logits, cal.temperature))
        assert ece_after < ece_before


class TestAbstention:
    def _toy(self):
        # 90 correct samples with high confidence, 10 wrong with low confidence
        y_true = np.array([0] * 90 + [1] * 10)
        y_pred = np.array([0] * 100)  # last 10 are errors
        rng = np.random.default_rng(7)
        confidence = np.concatenate([
            rng.uniform(0.7, 1.0, size=90),
            rng.uniform(0.05, 0.3, size=10),
        ])
        return y_true, y_pred, confidence

    def test_tuned_threshold_hits_target_coverage(self):
        y_true, y_pred, confidence = self._toy()
        policy = tune_abstention_threshold(y_true, y_pred, confidence,
                                           target_coverage=0.90)
        assert policy.target_coverage == 0.90
        assert policy.achieved_coverage >= 0.90
        assert policy.n_abstained + (
            policy.n_total - policy.n_abstained) == policy.n_total
        assert policy.n_abstained <= 10
        # Low-confidence errors are the ones abstained -> zero selective risk
        assert policy.selective_risk_at_threshold == 0.0
        assert policy.aurc >= 0.0

    def test_abstention_wins_over_no_abstention(self):
        y_true, y_pred, confidence = self._toy()
        policy = tune_abstention_threshold(y_true, y_pred, confidence)
        overall_risk = float((y_true != y_pred).mean())
        assert policy.selective_risk_at_threshold <= overall_risk

    def test_risk_coverage_curve_shape_and_bounds(self):
        y_true, y_pred, confidence = self._toy()
        curve = risk_coverage_curve(y_true, y_pred, confidence, n_points=20)
        assert len(curve) == 20
        coverages = [c["coverage"] for c in curve]
        assert coverages == sorted(coverages)
        for c in curve:
            assert 0.0 <= c["selective_risk"] <= 1.0