"""E1: Simple Baseline Benchmark (B0-B4).

Establishes the performance floor before any facility-normality modeling.
No new method may be accepted without comparison against these baselines.

Usage:
    cd server/api
    python -m app.research.e01_baselines --source synthetic
"""
from __future__ import annotations

import argparse

import pandas as pd

from app.research.baselines import (
    extract_b0_features,
    extract_b1_features,
    extract_b2_features,
    extract_b3_features,
    get_facility_coords,
    run_b4_statistical_anomaly,
    run_baseline,
)
from app.research.config import (
    DATASET_SCHEMA_VERSION,
    FACILITY_SPLIT_TEST_SIZE,
    SPLIT_SEED,
)
from app.research.dataset import (
    create_dataset_manifest,
    generate_synthetic_dataset,
    load_real_dataset,
)
from app.research.runner import run_experiment
from app.research.splits import (
    facility_grouped_split,
    geographic_split,
    temporal_split_with_abnormal_support,
)


def run_e1(
    df: pd.DataFrame,
    source: str,
    split_method: str = "facility_grouped",
    test_size: float = FACILITY_SPLIT_TEST_SIZE,
    seed: int = SPLIT_SEED,
) -> tuple[dict, pd.DataFrame, str]:
    """Run all baselines B0-B4 and produce comparison."""
    # --- Split ---
    if split_method == "facility_grouped":
        train_idx, test_idx, split_manifest = facility_grouped_split(df, test_size, seed)
    elif split_method == "geographic":
        train_idx, test_idx, split_manifest = geographic_split(df)
    else:
        # Temporal = the A5 frame: assert abnormal support in the future
        # window (shifting the cutoff earlier if the default lands before
        # the injected spikes) so anomaly-task P/R is computable there.
        train_idx, test_idx, split_manifest = temporal_split_with_abnormal_support(df)

    train_df = df.loc[train_idx].copy()
    test_df = df.loc[test_idx].copy()

    y_train = train_df["label_source_class"].astype("object").to_numpy()
    y_test = test_df["label_source_class"].astype("object").to_numpy()

    print(f"  Split: {split_manifest['split_method']}")
    print(f"  Train: {len(train_df)} obs, {train_df['facility_id'].nunique()} facilities")
    print(f"  Test:  {len(test_df)} obs, {test_df['facility_id'].nunique()} facilities")
    print(f"  Overlap check: {split_manifest.get('overlap_check', 'N/A')}")

    facility_coords = get_facility_coords()
    results: dict = {}
    all_predictions = []

    print("\n  Running B0 (FIRMS features only)...")
    results["B0_firms_only"] = run_baseline(
        "B0_firms_only",
        extract_b0_features(train_df), y_train,
        extract_b0_features(test_df), y_test, train_df, test_df,
    )
    all_predictions.append(_save_predictions(test_df, results["B0_firms_only"], "B0"))

    print("  Running B1 (+ facility proximity/context)...")
    results["B1_firms_context"] = run_baseline(
        "B1_firms_context",
        extract_b1_features(train_df, facility_coords), y_train,
        extract_b1_features(test_df, facility_coords), y_test, train_df, test_df,
    )
    all_predictions.append(_save_predictions(test_df, results["B1_firms_context"], "B1"))

    print("  Running B2 (+ persistence/history)...")
    results["B2_firms_persistence"] = run_baseline(
        "B2_firms_persistence",
        extract_b2_features(train_df), y_train,
        extract_b2_features(test_df), y_test, train_df, test_df,
    )
    all_predictions.append(_save_predictions(test_df, results["B2_firms_persistence"], "B2"))

    print("  Running B3 (all features combined)...")
    results["B3_combined"] = run_baseline(
        "B3_combined",
        extract_b3_features(train_df, facility_coords), y_train,
        extract_b3_features(test_df, facility_coords), y_test, train_df, test_df,
    )
    all_predictions.append(_save_predictions(test_df, results["B3_combined"], "B3"))

    print("  Running B4 (facility z-score anomaly)...")
    results["B4_statistical"] = run_b4_statistical_anomaly(train_df, test_df)

    comparison = _comparison_table(results)
    anomaly_task = _anomaly_task_report(split_manifest, results)
    conclusion = _generate_conclusion(results, comparison, source, anomaly_task)

    predictions_df = (
        pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()
    )

    metrics = {
        "experiment": "E01_baselines",
        "split_manifest_summary": {
            "method": split_manifest["split_method"],
            "split_id": split_manifest.get("split_id"),
            "n_train": split_manifest["n_train_observations"],
            "n_test": split_manifest["n_test_observations"],
        },
        "comparison_table": comparison,
        "results": results,
        "anomaly_task_future_window": anomaly_task,
    }
    return metrics, predictions_df, conclusion


def _save_predictions(test_df, result, baseline_name):
    """Extract per-observation predictions metadata for the failure gallery."""
    pred_df = test_df[["observation_id", "facility_id", "label_source_class"]].copy()
    pred_df["baseline"] = baseline_name
    pred_df["macro_f1_of_baseline"] = result["classification"]["macro_f1"]
    return pred_df


def _comparison_table(results):
    rows = []
    for name, r in results.items():
        if "classification" in r:
            rows.append({
                "baseline": name,
                "n_features": r.get("n_features", "-"),
                "macro_f1": r["classification"]["macro_f1"],
                "weighted_f1": r["classification"]["weighted_f1"],
                "accuracy": r["classification"]["accuracy"],
                "mcc": r["classification"]["mcc"],
                "facility_acc": r["facility_level"].get("facility_accuracy"),
                "ece": r["calibration"]["ece"],
                "aurc": r["risk_coverage"]["aurc"],
            })
        elif "abnormal_f1" in r:
            rows.append({
                "baseline": name,
                "n_features": "-",
                "macro_f1": None, "weighted_f1": None, "accuracy": None,
                "mcc": None, "facility_acc": None, "ece": None, "aurc": None,
                "abnormal_f1": r["abnormal_f1"],
                "false_alert_rate": r["false_alert_metrics"].get("false_alert_rate_per_facility_day"),
            })
    return rows


def _anomaly_task_report(split_manifest: dict, results: dict) -> dict | None:
    """Anomaly task on the FUTURE window (the A5 frame).

    Precision/recall are reported where negatives (normal rows) actually
    exist — normal vs abnormal in the held-out future window — together with
    the abnormal-support assertion. Source-classification precision on a
    detections-only window has no negatives and is never quoted instead.
    """
    check = split_manifest.get("abnormal_support_check")
    if check is None:
        return None
    b4 = results.get("B4_statistical", {}) or {}
    fa = b4.get("false_alert_metrics") or {}
    return {
        "window": "future (test) window, normal vs abnormal",
        "abnormal_test_rows": split_manifest.get("abnormal_test_rows"),
        "abnormal_support_required": split_manifest.get(
            "abnormal_support_required"),
        "abnormal_support_check": check,
        "abnormal_support_shifted": split_manifest.get("abnormal_support_shifted"),
        "b4_precision": b4.get("abnormal_precision"),
        "b4_recall": b4.get("abnormal_recall"),
        "b4_f1": b4.get("abnormal_f1"),
        "b4_false_alerts_per_facility_day": fa.get(
            "false_alert_rate_per_facility_day"),
        "b4_n_evaluable": b4.get("n_evaluable"),
        "note": ("B4 facility z-score on the future window; "
                 "source-classification precision is undefined on a "
                 "detections-only window and is NOT quoted here."),
    }


def _generate_conclusion(results, comparison, source, anomaly_task=None):
    b0_f1 = results.get("B0_firms_only", {}).get("classification", {}).get("macro_f1")
    b1_f1 = results.get("B1_firms_context", {}).get("classification", {}).get("macro_f1")
    b3_f1 = results.get("B3_combined", {}).get("classification", {}).get("macro_f1")
    b4 = results.get("B4_statistical", {})

    lines = [
        "## E1 Baseline Benchmark Results",
        "",
        f"**Data source:** {source}",
        "",
        "### Key Findings",
        "",
    ]

    if b0_f1 is not None and b1_f1 is not None:
        context_gain = (b1_f1 - b0_f1) * 100
        lines.append(f"- B0 (FIRMS only): macro-F1 = **{b0_f1}**")
        lines.append(f"- B1 (+ context): macro-F1 = **{b1_f1}** (delta = {context_gain:+.1f} pts)")
    if b3_f1 is not None:
        lines.append(f"- B3 (all combined): macro-F1 = **{b3_f1}**")

    if "abnormal_f1" in b4:
        lines.append(
            f"- B4 (anomaly z-score): abnormal F1 = **{b4['abnormal_f1']}**, "
            f"false-alert rate = {b4['false_alert_metrics'].get('false_alert_rate_per_facility_day')}"
        )

    if anomaly_task:
        at = anomaly_task
        shift = (
            " (cutoff shifted earlier to guarantee support — recorded in the "
            "split manifest)" if at.get("abnormal_support_shifted") else ""
        )
        lines += [
            "",
            "### Anomaly task — future window (A5 frame)",
            "",
            f"- Abnormal rows in the test window: {at['abnormal_test_rows']} "
            f"(required >= {at['abnormal_support_required']}) — "
            f"**{at['abnormal_support_check']}**{shift}",
            f"- B4 facility z-score: precision={at['b4_precision']}, "
            f"recall={at['b4_recall']}, F1={at['b4_f1']}, "
            f"false alerts/facility-day="
            f"{at['b4_false_alerts_per_facility_day']} "
            f"(n_evaluable={at['b4_n_evaluable']})",
            "- Source-classification precision on this window is undefined "
            "(detections-only window, no source negatives) and is NOT quoted.",
        ]
        if at["abnormal_support_check"] != "PASS":
            lines.append(
                "- **SUPPORT FAIL** — recorded, never estimated: the dataset "
                "does not carry enough abnormal rows after the cut.")

    lines += [
        "",
        "### Interpretation",
        "",
        "- B0 establishes the floor: thermal features alone are insufficient for reliable classification.",
        "- B1-B3 quantify how much context/persistence adds — this is the gap the facility-normality model must exceed.",
        "- B4 establishes the anomaly-detection baseline using simple per-facility statistics.",
        "",
        "### Decision",
        "",
        "- These baselines are **frozen** — all future experiments (E2+) must compare against them.",
        "- Any proposed method that does not beat B3 on classification or B4 on anomaly detection is **dropped**.",
        "",
        "Note: " + ("Results are on SYNTHETIC data — harness validation only, not real-world performance claims."
                    if source == "synthetic" else "Results are on real FIRMS data with proxy labels — not ground truth."),
    ]
    return "\n".join(lines)


# =====================================================================
# Main
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="E1: Baseline benchmark")
    parser.add_argument("--source", choices=["synthetic", "real"], default="synthetic")
    parser.add_argument("--csv", help="Path to FIRMS archive CSV")
    parser.add_argument("--n-days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=SPLIT_SEED)
    parser.add_argument("--split", choices=["facility_grouped", "temporal",
                                            "geographic"],
                        default="facility_grouped")
    args = parser.parse_args()

    if args.source == "synthetic":
        print("  [WARN] SYNTHETIC data — harness validation only")
        df = generate_synthetic_dataset(n_days=args.n_days, seed=args.seed)
        source = "synthetic"
    else:
        if not args.csv:
            raise SystemExit("--csv required for --source real")
        df = load_real_dataset(args.csv)
        source = f"real:{args.csv}"

    ds_manifest = create_dataset_manifest(df, source=source, version=DATASET_SCHEMA_VERSION)
    config = {
        "source": source,
        "split_method": args.split,
        "test_size": FACILITY_SPLIT_TEST_SIZE,
        "seed": args.seed,
        "baselines": ["B0", "B1", "B2", "B3", "B4"],
    }

    run_experiment(
        experiment_id="E01_baselines",
        hypothesis=(
            "Establish performance floor: FIRMS-only vs +context vs +persistence vs combined, "
            "plus facility z-score anomaly baseline"
        ),
        dataset_manifest=ds_manifest,
        split_manifest={"split_method": args.split, "seed": args.seed},
        config=config,
        experiment_fn=lambda: run_e1(df, source, args.split, FACILITY_SPLIT_TEST_SIZE, args.seed),
    )


if __name__ == "__main__":
    main()

