"""E11: Generalization to unseen facilities via Leave-One-Facility-Out.

For each facility: train on all others, test on that one.
Reports per-facility and aggregate performance. This is the harshest
generalization test — the model must work at facilities it has NEVER seen.

Usage:
    python -m app.research.e11_lofo --n-days 120
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from app.research.baselines import extract_b1_features, get_facility_coords
from app.research.config import (DATASET_SCHEMA_VERSION, MODEL_SEED,
                                 SOURCE_CLASSES, SPLIT_SEED)
from app.research.dataset import create_dataset_manifest, generate_synthetic_dataset
from app.research.metrics import classification_metrics
from app.research.runner import run_experiment
from app.research.splits import leave_one_facility_out

CLASS_TO_IDX = {c: i for i, c in enumerate(SOURCE_CLASSES)}


def run_lofo(df: pd.DataFrame, source: str, seed: int) -> tuple[dict, pd.DataFrame | None, str]:
    """Run LOFO cross-validation with facility-grouped folds."""
    folds = leave_one_facility_out(df)
    facility_coords = get_facility_coords()

    per_facility = []
    all_predictions = []
    y_true_all, y_pred_all = [], []

    for held_out, train_idx, test_idx, _fold_manifest in folds:
        train_df = df.loc[train_idx].copy()
        test_df = df.loc[test_idx].copy()

        if len(test_df) < 5:
            continue

        # Features: B1 (FIRMS + facility context) — our best baseline from Phase 1
        X_train = extract_b1_features(train_df, facility_coords)
        X_test = extract_b1_features(test_df, facility_coords)

        y_train = train_df["label_source_class"].map(CLASS_TO_IDX).to_numpy()
        y_test_true = test_df["label_source_class"]

        # Train RF on train fold
        rf = RandomForestClassifier(
            n_estimators=300, max_depth=12, min_samples_leaf=5,
            max_features="sqrt", class_weight="balanced_subsample",
            random_state=MODEL_SEED, n_jobs=-1)
        rf.fit(X_train.to_numpy(dtype=float), y_train)

        # Predict on held-out facility
        pred_codes = rf.predict(X_test.to_numpy(dtype=float))
        y_pred = [SOURCE_CLASSES[int(c)] if int(c) < len(SOURCE_CLASSES)
                  else "unknown" for c in pred_codes]

        # Fixed-label-space scoring
        y_true_list = y_test_true.astype("object").tolist()
        y_pred_list = [str(p) for p in y_pred]

        from sklearn.metrics import accuracy_score, f1_score
        acc = accuracy_score(y_true_list, y_pred_list)
        f1_macro = f1_score(y_true_list, y_pred_list, labels=SOURCE_CLASSES,
                            average="macro", zero_division=0)

        # Facility-level: does the model correctly identify this facility's type?
        facility_type = test_df["facility_type"].iloc[0] if "facility_type" in test_df else ""
        majority_pred = pd.Series(y_pred).mode().iloc[0] if y_pred else "unknown"
        type_correct = majority_pred == facility_type

        per_facility.append({
            "facility_id": held_out,
            "facility_type": facility_type,
            "n_test_obs": len(test_df),
            "accuracy": round(float(acc), 4),
            "macro_f1": round(float(f1_macro), 4),
            "majority_prediction": majority_pred,
            "type_identified_correctly": type_correct,
        })

        y_true_all.extend(y_true_list)
        y_pred_all.extend(y_pred_list)

        # Save predictions
        pred_df = test_df[["observation_id", "facility_id", "label_source_class"]].copy()
        pred_df["y_pred"] = y_pred
        pred_df["held_out_facility"] = held_out
        all_predictions.append(pred_df)

    # Aggregate
    if per_facility:
        accs = [f["accuracy"] for f in per_facility]
        f1s = [f["macro_f1"] for f in per_facility]
        type_rate = sum(1 for f in per_facility if f["type_identified_correctly"]) / len(per_facility)
        aggregate = {
            "n_folds": len(per_facility),
            "mean_accuracy": round(float(np.mean(accs)), 4),
            "std_accuracy": round(float(np.std(accs)), 4),
            "min_accuracy": round(float(np.min(accs)), 4),
            "max_accuracy": round(float(np.max(accs)), 4),
            "mean_macro_f1": round(float(np.mean(f1s)), 4),
            "std_macro_f1": round(float(np.std(f1s)), 4),
            "facility_type_identification_rate": round(float(type_rate), 4),
        }
    else:
        aggregate = {"n_folds": 0, "error": "No valid folds"}

    # Overall metrics across all LOFO predictions
    overall = classification_metrics(
        np.array(y_true_all, dtype=object), np.array(y_pred_all, dtype=object),
        labels=SOURCE_CLASSES)

    # Per-type breakdown
    type_perf: dict = {}
    for f in per_facility:
        t = f["facility_type"]
        if t not in type_perf:
            type_perf[t] = {"accuracies": [], "type_correct": []}
        type_perf[t]["accuracies"].append(f["accuracy"])
        type_perf[t]["type_correct"].append(f["type_identified_correctly"])
    type_summary = {
        t: {
            "n_facilities": len(v["accuracies"]),
            "mean_accuracy": round(float(np.mean(v["accuracies"])), 4),
            "type_identification_rate": round(
                float(np.mean(v["type_correct"])), 4),
        }
        for t, v in type_perf.items()
    }

    # Conclusion
    conclusion = _generate_conclusion(aggregate, type_summary, source)

    metrics = {
        "experiment": "E11_leave_one_facility_out",
        "aggregate": aggregate,
        "overall_metrics": overall,
        "per_facility": per_facility,
        "per_type_summary": type_summary,
    }
    preds = (
        pd.concat(all_predictions, ignore_index=True)
        if all_predictions else None
    )
    return metrics, preds, conclusion


def _generate_conclusion(aggregate, type_summary, source):
    lines = [
        "## E11 Leave-One-Facility-Out Generalization", "",
        f"**Data source:** {source}", "",
        "### Aggregate Performance", "",
        f"- **Folds:** {aggregate.get('n_folds', 0)}",
        f"- **Mean Accuracy:** {aggregate.get('mean_accuracy', 'N/A')} ± {aggregate.get('std_accuracy', 'N/A')}",
        f"- **Mean Macro-F1:** {aggregate.get('mean_macro_f1', 'N/A')} ± {aggregate.get('std_macro_f1', 'N/A')}",
        f"- **Worst Facility:** {aggregate.get('min_accuracy', 'N/A')}",
        f"- **Facility Type ID Rate:** {aggregate.get('facility_type_identification_rate', 'N/A')}", "",
        "### Per-Type Breakdown", "",
        "| Type | Facilities | Mean Acc | Type ID Rate |",
        "|---|---|---|---|",
    ]
    for t, s in sorted(type_summary.items()):
        lines.append(
            f"| {t} | {s['n_facilities']} | {s['mean_accuracy']} | "
            f"{s['type_identification_rate']} |")

    lines += [
        "", "### Interpretation", "",
        "- LOFO is the harshest test: the model has NEVER seen this facility.",
        "- Low accuracy is expected and HONEST — it measures true generalization.",
        "- Facility Type ID Rate > 50% means the model recognizes the TYPE of facility",
        "  even at unseen locations (thermal signature transfer).",
        "- Compare with Phase 1 temporal split (same facility, future time) —",
        "  the gap between temporal and LOFO performance is the generalization cost.",
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
        experiment_id="E11_lofo",
        hypothesis="Does the model generalize to facilities it has never seen during training?",
        dataset_manifest=ds_manifest,
        split_manifest={"split_method": "leave_one_facility_out"},
        config={"source": source, "n_days": args.n_days, "seed": args.seed},
        experiment_fn=lambda: run_lofo(df, source, args.seed),
    )


if __name__ == "__main__":
    main()