"""CLI trainer for the tw-multimodal-v2 (47-feature) contract.

  python -m app.ml.train_multimodal --samples 4000
  python -m app.ml.train_multimodal --samples 10000 --cv 5

Writes models/model_multimodal.joblib + models/eval_report_multimodal.json.
The serving v1 bundle (model_bundle.joblib / eval_report.json) is NOT touched;
inference.py keeps serving v1 until the v2 report is reviewed and adopted.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support

from app.ml import dataset_multimodal as ds
from app.ml.classifier import DEFAULT_BUNDLE, MultiModalClassifier
from app.ml.dataset import split_stratified
from app.ml.features import CLASSES, FEATURE_REGISTRY, MULTIMODAL_FEATURE_ORDER


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cv", type=int, default=5)
    ap.add_argument("--out", type=str, default=str(DEFAULT_BUNDLE.parent))
    args = ap.parse_args()

    X, y, provenance = ds.build_synthetic_multimodal(args.samples, args.seed)
    assert len(set(y)) == len(CLASSES), "training set must cover all 10 classes"
    tr, va, te = split_stratified(X, y, seed=args.seed)
    Xtr, ytr = np.array(X)[tr], np.array(y)[tr]
    Xte, yte = np.array(X)[te], np.array(y)[te]

    clf = MultiModalClassifier(model_path=Path(args.out) / "model_multimodal.joblib")
    headline = clf.train(Xtr, ytr, MULTIMODAL_FEATURE_ORDER, cv=args.cv)

    proba = clf.predict_proba(Xte)
    pred = proba.argmax(axis=1)
    labels = list(range(len(CLASSES)))
    names = [CLASSES[i] for i in labels]
    # sklearn stubs mistype zero_division (int valid at runtime) and the unaveraged
    # return shape - normalise via np.asarray as in the v1 trainer.
    prfs = precision_recall_fscore_support(yte, pred, labels=labels, average=None, zero_division=0)  # pyright: ignore[reportArgumentType]
    p, r, f1, support = (np.asarray(m, dtype=float) for m in prfs)
    per_class = {names[i]: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                            "f1": round(float(f1[i]), 4), "support": int(support[i])}
                 for i in range(len(labels))}

    t: list[float] = []
    for row in Xte[:100]:
        t0 = time.perf_counter()
        clf.predict_proba(row.reshape(1, -1))
        t.append((time.perf_counter() - t0) * 1000)

    report = {
        "model": MultiModalClassifier.VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": None,
        "dataset": {"source": provenance.get("mode", "synthetic-multimodal"),
                    "n_samples": len(y),
                    "label_provenance": {k: v for k, v in provenance.items() if k not in ("mode",)},
                    "class_counts": ds.class_counts(y)},
        "split": {"train": len(tr), "val": len(va), "test": len(te), "stratified": True},
        "metrics": {
            "macro_f1": round(float(f1_score(yte, pred, labels=labels, average="macro", zero_division=0)), 4),  # pyright: ignore[reportArgumentType]
            "weighted_f1": round(float(f1_score(yte, pred, labels=labels, average="weighted", zero_division=0)), 4),  # pyright: ignore[reportArgumentType]
            "per_class": per_class,
            "cv_f1_macro_mean": headline["cv_f1_macro_mean"],
            "cv_f1_macro_std": headline["cv_f1_macro_std"],
        },
        "features": {
            "count": len(MULTIMODAL_FEATURE_ORDER),
            "order": MULTIMODAL_FEATURE_ORDER,
            "registry_versions": sorted({str(m.version.value) for m in FEATURE_REGISTRY.values()}),
            "importance_top10": headline["feature_importance_top10"],
        },
        "confusion_matrix": {"labels": names, "matrix": confusion_matrix(yte, pred, labels=labels).tolist()},
        "inference_ms_p50": round(float(sorted(t)[len(t) // 2]), 2),
        "limitations": [
            "Proxy labels: synthetic multimodal signatures by construction - not on-site or media verified",
            "Train on a real FIRMS archive with live enrichment before operational use",
            "Weather context is Open-Meteo model data, not sensor observations; population is WorldPop raster (year-2020 baseline)",
            "Land-cover fractions are a facility-proximity PROXY for the ESA WorldCover raster - documented upgrade path",
            "FIRMS misses fires below ~375 m2 (sensor limit) - recall ceiling, not model failure",
            "Serving path still tw-ensemble-v1 until this report is reviewed and adopted behind a flag",
        ],
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"version": MultiModalClassifier.VERSION, "ensemble": clf.ensemble,
                 "scaler": clf.scaler, "feature_order": MULTIMODAL_FEATURE_ORDER,
                 "classes": names}, out / "model_multimodal.joblib")
    (out / "eval_report_multimodal.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[train-multimodal] macro_f1={report['metrics']['macro_f1']} "
          f"weighted_f1={report['metrics']['weighted_f1']} features={len(MULTIMODAL_FEATURE_ORDER)} "
          f"test_n={len(te)} p50={report['inference_ms_p50']}ms -> {out}")
    for name, m in per_class.items():
        print(f"  {name:<20} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} n={m['support']}")


if __name__ == "__main__":
    main()