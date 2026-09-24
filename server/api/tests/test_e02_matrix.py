"""Smoke test: the E02 matrix runs end-to-end on tiny synthetic data."""
from app.research.dataset import generate_synthetic_dataset
from app.research.e02_normality_matrix import run_matrix


def test_matrix_runs_and_produces_ladder():
    df = generate_synthetic_dataset(n_days=30, seed=11)
    metrics, preds, conclusion = run_matrix(df, "synthetic", "temporal", seed=11)

    rungs = [r["rung"] for r in metrics["ladder"]]
    assert rungs == ["A_firms", "B_context", "C_persistence", "D_normality",
                     "E_spatial", "F_temporal", "G_topology", "H_environment"]
    # Baselines sane, every rung scored, verdicts assigned
    for r in metrics["ladder"]:
        assert 0.0 <= r["source_macro_f1"] <= 1.0
        assert r["verdict"] in ("baseline", "PROMOTE", "DROP", "KEEP (neutral)",
                                "DROP (kill test)")
    assert metrics["rule_detector"]["test_f1"] >= 0.0
    assert len(preds) > 0
    assert "SYNTHETIC" in conclusion or "synthetic" in conclusion


def test_anomaly_type_breakdown_present():
    df = generate_synthetic_dataset(n_days=30, seed=11)
    metrics, _, _ = run_matrix(df, "synthetic", "temporal", seed=11)
    breakdown = metrics["anomaly_type_breakdown"]
    # Generator now tags anomaly_type; both types should be reported
    assert "intensity_spike" in breakdown
    assert "displaced_source" in breakdown
    assert breakdown["intensity_spike"]["support"] > 0


def test_topology_change_frozen_api():
    """G-rung kill-test dataclass exists and reports zeros on empty state."""
    import numpy as np
    import pandas as pd

    from app.ml.normal_state import build_facility_normal_state
    from app.research.topology import topology_change

    rng = np.random.default_rng(3)
    rows = [{
        "latitude": 22.47 + rng.normal(0, 0.002),
        "longitude": 70.07 + rng.normal(0, 0.002),
        "frp": float(np.exp(rng.normal(3.4, 0.4))),
        "observed_at": d,
    } for d in pd.date_range("2026-06-01", periods=40, freq="D", tz="UTC")]
    state = build_facility_normal_state(pd.DataFrame(rows), "F-001", "refinery")
    assert state.sufficient
    ch = topology_change(state, [])
    assert ch.n_new_zones == 0
    assert not ch.changed
