"""CLI trainer.
  python -m app.ml.train --source synthetic --samples 4000
  python -m app.ml.train --archive path/to/firms_archive.csv
Writes models/model_bundle.joblib + models/eval_report.json (locked schema).
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

from app.ml import dataset
from app.ml.ensemble import ProbAverageEnsemble, build_members
from app.ml.features import CLASSES, FEATURE_ORDER

MODELS_DIR = Path(__file__).resolve().parent / "models"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["synthetic", "archive"], default="synthetic")
    ap.add_argument("--archive", type=str, default="")
    ap.add_argument("--samples", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=str, default=str(MODELS_DIR))
    args = ap.parse_args()

    if args.source == "archive":
        X, y, provenance = dataset.build_from_archive(args.archive)
    else:
        X, y, provenance = dataset.build_synthetic(args.samples, args.seed)
    assert len(set(y)) == len(CLASSES), "training set must cover all 10 classes"

    tr, va, te = dataset.split_stratified(X, y, seed=args.seed)
    Xtr, ytr = np.array(X)[tr], np.array(y)[tr]
    Xva = np.array(X)[va]  # validation split: sanity check only (no early stopping in the ensemble)
    Xte, yte = np.array(X)[te], np.array(y)[te]

    model = ProbAverageEnsemble(build_members(len(CLASSES))).fit(Xtr, ytr)
    _ = model.predict_proba(Xva)

    probs = model.predict_proba(Xte)
    pred = probs.argmax(axis=1)
    labels = [int(c) for c in model.classes_]
    names = [CLASSES[i] for i in labels]
    # sklearn's stubs mistype zero_division (int 0 is valid at runtime) and the
    # unaveraged return shape (arrays, not scalars) — normalise via np.asarray.
    prfs = precision_recall_fscore_support(yte, pred, labels=labels, average=None, zero_division=0)  # pyright: ignore[reportArgumentType]
    p, r, f1, support = (np.asarray(m, dtype=float) for m in prfs)
    per_class = {names[i]: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                            "f1": round(float(f1[i]), 4), "support": int(support[i])} for i in range(len(labels))}

    t: list[float] = []
    for row in Xte[:100]:
        t0 = time.perf_counter()
        model.predict_proba(row.reshape(1, -1))
        t.append((time.perf_counter() - t0) * 1000)

    report = {
        "model": "tw-ensemble-v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": None,
        "dataset": {"source": provenance.get("mode", args.source), "n_samples": len(y),
                    "label_provenance": {k: v for k, v in provenance.items() if k != "mode"},
                    "class_counts": dataset.class_counts(y)},
        "split": {"train": len(tr), "val": len(va), "test": len(te), "stratified": True},
        "metrics": {
            "macro_f1": round(float(f1_score(yte, pred, labels=labels, average="macro", zero_division=0)), 4),  # pyright: ignore[reportArgumentType]
            "weighted_f1": round(float(f1_score(yte, pred, labels=labels, average="weighted", zero_division=0)), 4),  # pyright: ignore[reportArgumentType]
            "per_class": per_class,
        },
        "confusion_matrix": {"labels": names, "matrix": confusion_matrix(yte, pred, labels=labels).tolist()},
        "inference_ms_p50": round(float(sorted(t)[len(t) // 2]), 2),
        "limitations": [
            "Proxy labels: OSM tag proximity / synthetic signatures — not on-site or media verified",
            "Synthetic data reproduces documented thermal signatures; train on real FIRMS archive before operational use",
            "FIRMS misses fires below ~375 m² (sensor limit) — recall ceiling, not model failure",
            "Cloud-cover observation gaps not modelled",
            "UI 4-class view is a documented projection of this 10-way posterior (see /model/card)",
            "MODIS->VIIRS transfer untested: feature signatures are sensor-agnostic by design, but cross-sensor calibration is not yet validated",
        ],
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"version": "tw-ensemble-v1", "ensemble": model,
                 "feature_order": FEATURE_ORDER, "classes": names}, out / "model_bundle.joblib")
    (out / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[train] macro_f1={report['metrics']['macro_f1']} weighted_f1={report['metrics']['weighted_f1']} "
          f"test_n={len(te)} p50={report['inference_ms_p50']}ms -> {out}")
    for name, m in per_class.items():
        print(f"  {name:<20} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} n={m['support']}")


if __name__ == "__main__":
    main()
