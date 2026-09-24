"""Experiment runner — every experiment produces versioned artifacts.

Artifact structure:
    artifacts/{experiment_id}/{timestamp}/
        ├── MANIFEST.json       # experiment metadata + hashes
        ├── config.json         # frozen configuration
        ├── metrics.json        # all computed metrics
        ├── predictions.parquet # per-observation predictions (inspectable)
        └── conclusion.md       # human-readable summary
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.research.config import ARTIFACTS_DIR


def run_experiment(
    experiment_id: str,
    hypothesis: str,
    dataset_manifest: dict,
    split_manifest: dict,
    config: dict,
    experiment_fn: Callable[[], tuple[dict, pd.DataFrame | None, str]],
    artifacts_root: Path | None = None,
) -> Path:
    """Execute an experiment and save all artifacts.

    Args:
        experiment_id: e.g. "E01_baselines"
        hypothesis: what this experiment tests
        dataset_manifest: from dataset.create_dataset_manifest()
        split_manifest: from splits module
        config: frozen experiment configuration
        experiment_fn: callable returning (metrics_dict, predictions_df, conclusion_str)
        artifacts_root: override for the artifacts root (tests use this)

    Returns:
        Path to the artifact directory.
    """
    root = artifacts_root if artifacts_root is not None else ARTIFACTS_DIR
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    artifact_dir = root / experiment_id / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"  RUNNING: {experiment_id}")
    print(f"  Hypothesis: {hypothesis}")
    print(f"  Artifacts: {artifact_dir}")
    print(f"{'=' * 70}\n")

    # Execute the experiment
    metrics, predictions, conclusion = experiment_fn()

    # Save metrics
    (artifact_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )

    # Save predictions (for error inspection — failure gallery)
    if predictions is not None and len(predictions) > 0:
        predictions.to_parquet(artifact_dir / "predictions.parquet", index=False)

    # Save conclusion
    (artifact_dir / "conclusion.md").write_text(
        f"# {experiment_id}\n\n"
        f"**Hypothesis:** {hypothesis}\n\n"
        f"**Run:** {timestamp}\n\n"
        f"---\n\n{conclusion}\n",
        encoding="utf-8",
    )

    # Save frozen config
    (artifact_dir / "config.json").write_text(
        json.dumps(config, indent=2, default=str), encoding="utf-8"
    )

    # Save dataset + split manifests
    (artifact_dir / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, default=str), encoding="utf-8"
    )
    (artifact_dir / "split_manifest.json").write_text(
        json.dumps(split_manifest, indent=2, default=str), encoding="utf-8"
    )

    # Master manifest
    manifest = {
        "experiment_id": experiment_id,
        "hypothesis": hypothesis,
        "run_timestamp": timestamp,
        "dataset_version": dataset_manifest.get("dataset_version"),
        "dataset_content_hash": dataset_manifest.get("content_hash"),
        "split_id": split_manifest.get("split_id"),
        "split_method": split_manifest.get("split_method"),
        "config_hash": _dict_hash(config),
        "metrics_summary": {
            k: v.get("macro_f1") if isinstance(v, dict) and "macro_f1" in v else None
            for k, v in metrics.items() if isinstance(v, dict)
        },
    }
    (artifact_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )

    print(f"\n  [ok] Artifacts saved to {artifact_dir}")
    print("  [ok] Conclusion written (see conclusion.md in the artifact directory).")
    return artifact_dir


def _dict_hash(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
