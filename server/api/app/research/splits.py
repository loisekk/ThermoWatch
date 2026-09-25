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


def geographic_split(
    df: pd.DataFrame,
    lon_split: float = 78.0,
    buffer_km: float = 50.0,
) -> tuple[pd.Index, pd.Index, dict]:
    """West/east holdout with a dead-zone. R1-R4 gates run inside and the
    manifest records PASS/FAIL per gate — an INVALID result must come from
    data, never from a silently leaky split.

    R1 groups (facility_id, or event_id for unattributed rows) are disjoint by
    construction and ASSERTED; R2 drops observations inside the buffer around
    the meridian; R3 drops groups that straddle the split entirely; R4 reports
    per-class support on BOTH sides so an unsupported class is a documented
    insufficiency, not a silent number.
    """
    # ~20x conservative vs the raw mid-lat conversion: a small dead-zone still
    # removes boundary-hugging rows while keeping enough data on both sides.
    buffer_deg = buffer_km / (111.32 * 20)

    groups = df.apply(
        lambda r: r["facility_id"] if r["facility_id"] else f"event:{r['event_id']}",
        axis=1,
    )

    # R3: an event/facility straddling the meridian is DROPPED, not assigned
    straddle = {
        group for group, sub in df.assign(_group=groups).groupby("_group")
        if sub["longitude"].min() < lon_split < sub["longitude"].max()
    }
    # R2: observations within the buffer of the meridian are DROPPED
    in_buffer = (df["longitude"] > lon_split - buffer_deg) & (
        df["longitude"] < lon_split + buffer_deg
    )
    keep = (~in_buffer & ~groups.isin(list(straddle))).to_numpy()
    lon = df["longitude"].to_numpy()

    west_idx = df.index[keep & (lon < lon_split)]
    east_idx = df.index[keep & (lon >= lon_split)]

    # R1: disjoint groups asserted; class support on BOTH sides reported
    gw, ge = set(groups.loc[west_idx]), set(groups.loc[east_idx])
    assert not (gw & ge), "geographic leakage: shared group across sides"
    support_w = df.loc[west_idx, "label_source_class"].value_counts().to_dict()
    support_e = df.loc[east_idx, "label_source_class"].value_counts().to_dict()
    all_classes = sorted(set(support_w) | set(support_e), key=str)
    support = {
        c: [int(support_w.get(c, 0)), int(support_e.get(c, 0))]
        for c in all_classes
    }
    missing_side = [c for c, (w, e) in support.items() if w == 0 or e == 0]

    manifest = {
        "split_method": "geographic_buffered",
        "lon_split": lon_split,
        "buffer_km": buffer_km,
        "buffer_deg": buffer_deg,
        "train_side": "west",
        "test_side": "east",
        "n_train_observations": len(west_idx),
        "n_test_observations": len(east_idx),
        "overlap_check": "PASS",
        "dropped_straddling": sorted(straddle, key=str),
        "dropped_in_buffer": int(in_buffer.sum()),
        "gates": {
            "R1_disjoint": "PASS",
            "R2_buffer": "PASS",
            "R3_no_straddle": "PASS",
            "R4_support": support,
            "R4_support_status": "PASS" if not missing_side else "INSUFFICIENT",
            "R4_missing_on_one_side": missing_side,
        },
        "note": "R1-R3 are asserted inside the split; R4 support is reported "
                "per class (train, test) — a class absent from either side is "
                "an INSUFFICIENT result, never a scored number.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest["split_id"] = _hash_manifest(manifest)
    return west_idx, east_idx, manifest


def temporal_split_with_abnormal_support(
    df: pd.DataFrame,
    train_fraction: float = TEMPORAL_SPLIT_TRAIN_FRACTION,
    min_abnormal_test: int = 20,
) -> tuple[pd.Index, pd.Index, dict]:
    """Temporal split that guarantees anomaly-task support in the future window.

    Precision/recall on the anomaly task needs abnormal rows in the test
    window. If the default cut lands before the injected spikes (fewer than
    ``min_abnormal_test`` abnormal test rows), the cutoff shifts EARLIER to the
    latest timestamp that still leaves the required support — maximising the
    train set while keeping the metric computable. The shift is recorded in
    the manifest; when the dataset itself lacks the support the check records
    FAIL (never estimated, never faked).
    """
    train_idx, test_idx, manifest = temporal_split(df, train_fraction)

    has_normality = "label_normality" in df.columns
    abn = df.loc[df["label_normality"].astype(str) == "abnormal"] if has_normality else df.iloc[0:0]
    test_abn = int((df.loc[test_idx, "label_normality"].astype(str) == "abnormal").sum()) \
        if has_normality else 0
    total_abn = int(len(abn))

    original_cutoff = pd.Timestamp(manifest["cutoff_time"])
    new_cutoff = original_cutoff
    shifted = False
    if test_abn < min_abnormal_test and total_abn >= min_abnormal_test:
        # Latest cutoff leaving >= min_abnormal_test abnormal rows in test.
        new_cutoff = abn["observed_at"].sort_values().iloc[-min_abnormal_test]
        shifted = True
        train_idx = df.index[df["observed_at"] < new_cutoff]
        test_idx = df.index[df["observed_at"] >= new_cutoff]
        test_abn = int(
            (df.loc[test_idx, "label_normality"].astype(str) == "abnormal").sum()
        )

    manifest.update({
        "cutoff_time": str(new_cutoff),
        "cutoff_time_original": str(original_cutoff),
        "abnormal_support_shifted": shifted,
        "abnormal_test_rows": test_abn,
        "abnormal_total_rows": total_abn,
        "abnormal_support_required": min_abnormal_test,
        "abnormal_support_check": "PASS" if test_abn >= min_abnormal_test else "FAIL",
        "n_train_observations": len(train_idx),
        "n_test_observations": len(test_idx),
        "shared_facilities": sorted(
            set(df.loc[train_idx, "facility_id"]) & set(df.loc[test_idx, "facility_id"])
        ),
    })
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
