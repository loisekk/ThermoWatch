"""Gate smoke tests: E11 LOFO (G6) and E13 degradation (G7) run end-to-end
on tiny synthetic data and produce scored, structured results."""
from app.research.dataset import generate_synthetic_dataset
from app.research.e11_lofo import run_lofo
from app.research.e13_robustness import run_degradation


def test_lofo_runs():
    df = generate_synthetic_dataset(n_days=60, seed=11)
    metrics, preds, conclusion = run_lofo(df, "synthetic", seed=11)

    assert metrics["experiment"] == "E11_leave_one_facility_out"
    agg = metrics["aggregate"]
    assert agg["n_folds"] >= 1
    assert 0.0 <= agg["mean_accuracy"] <= 1.0
    assert 0.0 <= agg["mean_macro_f1"] <= 1.0
    assert 0.0 <= agg["facility_type_identification_rate"] <= 1.0
    # Per-facility rows carry the held-out id and a bounded accuracy
    for f in metrics["per_facility"]:
        assert f["facility_id"]
        assert 0.0 <= f["accuracy"] <= 1.0
        assert f["n_test_obs"] >= 5
    if preds is not None:
        assert len(preds) > 0
        assert {"observation_id", "y_pred", "held_out_facility"} <= set(preds.columns)
    assert "LOFO" in conclusion


def test_degradation_runs():
    df = generate_synthetic_dataset(n_days=60, seed=11)
    metrics, preds, conclusion = run_degradation(df, "synthetic", seed=11)

    assert metrics["experiment"] == "E13_robustness"
    scenarios = metrics["scenarios"]
    expected = {"full_features", "no_frp", "no_brightness",
                "no_facility_context", "sparse_50pct_obs", "thermal_only"}
    assert expected == set(scenarios)
    for name, sc in scenarios.items():
        assert 0.0 <= sc["macro_f1"] <= 1.0, name
    # Degradation deltas reported for every non-baseline scenario
    for name in expected - {"full_features"}:
        assert scenarios[name]["degradation_vs_full"] is not None
    assert isinstance(metrics["graceful_degradation_pass"], bool)
    assert preds is not None and len(preds) > 0
    assert {"y_pred", "scenario"} <= set(preds.columns)
    assert "E13" in conclusion