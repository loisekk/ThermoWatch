"""E0: Data & Label Feasibility Audit.

Answers: does the dataset have enough independent facility/event coverage
to support the research program? What are the leakage risks?

Usage:
    cd server/api
    python -m app.research.e00_data_audit --source synthetic
    python -m app.research.e00_data_audit --source real --csv path/to/firms.csv
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from app.research.config import DATASET_SCHEMA_VERSION
from app.research.dataset import (
    create_dataset_manifest,
    generate_synthetic_dataset,
    load_real_dataset,
)
from app.research.runner import run_experiment


def audit_dataset(df: pd.DataFrame, source: str) -> tuple[dict, pd.DataFrame, str]:
    """Run the full E0 audit."""
    coverage = _coverage_table(df)

    label_dist = df["label_source_class"].value_counts().to_dict()
    provenance_dist = df["label_provenance"].value_counts().to_dict()
    normality_dist = df["label_normality"].value_counts().to_dict()

    leakage = _leakage_report(df)
    missing = _missing_data_report(df)
    facility_independence = _facility_independence_check(df)

    # --- Decision ---
    n_facilities = int(df["facility_id"].nunique())
    n_classes = len(label_dist)
    min_support = min(label_dist.values()) if label_dist else 0
    enough_facilities = n_facilities >= 15
    enough_classes = n_classes >= 8
    enough_support = min_support >= 50

    decision = "GO" if (enough_facilities and enough_classes) else "REVISE"

    metrics = {
        "experiment": "E00_data_audit",
        "source": source,
        "dataset_version": DATASET_SCHEMA_VERSION,
        "coverage_table": coverage,
        "label_distribution": label_dist,
        "label_provenance": provenance_dist,
        "normality_distribution": normality_dist,
        "leakage_report": leakage,
        "missing_data": missing,
        "facility_independence": facility_independence,
        "decision": {
            "verdict": decision,
            "n_facilities": n_facilities,
            "n_classes": n_classes,
            "min_class_support": int(min_support),
            "criteria": {
                "enough_facilities_15": enough_facilities,
                "enough_classes_8": enough_classes,
                "min_support_50": enough_support,
            },
        },
    }

    conclusion = f"""## E0 Data Audit Results

**Verdict: {decision}**

### Coverage
- {coverage['n_observations']} observations across {coverage['n_facilities']} facilities
- Date range: {coverage['date_range'][0]} to {coverage['date_range'][1]}
- Mean observations per facility: {coverage['mean_obs_per_facility']}

### Label Quality
- {len(label_dist)} source classes represented
- Provenance: {json.dumps(provenance_dist)}
- Normality labels: {json.dumps(normality_dist)}

### Leakage Risks
{_format_leakage(leakage)}

### Missing Data
- FRP missing: {missing['frp_missing_pct']:.1f}%
- Brightness missing: {missing['brightness_missing_pct']:.1f}%

### Recommendation
{'Dataset has sufficient coverage to proceed to E1 baselines.' if decision == 'GO' else 'Dataset requires revision before E1 — see criteria above.'}
"""

    # Predictions not applicable for audit — empty df placeholder
    return metrics, df.head(0), conclusion


def _coverage_table(df):
    fac_obs = df[df["facility_id"] != ""]
    natural_obs = df[df["facility_id"] == ""]
    per_facility = fac_obs.groupby("facility_id").size()
    return {
        "n_observations": len(df),
        "n_facility_observations": len(fac_obs),
        "n_natural_observations": len(natural_obs),
        "n_facilities": int(fac_obs["facility_id"].nunique()),
        "n_natural_events": int(natural_obs["event_id"].nunique()),
        "mean_obs_per_facility": round(float(per_facility.mean()), 1) if len(per_facility) else 0,
        "min_obs_per_facility": int(per_facility.min()) if len(per_facility) else 0,
        "max_obs_per_facility": int(per_facility.max()) if len(per_facility) else 0,
        "date_range": [str(df["observed_at"].min()), str(df["observed_at"].max())],
        "temporal_gaps_days": _find_gaps(df),
    }


def _find_gaps(df):
    dates = df["observed_at"].dt.date.unique()
    if len(dates) < 2:
        return 0
    date_series = pd.Series(sorted(dates))
    gaps = date_series.diff().dt.days
    return int((gaps > 1).sum())


def _missing_data_report(df):
    return {
        "frp_missing_pct": round(float(df["frp"].isna().mean() * 100), 2),
        "brightness_missing_pct": round(float(df["brightness_ti4"].isna().mean() * 100), 2),
        "confidence_unknown_pct": round(float((df["confidence"] == "unknown").mean() * 100), 2),
    }


def _leakage_report(df):
    """Check for common leakage patterns."""
    risks = []

    # Exact duplicate coordinates
    dup_coords = int(df.duplicated(subset=["latitude", "longitude", "observed_at"]).sum())
    if dup_coords > 0:
        risks.append(f"EXACT_DUPLICATES: {dup_coords} observations share (lat, lon, timestamp)")

    # Class separation by location alone (shortcut learning check)
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score

    coords = df[["latitude", "longitude"]].values
    labels = df["label_source_class"].astype("object").to_numpy()
    if len(set(labels)) > 1:
        rf = RandomForestClassifier(n_estimators=50, random_state=0, n_jobs=-1)
        scores = cross_val_score(rf, coords, labels, cv=3, scoring="f1_macro")
        location_only_f1 = round(float(scores.mean()), 3)
        if location_only_f1 > 0.85:
            risks.append(
                f"LOCATION_SHORTCUT: coordinates alone achieve F1={location_only_f1} — "
                "model may memorize locations instead of learning thermal physics"
            )

    return {
        "risks": risks if risks else ["None detected"],
        "n_risks": len(risks),
        "verdict": "REVIEW" if risks else "CLEAN",
    }


def _facility_independence_check(df):
    """Check whether facilities are spatially separated enough for
    leave-one-facility-out to be meaningful."""
    fac_obs = df[df["facility_id"] != ""]
    facilities = fac_obs.groupby("facility_id").agg(
        lat=("latitude", "mean"), lon=("longitude", "mean")
    )
    min_dist = 999.0
    close_pairs = []
    fac_list = list(facilities.iterrows())
    for i in range(len(fac_list)):
        for j in range(i + 1, len(fac_list)):
            d = _haversine(fac_list[i][1]["lat"], fac_list[i][1]["lon"],
                           fac_list[j][1]["lat"], fac_list[j][1]["lon"])
            min_dist = min(min_dist, d)
            if d < 10.0:  # facilities within 10 km
                close_pairs.append((fac_list[i][0], fac_list[j][0], round(d, 1)))
    return {
        "min_facility_separation_km": round(float(min_dist), 1),
        "close_pairs_under_10km": close_pairs,
        "note": "Close pairs may share thermal signal — relevant for LOFO evaluation",
    }


def _format_leakage(leakage):
    return "\n".join(f"- {risk}" for risk in leakage["risks"])


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# =====================================================================
# Main
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="E0: Data feasibility audit")
    parser.add_argument("--source", choices=["synthetic", "real"], default="synthetic")
    parser.add_argument("--csv", help="Path to FIRMS archive CSV (for --source real)")
    parser.add_argument("--n-days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.source == "synthetic":
        print("  [WARN] Using SYNTHETIC data — results validate the harness, not real-world claims")
        df = generate_synthetic_dataset(n_days=args.n_days, seed=args.seed)
        source = "synthetic"
    else:
        if not args.csv:
            raise SystemExit("--csv required for --source real")
        df = load_real_dataset(args.csv)
        source = f"real:{args.csv}"

    ds_manifest = create_dataset_manifest(df, source=source, version=DATASET_SCHEMA_VERSION)
    config = {"source": source, "n_days": args.n_days, "seed": args.seed}

    run_experiment(
        experiment_id="E00_data_audit",
        hypothesis="Dataset has sufficient facility/event coverage and no critical leakage to support E1+",
        dataset_manifest=ds_manifest,
        split_manifest={"split_method": "none (audit only)"},
        config=config,
        experiment_fn=lambda: audit_dataset(df, source),
    )


if __name__ == "__main__":
    main()

