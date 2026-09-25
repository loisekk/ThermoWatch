"""E10 — hard-case benchmark: production rule detector vs H1-H12 scenarios.

The rule under test is the production assessment rule
(``app/services/assessment.py``) — flag ABNORMAL when

  - |intensity z| > ``settings.abnormal_z`` (log1p-FRP MAD z-score), or
  - the detection is a new zone (beyond every learned zone's own extent plus
    the observation's pixel half-diagonal plus ``settings.abnormal_new_zone_km``)

EXTENDED with the sustained-shift arm under test (plan 4.2 / H5): a slow
trajectory is invisible to a single-row intensity gate, so the windowed mean
of the facility's last K observations is scored against the baseline
(``sustained_shift_residual``). Every flag is attributed to the arm that
produced it (``caught_by_arm``) — mechanism evidence, not just pass/fail.

Facility normal states are built from normal-labelled history only: rows
labelled abnormal (the injected H2-H5 anomalies) never train the state, and
only normal rows before a temporal cutoff form history — evaluation rows are
never seen during state building. Production ``settings.state_*``
sufficiency thresholds apply. Nothing here is tuned on the hard-case rows.

Scenario expectations (scored, not tuned to pass):
  H1 normal persistent  -> false-alert rate low
  H2 intensity spike    -> recall high (intensity arm)
  H3 new zone           -> recall high (spatial arm)
  H4 displacement       -> recall high (spatial arm; 1.5-4 km, detectable)
  H5 duration anomaly   -> recall moderate (sustained arm carries it)
  H6 natural near fac.  -> natural-fire rate reported (land cover + gated
  H7 agri near facility     proximity; NO facility-type inheritance)
  H8 overlapping        -> association-level; reported for coverage only
  H9 sparse history     -> abstention rises when history is thinned
  H11 cold start        -> abstention near-total below sufficiency thresholds
  H12 regime shift      -> days-to-detection after a step change in FRP

H10 (missing corroboration) is NOT a row-level detector scenario: it is
covered by the E13 degradation matrix plus the Phase-7 external-evidence kill
switch, and is reported as an explicit gap.

Usage:
    python -m app.research.e10_hard_cases --n-days 60
"""
from __future__ import annotations

import argparse
from typing import cast

import numpy as np
import pandas as pd

from app.core.config import settings
from app.ml.normal_state import FacilityNormalState, build_facility_normal_state
from app.ml.residuals import (
    SUSTAINED_WINDOW,
    SUSTAINED_Z,
    intensity_residual,
    spatial_residual,
    sustained_shift_residual,
)
from app.research.config import DATASET_SCHEMA_VERSION, MODEL_SEED
from app.research.dataset import create_dataset_manifest
from app.research.hard_cases import HARD_CASE_DESCRIPTIONS, generate_hard_case_dataset
from app.research.runner import run_experiment

EXPERIMENT_ID = "E10_hard_cases"

# Pre-registered bars (fixed before looking at results; failures are reported,
# never silently re-tuned).
GATES = {
    "H1_false_alert_max": 0.10,
    "H2_recall_min": 0.80,
    "H3_recall_min": 0.80,
    "H4_recall_min": 0.60,
    "H5_recall_min": 0.50,
    "H11_abstain_min": 0.95,
}


def _build_states(history: pd.DataFrame) -> dict[str, FacilityNormalState]:
    """One normal state per facility from normal-labelled history rows.

    ``history`` is passed in already time-filtered by the caller (H9/H11
    pass thinned variants); abnormal-labelled rows are dropped defensively
    so injected anomalies can never enter a state.
    """
    states: dict[str, FacilityNormalState] = {}
    hist = history[
        (history["label_normality"] == "normal") & (history["facility_id"] != "")
    ]
    for fid, grp in hist.groupby("facility_id"):
        states[str(fid)] = build_facility_normal_state(
            grp, str(fid), str(grp["facility_type"].iloc[0]),
            min_obs=settings.state_min_obs, min_days=settings.state_min_days,
            zone_eps_km=settings.state_zone_eps_km,
            zone_min_samples=settings.state_zone_min_samples,
        )
    return states


DETECTOR_ARMS = ("intensity", "spatial_new_zone", "sustained_shift")


def _rule_flag(
    frp: float, lat: float, lon: float, state: FacilityNormalState,
    hour: int | None = None,
    scan_km: float | None = None,
    track_km: float | None = None,
    window: list[float] | None = None,
) -> tuple[bool, str | None, float | None, float | None]:
    """Rule with mechanism attribution: (flag, arm, intensity_z, nearest_km).

    Arms are evaluated in a fixed order and the FIRST firing arm is recorded,
    so ``caught_by_arm`` counts sum to the number of flagged rows.
    """
    is_night = None if hour is None else (hour < 6 or hour >= 18)
    extra = {}
    if scan_km is not None and track_km is not None:
        extra = {"obs_scan_km": scan_km, "obs_track_km": track_km}
    res_i = intensity_residual(frp, state, hour=hour, is_night=is_night)
    res_s = spatial_residual(
        lat, lon, state, new_zone_km=settings.abnormal_new_zone_km, **extra
    )
    res_sus = sustained_shift_residual(window or [], state, is_night=is_night)

    arm: str | None = None
    if res_i.z is not None and abs(res_i.z) > settings.abnormal_z:
        arm = "intensity"
    elif res_s.is_new_zone:
        arm = "spatial_new_zone"
    elif res_sus.z is not None and abs(res_sus.z) > SUSTAINED_Z:
        arm = "sustained_shift"
    return arm is not None, arm, res_i.z, res_s.nearest_zone_km


def _history_windows(
    history: pd.DataFrame, window_size: int = SUSTAINED_WINDOW
) -> dict[str, list[float]]:
    """Last ``window_size`` log1p(FRP) per facility, in time order.

    Seeds the rolling window so the sustained arm is causal from the first
    evaluation row: nothing after the cutoff is ever used.
    """
    windows: dict[str, list[float]] = {}
    hist = history[history["facility_id"] != ""].sort_values("observed_at")
    for r in hist.itertuples():
        w = windows.setdefault(str(r.facility_id), [])
        w.append(float(np.log1p(max(float(cast(float, r.frp)), 0.0))))
        del w[:-window_size]
    return windows


def _rolling_windows(
    rows: pd.DataFrame, seed_windows: dict[str, list[float]] | None,
    window_size: int = SUSTAINED_WINDOW,
) -> dict[int, list[float]]:
    """Per-row window (last K observations ENDING AT the row) keyed by position.

    Rows are walked in chronological order per facility, but the returned map
    is keyed by the row's position in ``rows`` so callers keep their own
    order (``final_gates`` pairs predictions to ``eval_rows`` positionally).
    """
    windows = {k: list(v) for k, v in (seed_windows or {}).items()}
    out: dict[int, list[float]] = {}
    if rows.empty:
        return out
    order = np.argsort(rows["observed_at"].to_numpy(), kind="stable")
    for pos in order:
        row = rows.iloc[int(pos)]
        fid = str(row["facility_id"])
        w = windows.setdefault(fid, [])
        w.append(float(np.log1p(max(float(cast(float, row["frp"])), 0.0))))
        del w[:-window_size]
        out[int(pos)] = list(w)
    return out


def _detect_rows(
    rows: pd.DataFrame, states: dict, seed_windows: dict[str, list[float]] | None = None,
) -> list[dict]:
    """One causal pass over ``rows``: prediction + firing arm per row.

    An abstention means the facility normal state is missing or below the
    production sufficiency thresholds — never a silent NORMAL.
    """
    windows = _rolling_windows(rows, seed_windows)
    records: list[dict] = []
    for pos, r in enumerate(rows.itertuples()):
        state = states.get(str(r.facility_id))
        z: float | None = None
        nearest: float | None = None
        arm: str | None = None
        if state is None or not state.sufficient:
            pred = "abstain"
        else:
            flag, arm, z, nearest = _rule_flag(
                cast(float, r.frp),
                cast(float, r.latitude),
                cast(float, r.longitude),
                state,
                hour=getattr(r.observed_at, "hour", None),
                scan_km=getattr(r, "scan", None),
                track_km=getattr(r, "track", None),
                window=windows.get(pos),
            )
            pred = "abnormal" if flag else "normal"
            if not flag:
                arm = None
        records.append({
            "hard_case_id": str(r.hard_case_id),
            "facility_id": str(r.facility_id),
            "observed_at": r.observed_at,
            "label_normality": str(r.label_normality),
            "frp": float(cast(float, r.frp)),
            "prediction": pred,
            "arm": arm,
            "intensity_z": z,
            "nearest_zone_km": nearest,
        })
    return records


# =====================================================================
# Evaluation helpers
# =====================================================================
HISTORY_FRAC = 0.60        # fraction of days used to build normal states
SPARSE_KEEP_EVERY = 3      # H9: keep every 3rd history day (gaps from orbit/cloud)
COLD_START_DAYS = 3        # H11: history window far below state_min_days
REGIME_SHIFT_FACTOR = 2.5  # H12: step multiplier applied after the shift point

# Normal-tagged rows that would otherwise self-score (they trained the state)
# get cut off to the held-out tail. H8 is coverage-only (no gate, no false-alert
# bar) so all its rows are scored regardless of cutoff.
NORMAL_TAGS = {"H1_normal_persistent", "H6_natural_near_facility",
               "H7_agri_near_facility"}

SCENARIO_ORDER = [
    "H1_normal_persistent", "H2_intensity_spike", "H3_new_zone",
    "H4_displacement", "H5_duration_anomaly", "H6_natural_near_facility",
    "H7_agri_near_facility", "H8_overlapping",
]


def _split_history(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Temporal cutoff: first HISTORY_FRAC of days build states; rest is eval."""
    days = pd.DatetimeIndex(sorted(df["observed_at"].dt.normalize().unique()))
    cutoff = pd.Timestamp(days[min(int(len(days) * HISTORY_FRAC), len(days) - 1)])
    history = df[(df["observed_at"] < cutoff) & (df["label_normality"] == "normal")]
    eval_all = df[df["observed_at"] >= cutoff]
    return history, eval_all, cutoff


def _score_rows(
    rows: pd.DataFrame, states: dict,
    seed_windows: dict[str, list[float]] | None = None,
) -> tuple[dict, list[dict]]:
    """Apply the rule per row; abstain when the state is unusable.

    Records keep the INPUT row order (callers pair them positionally).
    """
    records = _detect_rows(rows, states, seed_windows)
    summary = {"n": len(records), "flagged": 0, "abstained": 0, "normal": 0}
    for rec in records:
        if rec["prediction"] == "abstain":
            summary["abstained"] += 1
        elif rec["prediction"] == "abnormal":
            summary["flagged"] += 1
        else:
            summary["normal"] += 1
    return summary, records


def _rate(summary: dict) -> float | None:
    if summary["n"] == 0:
        return None
    return summary["flagged"] / summary["n"]


def _abstain_rate(summary: dict) -> float | None:
    if summary["n"] == 0:
        return None
    return summary["abstained"] / summary["n"]


def _attribute_flags(
    rows: pd.DataFrame, states: dict,
    seed_windows: dict[str, list[float]] | None = None,
) -> dict:
    """Split the flag rate by ARM: intensity vs spatial vs sustained.

    Shows *which* part of the rule produced a scenario's flags — essential for
    reading a gate failure (or a gate PASS) as mechanism evidence rather than
    a bare number. ``caught_by_arm`` counts sum to the flagged total because
    the detector records the FIRST firing arm per row.
    """
    records = _detect_rows(rows, states, seed_windows)
    scored = [r for r in records if r["prediction"] != "abstain"]
    if not scored:
        return {"n_scored": 0,
                "caught_by_arm": {arm: 0 for arm in DETECTOR_ARMS}}

    arm_counts = {arm: 0 for arm in DETECTOR_ARMS}
    nearest: list[float] = []
    for rec in scored:
        if rec["arm"] in arm_counts:
            arm_counts[rec["arm"]] += 1
        if rec["nearest_zone_km"] is not None:
            nearest.append(float(rec["nearest_zone_km"]))

    n = len(scored)
    return {
        "n_scored": n,
        "intensity_fire_rate": arm_counts["intensity"] / n,
        "spatial_fire_rate": arm_counts["spatial_new_zone"] / n,
        "sustained_fire_rate": arm_counts["sustained_shift"] / n,
        "caught_by_arm": arm_counts,
        "caught_by_arm_rate": {k: v / n for k, v in arm_counts.items()},
        "median_nearest_zone_km": float(np.median(nearest)) if nearest else None,
    }


def _natural_fire_feature_audit(rows: pd.DataFrame) -> dict:
    """H6/H7 feature-level evidence (plan 4.7): natural fire stays natural.

    A natural fire near a facility must present as natural fire: non-industrial
    land cover AND no facility-type one-hot. The pre-fix B1 features gave a
    wildfire 3 km from a refinery ``near_refinery=1`` because the one-hot was
    keyed on the NEAREST facility with no distance gate, so the row inherited
    the facility's class. This is a feature-column audit, not a retrained
    classifier — no model is fit or tuned on these rows.
    """
    from app.research.baselines import extract_b1_features, get_facility_coords

    if rows.empty:
        return {"n_rows": 0, "natural_fire_rate": None,
                "facility_type_inheritance_rate": None}
    feats = extract_b1_features(rows.reset_index(drop=True), get_facility_coords())
    near_cols = [c for c in feats.columns
                 if c.startswith("near_") and c != "near_facility"]
    inherited = (feats[near_cols].to_numpy() == 1).any(axis=1)
    landcover = rows.reset_index(drop=True)["landcover"].astype(str).to_numpy()
    non_industrial = np.isin(landcover, ["forest", "agriculture"])
    natural = (~inherited) & non_industrial
    return {
        "n_rows": int(len(feats)),
        "natural_fire_rate": float(natural.mean()),
        "facility_type_inheritance_rate": float(inherited.mean()),
        "n_near_facility_within_2km": int(feats["near_facility"].sum()),
        "note": "feature-level audit of land cover + distance-gated proximity; "
                "no classifier retrained on these rows",
    }


def _day_to_detection(flag_times: list, shift_ts: pd.Timestamp) -> int | None:
    """Whole days from the regime shift to the first flagged row (None = never)."""
    if not flag_times:
        return None
    delta = (min(flag_times) - shift_ts) // pd.Timedelta(days=1)
    return max(int(delta), 0)


# =====================================================================
# Metrics assembly
# =====================================================================
def _gate(name: str, value: float | None, op: str, threshold: float) -> dict:
    """Evaluate one pre-registered gate. Unverifiable (None) => fail."""
    if value is None:
        passed = False
    elif op == "<=":
        passed = value <= threshold
    else:
        passed = value >= threshold
    return {
        "gate": name, "value": value, "operator": op,
        "threshold": threshold, "pass": bool(passed),
    }


def build_metrics(
    df: pd.DataFrame, n_days: int
) -> tuple[dict, pd.DataFrame, str]:
    history, eval_all, cutoff = _split_history(df)
    states = _build_states(history)
    n_sufficient = sum(1 for s in states.values() if s.sufficient)
    n_zones = sum(len(s.zones) for s in states.values())
    print(f"  History: {len(history)} normal rows before {cutoff.date()}")
    print(f"  States: {len(states)} built, {n_sufficient} sufficient, "
          f"{n_zones} zones total")

    eval_fac = eval_all[eval_all["facility_id"] != ""]
    scenarios: dict[str, dict] = {}
    prediction_frames: list[pd.DataFrame] = []
    # Causal seeds for the sustained arm: the facility's last K log-FRPs from
    # history only (never eval rows, never the future).
    seed_windows = _history_windows(history)

    # --- H1-H8: row-tagged scenarios scored against the same states ---
    for tag in SCENARIO_ORDER:
        rows = df[df["hard_case_id"] == tag]
        if tag in NORMAL_TAGS:
            # Normal-tagged rows also appear in training history; score only
            # the held-out tail so the false-alert bar means anything.
            rows = rows[rows["observed_at"] >= cutoff]
        summary, records = _score_rows(rows, states, seed_windows)
        entry = {
            "description": HARD_CASE_DESCRIPTIONS.get(tag, ""),
            "n_rows": summary["n"],
            "n_flagged": summary["flagged"],
            "n_abstained": summary["abstained"],
            "n_normal": summary["normal"],
            "flagged_rate": _rate(summary),
            "abstain_rate": _abstain_rate(summary),
            "flag_attribution": _attribute_flags(rows, states, seed_windows),
        }
        if tag == "H1_normal_persistent":
            entry["expectation"] = "false-alert rate stays low"
            entry["metric"] = "false_alert_rate"
            entry["value"] = entry["flagged_rate"]
        elif tag in ("H6_natural_near_facility", "H7_agri_near_facility"):
            entry["expectation"] = ("natural fire near a facility stays natural "
                                    "(land cover + gated proximity)")
            entry["metric"] = "natural_fire_rate"
            entry["feature_audit"] = _natural_fire_feature_audit(rows)
            entry["value"] = entry["feature_audit"]["natural_fire_rate"]
            entry["detector_flagged_rate"] = entry["flagged_rate"]
            entry["attribution_note"] = (
                "rows are force-attributed to the nearby facility so the "
                "detector/classifier path can be exercised; production "
                "association only links detections within 2 km, which these "
                "rows deliberately exceed"
            )
            entry["gated"] = False
        elif tag == "H8_overlapping":
            entry["expectation"] = "association-level; coverage only (no gate)"
            entry["metric"] = "coverage_flagged_rate"
            entry["value"] = entry["flagged_rate"]
        else:
            entry["expectation"] = "recall high (rule flags the row)"
            entry["metric"] = "recall"
            entry["value"] = entry["flagged_rate"]
        scenarios[tag] = entry
        if records:
            frame = pd.DataFrame(records)
            frame["scenario"] = tag
            prediction_frames.append(frame)

    # --- H9: sparse history — thinned states should abstain more ---
    uniq_days = pd.DatetimeIndex(sorted(history["observed_at"].dt.normalize().unique()))
    keep_days = set(uniq_days[::SPARSE_KEEP_EVERY])
    sparse_hist = history[history["observed_at"].dt.normalize().isin(keep_days)]
    sparse_states = _build_states(sparse_hist)
    base_sum, _ = _score_rows(eval_fac, states, seed_windows)
    sparse_sum, _ = _score_rows(eval_fac, sparse_states, _history_windows(sparse_hist))
    base_abstain = _abstain_rate(base_sum) or 0.0
    sparse_abstain = _abstain_rate(sparse_sum)
    scenarios["H9_sparse"] = {
        "description": HARD_CASE_DESCRIPTIONS["H9_sparse"],
        "expectation": "abstention rises when history is thinned",
        "metric": "abstain_rate_thinned",
        "value": sparse_abstain,
        "abstain_rate_full_history": base_abstain,
        "abstain_rate_thinned": sparse_abstain,
        "abstention_delta": (
            (sparse_abstain - base_abstain)
            if sparse_abstain is not None else None
        ),
        "n_history_rows_full": int(len(history)),
        "n_history_rows_thinned": int(len(sparse_hist)),
        "n_states_sufficient_thinned": sum(
            1 for s in sparse_states.values() if s.sufficient
        ),
        "gated": False,
    }

    # --- H11: cold start — only the first few days of history exist ---
    cold_days = set(uniq_days[:COLD_START_DAYS])
    cold_hist = history[history["observed_at"].dt.normalize().isin(cold_days)]
    cold_states = _build_states(cold_hist)
    cold_sum, _ = _score_rows(eval_fac, cold_states, _history_windows(cold_hist))
    scenarios["H11_cold_start"] = {
        "description": HARD_CASE_DESCRIPTIONS["H11_cold_start"],
        "expectation": "abstention near-total below sufficiency thresholds",
        "metric": "abstain_rate",
        "value": _abstain_rate(cold_sum),
        "n_states_sufficient_cold": sum(
            1 for s in cold_states.values() if s.sufficient
        ),
        "n_history_days_used": COLD_START_DAYS,
        "gated": True,
    }

    # --- H12: regime shift — step change in FRP, days-to-detection ---
    shift_days: list[int] = []
    n_shift_facilities = 0
    n_shift_detected = 0
    for fid, state in states.items():
        if not state.sufficient:
            continue
        rows = eval_fac[
            (eval_fac["facility_id"] == fid)
            & (eval_fac["label_normality"] == "normal")
        ].sort_values("observed_at")
        if len(rows) < 6:
            continue
        n_shift_facilities += 1
        shift_ts = rows["observed_at"].iloc[len(rows) // 2]
        boosted = rows[rows["observed_at"] >= shift_ts].copy()
        boosted["frp"] = (boosted["frp"] * REGIME_SHIFT_FACTOR).round(2)
        summary, records = _score_rows(boosted, {fid: state}, seed_windows)
        flag_times = [r["observed_at"] for r in records if r["prediction"] == "abnormal"]
        days = _day_to_detection(flag_times, shift_ts)
        if days is not None:
            n_shift_detected += 1
            shift_days.append(days)
        if records:
            frame = pd.DataFrame(records)
            frame["scenario"] = "H12_regime_shift"
            prediction_frames.append(frame)
    scenarios["H12_regime_shift"] = {
        "description": HARD_CASE_DESCRIPTIONS["H12_regime_shift"],
        "expectation": "rule flags the boosted rows shortly after the step change",
        "metric": "days_to_detection",
        "value": float(np.median(shift_days)) if shift_days else None,
        "n_facilities_evaluated": n_shift_facilities,
        "n_facilities_detected": n_shift_detected,
        "median_days_to_detection": (
            float(np.median(shift_days)) if shift_days else None
        ),
        "max_days_to_detection": int(max(shift_days)) if shift_days else None,
        "regime_shift_factor": REGIME_SHIFT_FACTOR,
        "gated": False,
    }

    # --- Gates (pre-registered; failures are reported, never re-tuned) ---
    gates = [
        _gate("H1_false_alert_max",
              scenarios["H1_normal_persistent"]["value"], "<=",
              GATES["H1_false_alert_max"]),
        _gate("H2_recall_min", scenarios["H2_intensity_spike"]["value"], ">=",
              GATES["H2_recall_min"]),
        _gate("H3_recall_min", scenarios["H3_new_zone"]["value"], ">=",
              GATES["H3_recall_min"]),
        _gate("H4_recall_min", scenarios["H4_displacement"]["value"], ">=",
              GATES["H4_recall_min"]),
        _gate("H5_recall_min", scenarios["H5_duration_anomaly"]["value"], ">=",
              GATES["H5_recall_min"]),
        _gate("H11_abstain_min", scenarios["H11_cold_start"]["value"], ">=",
              GATES["H11_abstain_min"]),
    ]
    n_pass = sum(1 for g in gates if g["pass"])

    # --- Explicit gaps: scenarios this generator cannot express as rows ---
    documented_gaps = {
        "H10_missing_corroboration": {
            "description": HARD_CASE_DESCRIPTIONS["H10_missing_corroboration"],
            "status": "documented_gap",
            "reason": "not a row-level detector scenario; covered by the E13 "
                      "degradation matrix and the external-evidence kill switch "
                      "(settings.external_evidence_enabled=False).",
        },
    }

    metrics = {
        "n_days": int(n_days),
        "history_frac": HISTORY_FRAC,
        "cutoff_date": str(cutoff.date()),
        "n_history_rows": int(len(history)),
        "n_eval_rows_facility": int(len(eval_fac)),
        "n_states": len(states),
        "n_states_sufficient": n_sufficient,
        "n_zones_total": n_zones,
        "rule_config": {
            "abnormal_z": settings.abnormal_z,
            "abnormal_new_zone_km": settings.abnormal_new_zone_km,
            "state_min_obs": settings.state_min_obs,
            "state_min_days": settings.state_min_days,
        },
        "scenarios": scenarios,
        "gates": gates,
        "gates_summary": {
            "n_pass": n_pass, "n_total": len(gates),
            "all_pass": n_pass == len(gates),
        },
        "documented_gaps": documented_gaps,
    }

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames else pd.DataFrame()
    )
    conclusion = _conclusion(metrics)
    return metrics, predictions, conclusion


def _conclusion(metrics: dict) -> str:
    lines = [
        "### Gates (pre-registered)",
        "",
        "| Gate | Operator | Threshold | Value | Result |",
        "|---|---|---|---|---|",
    ]
    for g in metrics["gates"]:
        val = "n/a" if g["value"] is None else f"{g['value']:.3f}"
        lines.append(
            f"| {g['gate']} | {g['operator']} | {g['threshold']} | {val} | "
            f"{'PASS' if g['pass'] else 'FAIL'} |"
        )
    gs = metrics["gates_summary"]
    lines += ["", f"**{gs['n_pass']}/{gs['n_total']} gates pass.**", "",
              "### Per-scenario results", "",
              "| Scenario | Metric | Value | Rows | Flagged | Abstained |",
              "|---|---|---|---|---|---|"]
    for tag, s in metrics["scenarios"].items():
        val = "n/a" if s["value"] is None else f"{s['value']:.3f}"
        lines.append(
            f"| {tag} | {s['metric']} | {val} | {s.get('n_rows', '—')} | "
            f"{s.get('n_flagged', '—')} | {s.get('n_abstained', '—')} |"
        )

    failed = [g for g in metrics["gates"] if not g["pass"]]
    if failed:
        lines += ["", "### Gate failure attribution", ""]
        for g in failed:
            tag = g["gate"].split("_")[0]
            entry = next(
                (s for k, s in metrics["scenarios"].items() if k.startswith(tag)),
                None,
            )
            lines.append(f"- **{g['gate']}** = {g['value']} (needs {g['operator']} "
                         f"{g['threshold']}) — **FAIL**.")
            if entry and entry.get("flag_attribution", {}).get("n_scored"):
                a = entry["flag_attribution"]
                med = a["median_nearest_zone_km"]
                med_txt = (
                    f"{med:.2f} km" if med is not None
                    else "no zones learned (spatial gate inert by contract)"
                )
                lines.append(
                    f"  - arm fire rates: intensity "
                    f"{a['intensity_fire_rate']:.3f}, spatial "
                    f"{a['spatial_fire_rate']:.3f}, sustained "
                    f"{a.get('sustained_fire_rate', 0.0):.3f}; "
                    f"median distance to nearest learned zone {med_txt} vs "
                    f"new-zone margin "
                    f"{metrics['rule_config']['abnormal_new_zone_km']} km "
                    f"(tolerance = zone extent + pixel half-diagonal + margin)."
                )
        lines.append("")
        lines.append(
            "Failures are reported as measured — thresholds and gates are "
            "pre-registered and are not re-tuned to pass."
        )

    lines += ["", "### Per-scenario arm attribution (mechanism evidence)", "",
              "Flags are attributed to the FIRST firing arm, so the counts sum "
              "to the flagged total. This is how a gate move is shown to come "
              "from the intended mechanism.", "",
              "| Scenario | caught_by_arm (intensity / spatial / sustained) | "
              "n_scored |", "|---|---|---|"]
    for tag, s in metrics["scenarios"].items():
        arm = s.get("flag_attribution", {}).get("caught_by_arm")
        if not arm:
            continue
        lines.append(
            f"| {tag} | {arm['intensity']} / {arm['spatial_new_zone']} / "
            f"{arm['sustained_shift']} | "
            f"{s['flag_attribution']['n_scored']} |"
        )

    lines += ["", "### Documented gaps (honest omissions)", ""]
    for tag, gap in metrics["documented_gaps"].items():
        lines.append(f"- **{tag}** — {gap['reason']}")
    lines += ["", "### Interpretation", "",
              "- States are built from normal history BEFORE the temporal cutoff; "
              "normal-tagged scenarios are scored only after it (no self-scoring).",
              "- Recall = fraction of scenario rows the rule flags; "
              "abstentions count against recall, never in favor of it.",
              "- H6/H7 rows are force-attributed to the nearby facility so the "
              "detector/classifier path can be exercised; production association "
              "only links detections within 2 km, which these rows deliberately "
              "exceed. The reported natural_fire_rate is a FEATURE-COLUMN audit "
              "(land cover + distance-gated near_* one-hots); no classifier is "
              "retrained or tuned on these rows.",
              "- H9/H11 report abstention under thinned/cold-start history — "
              "abstaining is the safe answer when history is inadequate.",
              "- H12 reports whole days from a 2.5x FRP step change to the first "
              "flagged row; median over facilities where detection occurred.",
              "- Scoring is per-row on raw detections. Production aggregates "
              "detections into incidents first (median position, >=2 observations "
              "per incident), so spatial-gate rates here characterize the raw gate "
              "rather than end-to-end incident decisions.",
              "- Generator and detector share ONE observation-uncertainty model "
              "(`app/ml/observation_uncertainty.py`): detections scatter within "
              "their pixel (sigma = half-extent/sqrt(12), scan/track in km), and "
              "the new-zone gate grants zone extent + the observation's own pixel "
              "half-diagonal + the configured margin. The pre-fix mismatch "
              "(scan km used as degrees) is the mechanism the 2026-09-25 run "
              "recorded as the dominant false-alert source.",
              "- The sustained arm reads only past observations (history seed + "
              "the current row); the baseline state excludes the eval window.",
              "",
              "Note: Results are on SYNTHETIC hard-case rows — harness validation "
              "only, not real-world performance claims."]
    return "\n".join(lines)

# =====================================================================
# Main
# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="E10 hard-case benchmark")
    ap.add_argument("--n-days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=MODEL_SEED)
    args = ap.parse_args()

    print(f"  [WARN] SYNTHETIC hard-case dataset (seed={args.seed}) — "
          "harness validation only")
    df = generate_hard_case_dataset(seed=args.seed, n_days=args.n_days)
    ds_manifest = create_dataset_manifest(
        df, "hard_case_synthetic", DATASET_SCHEMA_VERSION
    )
    config = {
        "seed": args.seed,
        "n_days": args.n_days,
        "history_frac": HISTORY_FRAC,
        "sparse_keep_every": SPARSE_KEEP_EVERY,
        "cold_start_days": COLD_START_DAYS,
        "regime_shift_factor": REGIME_SHIFT_FACTOR,
        "gates": GATES,
        "rule_config": {
            "abnormal_z": settings.abnormal_z,
            "abnormal_new_zone_km": settings.abnormal_new_zone_km,
            "state_min_obs": settings.state_min_obs,
            "state_min_days": settings.state_min_days,
            "state_zone_eps_km": settings.state_zone_eps_km,
            "state_zone_min_samples": settings.state_zone_min_samples,
        },
    }
    run_experiment(
        experiment_id=EXPERIMENT_ID,
        hypothesis=(
            "The production rule detector (intensity z + new-zone gate) meets "
            "pre-registered recall/false-alert bars across H1-H12 hard cases"
        ),
        dataset_manifest=ds_manifest,
        split_manifest={
            "split_method": "temporal_cutoff",
            "history_frac": HISTORY_FRAC,
            "note": "normal rows before cutoff build states; scenarios scored "
                    "on the held-out tail (abnormal rows are never trained on)",
        },
        config=config,
        experiment_fn=lambda: build_metrics(df, args.n_days),
    )


if __name__ == "__main__":
    main()
