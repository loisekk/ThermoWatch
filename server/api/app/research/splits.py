"""Leakage-controlled split utilities.

Principle: observations from the same facility NEVER appear in both
train and test (unless using temporal split, where the same facility
appears but at different times — documented in the manifest).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from app.research.config import (
    FACILITY_SPLIT_TEST_SIZE,
    SPLIT_SEED,
    TEMPORAL_SPLIT_TRAIN_FRACTION,
)


def facility_grouped_split(
    df: pd.DataFrame,
    test_size: float = FACILITY_SPLIT_TEST_SIZE,
    seed: int = SPLIT_SEED,
) -> tuple[pd.Index, pd.Index, dict]:
    """Split by facility — no facility appears in both train and test.

    Observations not attributed to a facility (natural fires, agri burns)
    are grouped by their event_id so the same fire event stays together.

    Returns (train_idx, test_idx, manifest).
    """
    # Assign group keys: facility_id for facility obs, event_id for others
    groups = df.apply(
        lambda r: r["facility_id"] if r["facility_id"] else f"event:{r['event_id']}",
        axis=1,
    )

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_idx, test_idx = next(splitter.split(df, groups=groups.to_numpy(dtype=object)))

    train_facilities = sorted(set(groups.iloc[train_idx]))
    test_facilities = sorted(set(groups.iloc[test_idx]))

    manifest = {
        "split_method": "facility_grouped",
        "seed": seed,
        "test_size_fraction": test_size,
        "n_train_observations": len(train_idx),
        "n_test_observations": len(test_idx),
        "train_groups": train_facilities,
        "test_groups": test_facilities,
        "overlap_check": "PASS" if not set(train_facilities) & set(test_facilities) else "FAIL",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest["split_id"] = _hash_manifest(manifest)
    return df.index[train_idx], df.index[test_idx], manifest


def temporal_split(
    df: pd.DataFrame,
    train_fraction: float = TEMPORAL_SPLIT_TRAIN_FRACTION,
) -> tuple[pd.Index, pd.Index, dict]:
    """Split by time — train on earlier data, test on later data.

    Same facility may appear in both, but at different times.
    This simulates deployment: you train on history, predict the future.
    """
    df_sorted = df.sort_values("observed_at")
    n = len(df_sorted)
    split_point = int(n * train_fraction)
    cutoff_time = df_sorted.iloc[split_point]["observed_at"]

    train_mask = df["observed_at"] < cutoff_time
    test_mask = ~train_mask

    train_idx = df.index[train_mask]
    test_idx = df.index[test_mask]

    manifest = {
        "split_method": "temporal",
        "train_fraction": train_fraction,
        "cutoff_time": str(cutoff_time),
        "n_train_observations": len(train_idx),
        "n_test_observations": len(test_idx),
        "shared_facilities": sorted(
            set(df.loc[train_idx, "facility_id"]) & set(df.loc[test_idx, "facility_id"])
        ),
        "note": "Same facilities appear in both splits at different times — "
                "temporal leakage is controlled by strict time ordering.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest["split_id"] = _hash_manifest(manifest)
    return train_idx, test_idx, manifest


def leave_one_facility_out(
    df: pd.DataFrame,
) -> list[tuple[str, pd.Index, pd.Index, dict]]:
    """Generate LOFO folds: each facility takes a turn as the test set.

    Returns list of (facility_id, train_idx, test_idx, manifest).
    """
    facility_ids = sorted(df["facility_id"].unique())
    facility_ids = [f for f in facility_ids if f]  # skip empty (non-facility)
    folds = []
    for held_out in facility_ids:
        train_idx = df.index[df["facility_id"] != held_out]
        test_idx = df.index[df["facility_id"] == held_out]
        if len(test_idx) < 5:  # skip facilities with too few observations
            continue
        manifest = {
            "split_method": "leave_one_facility_out",
            "held_out_facility": held_out,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
        }
        folds.append((held_out, train_idx, test_idx, manifest))
    return folds


def _hash_manifest(manifest: dict) -> str:
    """Deterministic hash of the split manifest for versioning."""
    content = json.dumps(manifest, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:12]
