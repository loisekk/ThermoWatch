"""E14: Data-efficiency — how much facility history is needed?

For each history length (7, 14, 21, 30, 45, 60, 90 days), train the
facility normal state on that much data and measure anomaly detection
performance. Determines cold-start requirements.

Usage:
    python -m app.research.e14_data_efficiency --n-days 120
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from app.ml.normal_state import build_facility_normal_state
from app.ml.residuals import intensity_residual
from app.research.config import DATASET_SCHEMA_VERSION, SPLIT_SEED
from app.research.dataset import create_dataset_manifest, generate_synthetic_dataset
from app.research.runner import run_experiment

HISTORY_LENGTHS = [7, 14, 21, 30, 45, 60, 90]


def run_data_efficiency(
    df: pd.DataFrame, source: str, seed: int,
) -> tuple[dict, pd.DataFrame, str]:
    """Measure anomaly detection performance vs. history length."""
    # Sort by time
    df_sorted = df.sort_values("observed_at").reset_index(drop=True)

    # Use last 30 days as "test" period; vary the amount of history before it
    dates = df_sorted["observed_at"].dt.date.unique()
    if len(dates) < 100:
        # Not enough data — use what we have
        test_start = dates[-30] if len(dates) >= 30 else dates[-len(dates) // 3]
    else:
        test_start = dates[-30]

    test_mask = df_sorted["observed_at"].dt.date >= test_start
    test_df = df_sorted[test_mask].copy()
    history_pool = df_sorted[~test_mask].copy()

    results = []
    predictions = []

    for hist_days in HISTORY_LENGTHS:
        # Take only the last `hist_days` days of history
        if len(dates) < hist_days + 30:
            continue  # not enough data for this history length

        # NOTE: test_start is a datetime.date (from .dt.date.unique());
        # date - Timedelta returns a date which has NO .date() method, so
        # normalize through pd.Timestamp before taking the date back.
        cutoff_date = (pd.Timestamp(test_start) - pd.Timedelta(days=hist_days)).date()
        hist_df = history_pool[history_pool["observed_at"].dt.date >= cutoff_date].copy()

        # Build facility states from this limited history — NORMAL rows only:
        # injected anomalies must never contaminate the baseline being scored.
        states = {}
        fac_obs = hist_df[hist_df["facility_id"] != ""]
        if "label_normality" in fac_obs.columns:
            fac_obs = fac_obs[fac_obs["label_normality"] == "normal"]
        for fid, group in fac_obs.groupby("facility_id"):
            states[str(fid)] = build_facility_normal_state(group, str(fid), "")

        # Score test observations using z-score rule
        y_true, y_pred, confidences = [], [], []
        test_facility = test_df[test_df["facility_id"] != ""]
        for _, row in test_facility.iterrows():
            st = states.get(str(row["facility_id"]))
            if st is None or not st.sufficient:
                y_pred.append(-1)  # abstain
                y_true.append(1 if row["label_normality"] == "abnormal" else 0)
                confidences.append(0.0)
                continue
            r = intensity_residual(
                row["frp"], st, hour=pd.Timestamp(row["observed_at"]).hour,
            )
            y_true.append(1 if row["label_normality"] == "abnormal" else 0)
            y_pred.append(1 if (r.z is not None and abs(r.z) > 3.5) else 0)
            confidences.append(min(abs(r.z or 0) / 5.0, 1.0))

        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        confidences = np.array(confidences)

        # Only score non-abstained
        mask = y_pred >= 0
        n_evaluable = int(mask.sum())
        n_abstain = int((~mask).sum())

        if n_evaluable > 0:
            f1 = f1_score(y_true[mask], y_pred[mask], zero_division=0)
            # false alerts: predicted abnormal among truly-normal evaluable obs
            n_normal = int((y_true[mask] == 0).sum())
            n_false = int(((y_true[mask] == 0) & (y_pred[mask] == 1)).sum())
            false_alert_rate = n_false / max(n_normal, 1)
        else:
            f1 = 0.0
            false_alert_rate = 1.0

        n_sufficient_states = sum(1 for s in states.values() if s.sufficient)

        results.append({
            "history_days": hist_days,
            "n_sufficient_facilities": n_sufficient_states,
            "n_total_facilities": len(states),
            "n_test_obs": len(test_facility),
            "n_evaluable": n_evaluable,
            "n_abstained": n_abstain,
            "abstain_rate": round(n_abstain / len(test_facility), 4) if len(test_facility) else 0,
            "anomaly_f1": round(float(f1), 4),
            "false_alert_rate": round(false_alert_rate, 4),
        })

        # Save predictions
        p = test_facility[["observation_id", "facility_id", "label_normality"]].copy()
        p["history_days"] = hist_days
        p["y_pred"] = np.where(y_pred == 1, "abnormal",
                               np.where(y_pred == 0, "normal", "abstain"))
        predictions.append(p)

    # Find minimum viable history (F1 > 0.5 and abstain rate < 0.5)
    min_viable = None
    for r in results:
        if r["anomaly_f1"] > 0.5 and r["abstain_rate"] < 0.5:
            min_viable = r["history_days"]
            break

    conclusion = _conclusion(results, min_viable, source)
    metrics = {
        "experiment": "E14_data_efficiency",
        "learning_curve": results,
        "minimum_viable_history_days": min_viable,
    }
    preds = (
        pd.concat(predictions, ignore_index=True)
        if predictions
        else pd.DataFrame(
            columns=[
                "observation_id",
                "facility_id",
                "label_normality",
                "history_days",
                "y_pred",
            ]
        )
    )
    return metrics, preds, conclusion


def _conclusion(results, min_viable, source):
    lines = [
        "## E14 Data-Efficiency Learning Curve", "",
        f"**Data source:** {source}", "",
        "| History (days) | Sufficient Facilities | Abstain Rate | Anomaly F1 | False-Alert Rate |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['history_days']} | {r['n_sufficient_facilities']}/{r['n_total_facilities']} "
            f"| {r['abstain_rate']} | {r['anomaly_f1']} | {r['false_alert_rate']} |")

    lines += [
        "", f"**Minimum viable history: {min_viable} days**" if min_viable
        else "**No minimum viable history found** — needs more data",
        "",
        "### Interpretation",
        "- Shorter history → more abstentions (facilities below MIN_OBS threshold).",
        "- The curve shows where performance saturates — more history stops helping.",
        "- Min viable = the cold-start waiting period before the system is useful",
        "  at a new facility.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=SPLIT_SEED)
    args = ap.parse_args()

    df = generate_synthetic_dataset(n_days=args.n_days, seed=args.seed)
    ds_manifest = create_dataset_manifest(df, "synthetic", DATASET_SCHEMA_VERSION)
    run_experiment(
        experiment_id="E14_data_efficiency",
        hypothesis="How much facility history is needed before anomaly detection works?",
        dataset_manifest=ds_manifest,
        split_manifest={"split_method": "temporal_rolling"},
        config={"source": "synthetic", "seed": args.seed, "history_lengths": HISTORY_LENGTHS},
        experiment_fn=lambda: run_data_efficiency(df, "synthetic", args.seed),
    )


if __name__ == "__main__":
    main()