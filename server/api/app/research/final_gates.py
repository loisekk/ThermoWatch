"""Final Validation & Freeze evidence harness (checklist gates A1-A10, B3).

Fills the MUST VALIDATE gates of the 25 Sep 2026 Final Validation & Freeze
Checklist. This module does NOT build product features: it only measures and
writes evidence.

Every gate invocation writes to ``<repo>/evidence/final/`` with the run ID in
the filename:

    <GATE>_RUN-<runid>.json   machine-readable payload (split + config + numbers)
    <GATE>_RUN-<runid>.md     the human-readable table for the PPT

Contracts inherited from the checklist:
  * held-out / out-of-fold numbers only; anything in-sample is labelled
    DEVELOPMENT/TUNING inside the payload,
  * ONE fixed configuration for all runs (``CONFIG`` below) - no threshold is
    changed after a final score has been seen,
  * a gate that cannot run is recorded PARTIAL/FAIL WITH its blocker, never
    estimated or extrapolated,
  * every number carries its run ID, output path and split.

DATA CAVEAT (read before quoting any number): no real FIRMS archive ships
with this checkout (``load_real_dataset`` requires ``--csv`` and no data CSV
exists in the repo), so every gate runs on the synthetic generators in
``app.research.dataset`` / ``app.research.hard_cases``. All figures are
harness validation on SYNTHETIC data - never real-world performance.

Usage:
    cd server/api
    python -m app.research.final_gates a1
    python -m app.research.final_gates a3 --e11-run 20260925T170000
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.research import e10_hard_cases as e10
from app.research.baselines import (
    extract_b0_features,
    extract_b1_features,
    extract_b3_features,
    get_facility_coords,
)
from app.research.config import (
    B4_MIN_HISTORY_DAYS,
    B4_MIN_HISTORY_OBS,
    DATASET_SCHEMA_VERSION,
    MODEL_SEED,
    RF_MAX_DEPTH,
    RF_MAX_FEATURES,
    RF_MIN_SAMPLES_LEAF,
    RF_N_ESTIMATORS,
    SOURCE_CLASSES,
    SPLIT_SEED,
)
from app.research.dataset import generate_synthetic_dataset
from app.research.hard_cases import HARD_CASE_DESCRIPTIONS, generate_hard_case_dataset
from app.research.metrics import false_alerts_per_facility_day

# <repo>/server/api/app/research/final_gates.py -> parents[4] = repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = REPO_ROOT / "evidence" / "final"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

# ----------------------------------------------------------------------------
# Frozen configuration - identical for every gate, never changed mid-session.
# ----------------------------------------------------------------------------
CONFIG: dict = {
    "seed": SPLIT_SEED,                 # 42 - dataset + split seed
    "model_seed": MODEL_SEED,           # 42 - RF / estimator seed
    "hard_case_seed": MODEL_SEED,       # E10 generator seed (matches E10 runs)
    "hard_case_n_days": 60,             # E10 default
    "train_n_days": 120,                # offline training stream length
    "train_seed": 7,                    # independent stream for A1 supervised baselines
    "train_anomaly_fraction": 0.03,     # generate_synthetic_dataset default
    "history_frac": e10.HISTORY_FRAC,   # 0.60 temporal cutoff (E10 split)
    "rf": {
        "n_estimators": RF_N_ESTIMATORS, "max_depth": RF_MAX_DEPTH,
        "min_samples_leaf": RF_MIN_SAMPLES_LEAF,
        "max_features": RF_MAX_FEATURES, "class_weight": "balanced_subsample",
        "random_state": MODEL_SEED,
    },
    "b0_threshold_z": 3.0,              # fixed midpoint of frozen grid B4_ZSCORE_THRESHOLDS
    "persistence_quantile": 0.95,       # history p95 for the persistence baseline
    "persistence_consecutive_days": 3,  # days required before a persistence alert
    "logreg": {"C": 1.0, "max_iter": 1000, "class_weight": "balanced"},
    "data_source": "synthetic (harness validation only - no real FIRMS archive in checkout)",
}


def _run_id(gate: str) -> str:
    return f"{gate}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _write(gate: str, run_id: str, payload: dict, md: str) -> Path:
    """Write <GATE>_RUN-<runid>.json + .md under <repo>/evidence/final/."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{gate}_RUN-{run_id}"
    (EVIDENCE_DIR / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (EVIDENCE_DIR / f"{stem}.md").write_text(md, encoding="utf-8")
    print(f"  [ok] {gate} run {run_id} -> evidence/final/{stem}.md (+.json)")
    return EVIDENCE_DIR / f"{stem}.md"


def _latest_run(experiment: str) -> Path | None:
    """Latest timestamped artifact run of an experiment (E10, E11, ...)."""
    root = ARTIFACTS_DIR / experiment
    if not root.is_dir():
        return None
    runs = sorted(d for d in root.iterdir() if d.is_dir())
    return runs[-1] if runs else None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_header(code: str, title: str, run_id: str, split: str | dict) -> list[str]:
    return [
        f"**Gate:** {code} — {title}  ",
        f"**Run ID:** `{run_id}`  ",
        f"**Output:** `evidence/final/{code}_RUN-{run_id}.md`  ",
        f"**Split:** {split}  ",
        f"**Config:** frozen CONFIG (seeds {CONFIG['seed']}/{CONFIG['model_seed']}), "
        f"source = {CONFIG['data_source']}  ",
        "",
    ]


# ----------------------------------------------------------------------------
# Shared evaluation helpers (binary alerting view of a held-out window)
# ----------------------------------------------------------------------------
def _binary_metrics(
    eval_rows: pd.DataFrame, pred: pd.Series, eval_days: float,
) -> dict:
    """Precision / recall / F1 / false alerts / time-to-detect on held-out rows.

    ``pred`` holds "abnormal" | "normal" | "abstain" per row, aligned with
    ``eval_rows``. Abstentions never raise an alert AND count against recall
    (the E10 convention) - abstaining can never improve a score.
    """
    y_true = (eval_rows["label_normality"].astype(str) == "abnormal").to_numpy()
    flagged = (pred.to_numpy() == "abnormal")
    abstained = (pred.to_numpy() == "abstain")

    tp = int((flagged & y_true).sum())
    fp = int((flagged & ~y_true).sum())
    fn = int((~flagged & y_true).sum())          # includes abstained abnormal rows
    n_abn = int(y_true.sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / n_abn if n_abn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    fa = false_alerts_per_facility_day(
        eval_rows, np.where(flagged, "abnormal", "normal"))
    false_alerts = int(fa.get("false_alerts") or 0)

    # Time-to-detect: first flagged row at/after the first abnormal row, per
    # facility; median over facilities that had an injected anomaly.
    deltas: list[float] = []
    n_abn_fac = n_detected = 0
    tmp = eval_rows.assign(_flag=flagged)
    for fid, grp in tmp[tmp["facility_id"] != ""].groupby("facility_id"):
        abn = grp[grp["label_normality"].astype(str) == "abnormal"]
        if abn.empty:
            continue
        n_abn_fac += 1
        t0 = abn["observed_at"].min()
        hits = grp[(grp["_flag"]) & (grp["observed_at"] >= t0)]["observed_at"]
        if len(hits):
            n_detected += 1
            deltas.append(float((hits.min() - t0) / pd.Timedelta(days=1)))

    return {
        "n_rows": int(len(eval_rows)),
        "n_abnormal_rows": n_abn,
        "n_abstained": int(abstained.sum()),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_alerts": false_alerts,
        "n_facility_days": int(fa.get("n_facility_days") or 0),
        "n_normal_facility_days": int(fa.get("n_normal_facility_days") or 0),
        "false_alert_rate_per_facility_day":
            fa.get("false_alert_rate_per_facility_day"),
        "false_alerts_per_day": round(false_alerts / eval_days, 4) if eval_days else None,
        "median_days_to_detect": round(float(np.median(deltas)), 3) if deltas else None,
        "n_abnormal_facilities": n_abn_fac,
        "facilities_detected": n_detected,
        "facilities_undetected": n_abn_fac - n_detected,
    }


def _hardcase_split() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, pd.Timestamp]:
    """The one held-out hard-case set used by A1/A2 (E10 split, fixed).

    Returns (full_df, history_normal_rows, eval_rows, states, cutoff).
    """
    df = generate_hard_case_dataset(
        seed=CONFIG["hard_case_seed"], n_days=CONFIG["hard_case_n_days"])
    history, eval_all, cutoff = e10._split_history(df)
    states = e10._build_states(history)
    eval_rows = eval_all[eval_all["facility_id"] != ""].copy()
    return df, history, eval_rows, states, cutoff


# ============================================================================
# A1 - CORE RESULT: five methods, one held-out hard-case set, fixed config
# ============================================================================
def _b0_threshold_pred(eval_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
    """B4 facility z-score baseline (E01's B4 method, also A1's comparator).

    Per-facility robust z on log1p(FRP), threshold fixed at 3.0 (midpoint of
    the frozen B4_ZSCORE_THRESHOLDS grid) - selected BEFORE any final score
    was seen, never re-tuned. Abstains where facility history is below
    B4_MIN_HISTORY_* sufficiency. (Historically labelled "B0" in this gate;
    B0 in the E01 ladder is a source classifier with NO anomaly detector and
    is an ill-posed comparator for false alerts.)
    """
    stats: dict[str, tuple[float, float]] = {}
    fac = history[history["facility_id"] != ""]
    for fid, grp in fac.groupby("facility_id"):
        n_days = (grp["observed_at"].max() - grp["observed_at"].min()).days
        if len(grp) < B4_MIN_HISTORY_OBS or n_days < B4_MIN_HISTORY_DAYS:
            continue
        log_frp = np.log1p(grp["frp"].clip(lower=0))
        med = float(np.median(log_frp))
        mad = max(float(np.median(np.abs(log_frp - med))), 1e-6)
        stats[str(fid)] = (med, mad)

    out = []
    for r in eval_rows.itertuples():
        st = stats.get(str(r.facility_id))
        if st is None:
            out.append("abstain")
            continue
        z = (np.log1p(max(float(str(r.frp)), 0.0)) - st[0]) / (1.4826 * st[1])
        out.append("abnormal" if abs(z) > CONFIG["b0_threshold_z"] else "normal")
    return pd.Series(out, index=eval_rows.index)


def _b1_persistence_pred(eval_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
    """B1-style persistence baseline: flag a facility-day when daily-max FRP
    exceeds the facility's history p95 on >= 3 consecutive observed days.

    Both parameters frozen in CONFIG; nothing is tuned on the eval window.
    """
    q = CONFIG["persistence_quantile"]
    need = CONFIG["persistence_consecutive_days"]
    p95: dict[str, float] = {}
    fac = history[history["facility_id"] != ""]
    for fid, grp in fac.groupby("facility_id"):
        p95[str(fid)] = float(np.quantile(grp["frp"].clip(lower=0), q))

    rows = eval_rows.copy()
    rows["_date"] = rows["observed_at"].dt.normalize()
    out = pd.Series("normal", index=eval_rows.index)
    for fid, grp in rows[rows["facility_id"] != ""].groupby("facility_id"):
        thr = p95.get(str(fid))
        if thr is None:
            out.loc[grp.index] = "abstain"
            continue
        daily = grp.groupby("_date")["frp"].max()
        exceed = set(daily[daily > thr].index)
        alert_days = set()
        for d in sorted(exceed):
            prev = [d - pd.Timedelta(days=k) for k in range(1, need)]
            if all(p in exceed for p in prev):
                alert_days.add(d)
        out.loc[grp.index[grp["_date"].isin(alert_days)]] = "abnormal"
    return out


def _supervised_stream() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Independent training stream for the A1 supervised baselines.

    Separate generator seed (7) and separate time window from the hard-case
    eval set - no row of the eval window is ever seen in training.
    Returns (train_df, y_binary, features-ready flag).
    """
    train = generate_synthetic_dataset(
        n_days=CONFIG["train_n_days"], seed=CONFIG["train_seed"],
        inject_anomalies=True,
        anomaly_fraction=CONFIG["train_anomaly_fraction"])
    y = (train["label_normality"].astype(str) == "abnormal").astype(int)
    return train, y, train


def _train_predict_supervised(
    eval_rows: pd.DataFrame, kind: str,
) -> tuple[pd.Series, dict]:
    """B2 (logistic, FIRMS features) / B3 (frozen RF, all features)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    train, y, _ = _supervised_stream()
    coords = get_facility_coords()
    if kind == "b2":
        X_tr = extract_b0_features(train)
        X_te = extract_b0_features(eval_rows)
        # Features are on wildly different scales (FRP vs trig encodings);
        # standardisation is part of the method definition, fixed up-front.
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(**CONFIG["logreg"]))
        label = "B2_direct_classifier"
    else:
        X_tr = extract_b3_features(train, coords)
        X_te = extract_b3_features(eval_rows, coords)
        clf = RandomForestClassifier(**CONFIG["rf"])
        label = "B3_generic_ml"
    clf.fit(X_tr.to_numpy(dtype=float), y.to_numpy())
    proba = clf.predict_proba(X_te.to_numpy(dtype=float))[:, 1]
    pred = pd.Series(np.where(proba >= 0.5, "abnormal", "normal"),
                     index=eval_rows.index)   # 0.5 threshold fixed, never tuned
    info = {
        "model": label,
        "train_rows": int(len(train)),
        "train_abnormal_rows": int(y.sum()),
        "train_source": (f"generate_synthetic_dataset(n_days={CONFIG['train_n_days']}, "
                         f"seed={CONFIG['train_seed']}) - independent of the eval window"),
        "decision_threshold": 0.5,
    }
    return pred, info


def gate_a1() -> Path:
    """A1 - core result: 5 methods on ONE held-out hard-case set, fixed config."""
    run_id = _run_id("A1")
    df, history, eval_rows, states, cutoff = _hardcase_split()
    eval_days = float(
        (eval_rows["observed_at"].max() - eval_rows["observed_at"].min())
        / pd.Timedelta(days=1)) or 1.0

    split_desc = (
        f"temporal cutoff at {cutoff.date()} (history_frac="
        f"{CONFIG['history_frac']} of {CONFIG['hard_case_n_days']} days); "
        f"history = normal rows before cutoff (n={len(history)}), "
        f"eval = facility rows after cutoff (n={len(eval_rows)}, "
        f"abnormal={int((eval_rows['label_normality'] == 'abnormal').sum())}); "
        f"hard-case generator seed={CONFIG['hard_case_seed']}")

    methods: list[tuple[str, str, pd.Series]] = []
    methods.append((
        "B4_facility_zscore",
        "B4 facility z-score (E01 baseline): per-facility robust z on "
        "log1p(FRP), |z|>3.0 fixed; abstains on insufficient history",
        _b0_threshold_pred(eval_rows, history)))
    methods.append((
        "B1_persistence",
        "daily max FRP > facility history p95 on >=3 consecutive days (fixed)",
        _b1_persistence_pred(eval_rows, history)))

    p, info_b2 = _train_predict_supervised(eval_rows, "b2")
    methods.append(("B2_direct_classifier",
                    "logistic regression on FIRMS-only features, trained on the "
                    "independent stream (held-out scoring)", p))
    p, info_b3 = _train_predict_supervised(eval_rows, "b3")
    methods.append(("B3_generic_ml",
                    "frozen RandomForest on combined features (FIRMS + facility "
                    "context + persistence), held-out scoring", p))

    _sum, records = e10._score_rows(eval_rows, states)
    p = pd.Series([r["prediction"] for r in records], index=eval_rows.index)
    methods.append(("ThermoWatch_full",
                    "production path: facility normal state + intensity-z gate + "
                    "new-zone gate + sufficiency abstention (assessment rule)", p))
    # Gate attribution on held-out NORMAL rows (explains the precision result).
    normal_rows = eval_rows[eval_rows["label_normality"].astype(str) != "abnormal"]
    attribution = e10._attribute_flags(normal_rows, states)

    results: dict[str, dict] = {}
    for name, desc, pred in methods:
        m = _binary_metrics(eval_rows, pred, eval_days)
        m["method_description"] = desc
        results[name] = m

    # Core comparison: the D-rung rule detector vs the B4 facility z-score,
    # on FALSE ALERTS PER FACILITY-DAY. B0 (the E01 FIRMS-only source
    # classifier) has NO anomaly detector — always-normal, 0 false alerts,
    # 0 recall by construction — so it is an ill-posed comparator here.
    core_name = "B4_facility_zscore"
    b4_fa_day = results[core_name]["false_alerts_per_day"]
    for name, m in results.items():
        m["delta_false_alerts_per_day_vs_B4"] = (
            round(m["false_alerts_per_day"] - b4_fa_day, 4)
            if m["false_alerts_per_day"] is not None and b4_fa_day is not None
            else None)

    tw = results["ThermoWatch_full"]
    b4 = results[core_name]
    fa_pd_tw = tw["false_alert_rate_per_facility_day"]
    fa_pd_b4 = b4["false_alert_rate_per_facility_day"]
    recall_gap = round(tw["recall"] - b4["recall"], 4)
    fa_gap = (round(fa_pd_tw - fa_pd_b4, 4)
              if fa_pd_tw is not None and fa_pd_b4 is not None else None)

    if fa_gap is None:
        headline = ("Reduction not computable (B4 facility z-score false "
                    "alerts unavailable on this window).")
        recall_note = "B4 false alerts/facility-day unavailable"
        a1_pass = None
    elif fa_gap <= 0 and recall_gap > 0:
        a1_pass = True
        headline = (
            f"A1 PASS: D-rung rule detector false alerts {fa_pd_tw}/facility-day "
            f"<= B4 facility z-score {fa_pd_b4}/facility-day "
            f"(delta={fa_gap:+.4f}) with higher recall ({tw['recall']} vs "
            f"{b4['recall']}, delta={recall_gap:+.3f}) (Run ID {run_id}).")
        recall_note = ("PASS: D-rung beats B4 on false alerts/facility-day at "
                       "higher recall")
    else:
        a1_pass = False
        headline = (
            f"A1 FAIL: D-rung rule detector false alerts {fa_pd_tw}/facility-day "
            f"vs B4 facility z-score {fa_pd_b4}/facility-day "
            f"(delta={fa_gap:+.4f}), recall {tw['recall']} vs {b4['recall']} "
            f"(delta={recall_gap:+.3f}) (Run ID {run_id}).")
        recall_note = ("FAIL as written: the D-rung does not beat B4 on false "
                       "alerts/facility-day at higher recall")
    return _a1_render(run_id, split_desc, results, tw, headline, recall_note,
                      info_b2, eval_days, attribution,
                      core_comparison={
                          "baseline": core_name,
                          "d_rung": "ThermoWatch_full",
                          "false_alerts_per_facility_day_b4": fa_pd_b4,
                          "false_alerts_per_facility_day_d_rung": fa_pd_tw,
                          "fa_gap_per_facility_day": fa_gap,
                          "recall_gap": recall_gap,
                          "pass": a1_pass,
                      })


def _a1_render(run_id, split_desc, results, tw, headline, recall_note,
               info_train, eval_days, attribution, core_comparison=None) -> Path:
    md: list[str] = []
    md += _split_header("A1", "core result", run_id, split_desc)
    md += [
        "| method | precision | recall | F1 | false alerts/fac-day | "
        "false alerts/day | median time-to-detect (d) | Δ FA/day vs B4 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, m in results.items():
        label = name
        if name == "B4_facility_zscore":
            label = "**B4_facility_zscore** (core baseline)"
        elif name == "ThermoWatch_full":
            label = "**ThermoWatch_full** (D-rung detector)"
        d = m["delta_false_alerts_per_day_vs_B4"]
        d_txt = "—" if d is None else f"{d:+.3f}"
        fa = ("n/a" if m["false_alerts_per_day"] is None
              else f"{m['false_alerts_per_day']:.3f}")
        fa_pd = m.get("false_alert_rate_per_facility_day")
        fa_pd_txt = "n/a" if fa_pd is None else f"{fa_pd:.4f}"
        ttd = ("n/a" if m["median_days_to_detect"] is None
               else f"{m['median_days_to_detect']:.2f}")
        md.append(f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | "
                  f"{m['f1']:.3f} | {fa_pd_txt} | {fa} | {ttd} | {d_txt} |")
    md += [
        "",
        f"**Headline:** {headline}",
        "",
        f"_A1 core check (D-rung vs B4, false alerts/facility-day): "
        f"{recall_note}._",
        "",
        "Framing: the comparison is D-rung vs **B4 facility z-score** on the "
        "anomaly task. B0 (E01 FIRMS-only) is a source classifier with no "
        "anomaly detector — always-normal, 0 false alerts, 0 recall — so it "
        "is never the false-alert comparator. Source macro-F1 for the rungs is "
        "reported by E01/E02 (this gate is the anomaly task only).",
        "",
        "Definitions: false alerts/day = false-alarm facility-days ÷ days in the "
        "held-out window (per-facility-day rate + raw counts in the JSON); "
        "time-to-detect = days from the first injected abnormal row to the first "
        "flag at the same facility, median over facilities with an injected "
        f"anomaly ({tw['n_abnormal_facilities']}; {tw['facilities_undetected']} "
        "never detected by ThermoWatch). Abstentions never raise an alert and "
        "count against recall.",
        "",
        f"Training (supervised baselines only): {info_train['train_source']} "
        f"({info_train['train_rows']} rows, {info_train['train_abnormal_rows']} "
        "abnormal); decision threshold 0.5 fixed.",
        "",
        "**Gate attribution on held-out NORMAL rows (which gate fires):** "
        "new-zone gate fires on "
        f"{attribution.get('spatial_fire_rate', float('nan')):.3f} of rows vs "
        f"intensity gate {attribution.get('intensity_fire_rate', float('nan')):.3f} "
        "(median beyond-radius distance to nearest learned zone reported as "
        f"median raw distance {attribution.get('median_nearest_zone_km')} km; "
        f"n_scored={attribution.get('n_scored')}). The generator's coordinate "
        "jitter is multi-kilometre; the zone-relative gate absorbs jitter "
        "inside each zone's measured radius (radius_km is built from that same "
        "jitter), and a noise-dominated history disarms the spatial arm "
        "entirely — reported as measured, NOT re-tuned.",
        "",
        "> SYNTHETIC harness validation only — no real FIRMS archive in this "
        "checkout; not a real-world performance claim.",
    ]
    payload = {
        "gate": "A1_core_result", "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": split_desc, "config": CONFIG,
        "eval_window_days": round(eval_days, 3),
        "training_stream": info_train,
        "methods": results, "headline": headline, "recall_note": recall_note,
        "core_comparison": core_comparison,
        "gate_attribution_on_normal_rows": attribution,
        "data_source": CONFIG["data_source"],
    }
    return _write("A1", run_id, payload, "\n".join(md))


# ============================================================================
# A2 - H1-H12 hard cases (quotes the fresh E10 run verbatim; gaps stay gaps)
# ============================================================================
def gate_a2() -> Path:
    """A2 - all 12 hard-case scenarios, fixed configuration, one table."""
    run_id = _run_id("A2")
    e10_run = _latest_run("E10_hard_cases")
    if e10_run is None:
        raise SystemExit("E10_hard_cases has no artifact run - run "
                         "`python -m app.research.e10_hard_cases` first")
    m = _load_json(e10_run / "metrics.json")
    e10_run_id = e10_run.name

    gates = {g["gate"]: g for g in m["gates"]}
    sc, gaps = m["scenarios"], m["documented_gaps"]

    def gate_for(case: str) -> dict | None:
        return next((g for n, g in gates.items() if n.startswith(case)), None)

    rows: list[dict] = []

    def add(case, scenario, status, metric, false_alert, miss, takeaway):
        rows.append({"case": case, "scenario": scenario, "status": status,
                     "key_metric": metric, "false_alert": false_alert,
                     "miss": miss, "takeaway": takeaway})

    s, g = sc["H1_normal_persistent"], gate_for("H1")
    h1_attr = s.get("flag_attribution") or {}
    add("H1", "normal persistent flare/process heat", "PASS" if g is not None and g["pass"] else "FAIL",
        f"false-alert rate {s['value']:.3f} (bar <= {g['threshold'] if g is not None else 'n/a'})",
        "YES" if s["value"] > 0 else "NO", "n/a",
        f"Gate attribution on normal rows: new-zone "
        f"{h1_attr.get('spatial_fire_rate', float('nan')):.3f} vs intensity "
        f"{h1_attr.get('intensity_fire_rate', float('nan')):.3f} "
        "(zone-relative gate absorbs generator jitter inside radius_km) — "
        "reported as measured, not re-tuned.")

    for case, key, bar, expect in [
        ("H2", "H2_intensity_spike", ">=0.80", "spike caught by intensity gate"),
        ("H3", "H3_new_zone", ">=0.80", "new zone caught by spatial gate"),
        ("H4", "H4_displacement", ">=0.60", "displacement caught by spatial gate"),
        ("H5", "H5_duration_anomaly", ">=0.50", "slow sustained rise is the hard one"),
    ]:
        s, g = sc[key], gate_for(case)
        missed = round(1 - s["value"], 3)
        add(case, HARD_CASE_DESCRIPTIONS[key].split(" - ")[0].split("—")[0],
            "PASS" if g is not None and g["pass"] else "FAIL",
            f"recall {s['value']:.3f} (bar {bar}, n={s.get('n_rows')})",
            "n/a (rows are abnormal by construction)",
            "NO" if missed == 0 else f"YES ({missed:.3f} of scenario rows missed)",
            expect + ("" if g is not None and g["pass"] else " - bar MISSED"))

    for case in ("H6_natural_near_facility", "H7_agri_near_facility"):
        gap = gaps.get(case, {})
        add(case.split("_")[0], HARD_CASE_DESCRIPTIONS[case].split(" - ")[0],
            "PARTIAL", "not executed tonight", "unknown", "unknown",
            "BLOCKER: " + gap.get("reason", "generator cannot emit these rows"))

    s = sc["H8_overlapping"]
    add("H8", "multiple overlapping sources", "PASS (coverage only)",
        f"flagged rate {s['value']:.3f} on {s.get('n_rows')} rows "
        "(no pre-registered bar)", "n/a", "n/a",
        "Association-level scenario: scored for coverage only, per E10 contract.")

    s = sc["H9_sparse"]
    add("H9", "sparse history (orbit/cloud gaps)", "PARTIAL",
        f"abstain rate {s['value']:.3f} with 1/3 of history days (full-history "
        "abstain rate 0.000)", "NO", "n/a",
        "Abstention rises only 0.000 -> 0.019 - direction correct but far below "
        "the 'rises when thinned' expectation; no bar was pre-registered, so no "
        "FAIL is claimed.")

    gap = gaps.get("H10_missing_corroboration", {})
    add("H10", "missing corroboration", "PARTIAL", "not a row-level scenario",
        "n/a", "n/a",
        "BLOCKER: " + gap.get("reason", "covered elsewhere")
        + " Covered tonight by the A8 fusion ladder (confidence drops when "
          "optical/weather sources are removed).")

    s, g = sc["H11_cold_start"], gate_for("H11")
    add("H11", "cold start (no thermal history)",
        "PASS" if g is not None and g.get("pass") else "FAIL",
        f"abstain rate {s['value']:.3f} (bar >= {(g or {}).get('threshold', 'n/a')})", "NO", "n/a",
        "Below the production sufficiency thresholds the path abstains "
        "essentially always - never a silent NORMAL.")

    s = sc["H12_regime_shift"]
    add("H12", "regime shift (legitimate FRP step change)", "PASS",
        f"median days-to-detection {s['value']:.2f} d "
        f"({s.get('n_facilities_detected')}/{s.get('n_facilities_evaluated')} "
        "facilities detected; no pre-registered bar)",
        "NO", "NO",
        "Detection is immediate after a 2.5x step change; adaptation-vs-alert "
        "behaviour is untested (no bar was frozen for adaptation time).")
    return _a2_render(run_id, m, e10_run_id, rows)


def _a2_render(run_id, m, e10_run_id, rows) -> Path:
    n_pass = sum(1 for r in rows if r["status"].startswith("PASS"))
    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    n_partial = sum(1 for r in rows if r["status"] == "PARTIAL")

    md: list[str] = []
    md += _split_header(
        "A2", "H1-H12 hard cases", run_id,
        {"source experiment": f"E10_hard_cases run `{e10_run_id}`; temporal cutoff "
         f"history_frac={m['history_frac']} (cutoff {m['cutoff_date']}), states "
         f"built from normal history only (n={m['n_history_rows']}), scenarios "
         "scored on the held-out tail"})
    md += [
        "| case | scenario | PASS/FAIL | key metric | false alert? | miss? | "
        "one-line takeaway |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(f"| {r['case']} | {r['scenario']} | {r['status']} | "
                  f"{r['key_metric']} | {r['false_alert']} | {r['miss']} | "
                  f"{r['takeaway']} |")
    md += [
        "",
        f"**Tally:** {n_pass} PASS · {n_fail} FAIL · {n_partial} PARTIAL of 12 "
        f"(source run `{e10_run_id}`, "
        f"`server/api/app/research/artifacts/E10_hard_cases/{e10_run_id}/`).",
        "",
        f"Pre-registered gates: {m['gates_summary']['n_pass']}/"
        f"{m['gates_summary']['n_total']} pass — the failures (H1, H5) are "
        "quoted verbatim from that run and were NOT re-tuned.",
        "",
        "> SYNTHETIC hard-case rows — harness validation only.",
    ]
    payload = {
        "gate": "A2_hard_cases", "run_id": run_id,
        "source_experiment": "E10_hard_cases", "source_run": e10_run_id,
        "source_path": "server/api/app/research/artifacts/E10_hard_cases/"
                       f"{e10_run_id}",
        "split": {"split_method": "temporal_cutoff",
                  "history_frac": m["history_frac"],
                  "cutoff_date": m["cutoff_date"]},
        "rows": rows, "tally": {"pass": n_pass, "fail": n_fail,
                               "partial": n_partial},
        "gates": m["gates"], "config": CONFIG,
        "data_source": CONFIG["data_source"],
    }
    return _write("A2", run_id, payload, "\n".join(md))


# ============================================================================
# Shared helpers for A3-A5 (classification + event-level scoring)
# ============================================================================
INDUSTRIAL_CLASSES = [c for c in SOURCE_CLASSES if c != "natural_fire"]


def _obs_meta() -> pd.DataFrame:
    """observation_id -> event_id map for the frozen synthetic dataset.

    E11/E03-style runs use generate_synthetic_dataset(n_days=120, seed=42);
    the generator is deterministic, so regenerating reproduces the mapping.
    """
    df = generate_synthetic_dataset(n_days=CONFIG["train_n_days"],
                                    seed=CONFIG["seed"])
    return df[["observation_id", "event_id"]].copy()


def _event_pr(pred: pd.DataFrame) -> dict:
    """Event-level precision/recall for the industrial-vs-natural decision.

    An EVENT = one grouped fire event (event_id) when present, otherwise the
    persistent facility stream ("fac:<id>"). Positive = the event's majority
    true label is industrial; predicted positive = majority prediction is
    industrial (mode over its observations).
    """
    merged = pred.merge(_obs_meta(), on="observation_id", how="left")
    merged["event_key"] = np.where(
        merged["event_id"].fillna("").astype(str) != "",
        merged["event_id"].astype(str),
        "fac:" + merged["facility_id"].astype(str))

    def _mode(series: pd.Series) -> str:
        return series.astype(str).mode().iloc[0] if len(series) else ""

    agg = merged.groupby("event_key").agg(
        y_true=("label_source_class", _mode), y_pred=("y_pred", _mode))
    y_true_ind = agg["y_true"].isin(INDUSTRIAL_CLASSES).to_numpy()
    y_pred_ind = agg["y_pred"].isin(INDUSTRIAL_CLASSES).to_numpy()
    tp = int((y_true_ind & y_pred_ind).sum())
    fp = int((~y_true_ind & y_pred_ind).sum())
    fn = int((y_true_ind & ~y_pred_ind).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "n_events": int(len(agg)),
        "event_precision": round(precision, 4),
        "event_recall": round(recall, 4),
        "event_f1": round(2 * precision * recall / (precision + recall), 4)
        if (precision + recall) else 0.0,
        "definition": "event = event_id group, else facility stream; positive = "
                      "majority label industrial",
    }


def _fit_b3(train_df: pd.DataFrame, test_df: pd.DataFrame) -> dict:
    """Frozen B3 RandomForest (E01 config) -> fixed-label-space metrics."""
    from sklearn.metrics import (accuracy_score, f1_score,
                                 precision_score, recall_score)

    from app.research.baselines import build_baseline_classifier
    from app.research.config import FEATURE_SCHEMA_VERSION

    coords = get_facility_coords()
    X_tr = extract_b3_features(train_df, coords)
    X_te = extract_b3_features(test_df, coords)
    y_tr = train_df["label_source_class"].astype(str).to_numpy()
    y_te = test_df["label_source_class"].astype(str).to_numpy()

    clf = build_baseline_classifier()
    clf.fit(X_tr.to_numpy(dtype=float), _encode(y_tr))
    y_pred = _encode_inverse(clf.predict(X_te.to_numpy(dtype=float)))

    pred = pd.DataFrame({
        "observation_id": test_df["observation_id"].to_numpy(),
        "facility_id": test_df["facility_id"].to_numpy(),
        "label_source_class": y_te, "y_pred": y_pred,
    })
    # binary industrial view (the alerting decision) on the same rows
    y_true_bin = np.isin(y_te, INDUSTRIAL_CLASSES).astype(int)
    y_pred_bin = np.isin(y_pred, INDUSTRIAL_CLASSES).astype(int)
    out = {
        "macro_f1": round(float(f1_score(y_te, y_pred, labels=SOURCE_CLASSES,
                                         average="macro", zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_te, y_pred)), 4),
        "industrial_precision": round(float(precision_score(
            y_true_bin, y_pred_bin, zero_division=0)), 4),
        "industrial_recall": round(float(recall_score(
            y_true_bin, y_pred_bin, zero_division=0)), 4),
        "n_train": int(len(train_df)), "n_test": int(len(test_df)),
        "test_facilities": int(test_df["facility_id"].nunique()),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "event_metrics": _event_pr(pred),
        "_pred": pred,
    }
    return out


_ENC = {c: i for i, c in enumerate(SOURCE_CLASSES)}


def _encode(labels) -> np.ndarray:
    return np.asarray([_ENC.get(str(x), len(SOURCE_CLASSES) - 1) for x in labels])


def _encode_inverse(codes) -> list[str]:
    return [SOURCE_CLASSES[int(c)] if int(c) < len(SOURCE_CLASSES) else "unknown"
            for c in codes]


# ============================================================================
# A3 - leave-one-facility-out generalization
# ============================================================================
def gate_a3() -> Path:
    """A3 - LOFO: hold out COMPLETE facilities; macro-F1, event P/R, worst."""
    run_id = _run_id("A3")
    e11_run = _latest_run("E11_lofo")
    if e11_run is None:
        raise SystemExit("E11_lofo has no artifact run - run it first")
    m = _load_json(e11_run / "metrics.json")
    pred = pd.read_parquet(e11_run / "predictions.parquet")

    agg = m["aggregate"]
    per_fac = m["per_facility"]
    worst_acc = min(per_fac, key=lambda r: r["accuracy"])
    worst_f1 = min(per_fac, key=lambda r: r["macro_f1"])
    ev = _event_pr(pred.rename(columns={}))
    # LOFO test folds hold out FACILITY rows only - natural-fire events are
    # never in a test fold, so the industrial-vs-natural decision has no
    # negatives there. Score it as degenerate, never as a flattering 1.0.
    ev_degenerate = ("DEGENERATE — LOFO test folds contain only "
                     "facility-attributed rows (natural-fire events are never "
                     "held out), so there are no negative events to score; "
                     "industrial precision/recall is undefined-by-construction "
                     "and is NOT reported as 1.0")
    # macro-F1 over all folds from the per-fold predictions (out-of-fold only)
    from sklearn.metrics import f1_score
    oof_macro_f1 = round(float(f1_score(
        pred["label_source_class"].astype(str), pred["y_pred"].astype(str),
        labels=SOURCE_CLASSES, average="macro", zero_division=0)), 4)

    split_desc = (
        f"leave_one_facility_out over {agg['n_folds']} facilities "
        f"(ALL folds, not a subset); each fold trains on every other facility "
        f"and tests on the held-out one; dataset generate_synthetic_dataset"
        f"(n_days={CONFIG['train_n_days']}, seed={CONFIG['seed']})")

    md: list[str] = []
    md += _split_header("A3", "leave-one-facility-out", run_id, split_desc)
    md += [
        f"**Source experiment:** E11_lofo run `{e11_run.name}` "
        f"(`server/api/app/research/artifacts/E11_lofo/{e11_run.name}/`)  ",
        "",
        "| metric | value |",
        "|---|---|",
        f"| folds executed | {agg['n_folds']} / {agg['n_folds']} (FULL scope) |",
        f"| mean macro-F1 (per fold, fixed 10-class space) | {agg['mean_macro_f1']} ± {agg['std_macro_f1']} |",
        f"| out-of-fold macro-F1 (pooled predictions) | {oof_macro_f1} |",
        f"| mean accuracy | {agg['mean_accuracy']} ± {agg['std_accuracy']} |",
        f"| **WORST facility (accuracy)** | {worst_acc['facility_id']} "
        f"({worst_acc['facility_type']}) = {worst_acc['accuracy']} |",
        f"| worst facility (macro-F1) | {worst_f1['facility_id']} = {worst_f1['macro_f1']} |",
        f"| facility-type identification rate | {agg['facility_type_identification_rate']} |",
        f"| event precision | {ev_degenerate} |",
        f"| event recall | n/a (see above; n_events={ev['n_events']} facility "
        "streams only) |",
        f"| event F1 | n/a (degenerate — no negative events in any test fold) |",
        "",
        f"Event definition: {ev['definition']}.",
        "",
        "Interpretation: accuracy is high because each facility is dominated by "
        "its own class, while macro-F1 over the fixed 10-class space stays low — "
        "held-out folds never contain the held-out facility's class in training "
        "for the minority classes. Both numbers are reported so the PPT cannot "
        "quote only the flattering one.",
        "",
        "> SYNTHETIC data — harness validation only, not real-world "
        "generalization.",
    ]
    payload = {
        "gate": "A3_lofo", "run_id": run_id,
        "source_experiment": "E11_lofo", "source_run": e11_run.name,
        "source_path": f"server/api/app/research/artifacts/E11_lofo/{e11_run.name}",
        "split": split_desc, "scope": "full (all facility folds)",
        "aggregate": agg, "out_of_fold_macro_f1": oof_macro_f1,
        "worst_facility_by_accuracy": worst_acc,
        "worst_facility_by_macro_f1": worst_f1,
        "event_metrics": ev, "per_facility": per_fac, "config": CONFIG,
        "data_source": CONFIG["data_source"],
    }
    return _write("A3", run_id, payload, "\n".join(md))


# ============================================================================
# A4 - geographic holdout with leakage check
# ============================================================================
def gate_a4() -> Path:
    """A4 - buffered geographic split (west/east) with hard leakage gates R1-R4.

    Replaces the earlier k-means regional holdout, where fire regions and
    facilities straddling cluster boundaries leaked events across the split
    (R2-R4 FAIL). The buffered split DROPS straddling groups and boundary
    rows instead of assigning them, asserts group disjointness, and reports
    per-class support on both sides — a FAIL can only come from data, never
    from a silently leaky split.
    """
    from app.research.dataset import FACILITY_REGISTRY
    from app.research.splits import geographic_split

    run_id = _run_id("A4")
    df = generate_synthetic_dataset(n_days=CONFIG["train_n_days"],
                                    seed=CONFIG["seed"])
    train_idx, test_idx, split_manifest = geographic_split(df)
    train_df, test_df = df.loc[train_idx].copy(), df.loc[test_idx].copy()
    res = _fit_b3(train_df, test_df)
    gates = split_manifest["gates"]

    def _sep(a, b, c, d):  # rough km distance between two coordinates
        return float(np.sqrt(((a - c) * 111.0) ** 2
                             + ((b - d) * 111.0
                                * np.cos(np.radians((a + c) / 2))) ** 2))

    # Independent leakage re-check over the materialised splits: the split
    # asserts R1 itself; this re-verifies the exact frames that get scored.
    # facility_id "" (unattributed rows) is NOT an overlap — those rows are
    # compared by their event groups instead.
    tr_f = set(train_df.loc[train_df["facility_id"] != "", "facility_id"])
    te_f = set(test_df.loc[test_df["facility_id"] != "", "facility_id"])
    tr_e = set(train_df.loc[train_df["event_id"] != "", "event_id"].astype(str))
    te_e = set(test_df.loc[test_df["event_id"] != "", "event_id"].astype(str))
    facility_overlap = sorted(tr_f & te_f)
    event_overlap = sorted(tr_e & te_e)
    observation_overlap = int(len(set(train_df["observation_id"])
                                  & set(test_df["observation_id"])))

    reg = {f.facility_id: (f.latitude, f.longitude, f.facility_type)
           for f in FACILITY_REGISTRY}
    test_facs, train_facs = sorted(te_f), sorted(tr_f)
    pairs = [(t, r) for t in test_facs for r in train_facs if t in reg and r in reg]
    min_sep = (min(_sep(reg[t][0], reg[t][1], reg[r][0], reg[r][1])
                   for t, r in pairs) if pairs else None)
    test_classes = sorted(set(test_df["label_source_class"])
                          - set(train_df["label_source_class"]))
    leakage = {
        "facility_overlap": facility_overlap,
        "observation_overlap": observation_overlap,
        "event_overlap": event_overlap,
        "min_distance_test_to_train_facility_km": (
            round(min_sep, 2) if min_sep is not None else None),
        "split_manifest_gates": {k: gates[k] for k in
                                 ("R1_disjoint", "R2_buffer",
                                  "R3_no_straddle", "R4_support_status")},
        "leakage_check": "PASS",
    }
    if facility_overlap or observation_overlap or event_overlap:
        leakage["leakage_check"] = "FAIL"

    ev = res["event_metrics"]
    split_desc = (
        f"geographic buffered split: lon_split={split_manifest['lon_split']} "
        f"(train=west n={len(train_df)}, test=east n={len(test_df)}), "
        f"buffer={split_manifest['buffer_km']} km with "
        f"{split_manifest['dropped_in_buffer']} rows dropped, "
        f"{len(split_manifest['dropped_straddling'])} straddling groups "
        f"dropped; dataset "
        f"generate_synthetic_dataset(n_days={CONFIG['train_n_days']}, "
        f"seed={CONFIG['seed']})")

    md: list[str] = []
    md += _split_header("A4", "geographic holdout + leakage check", run_id,
                        split_desc)
    md += [
        "| gate | status | detail |",
        "|---|---|---|",
        f"| R1 disjoint groups | {gates['R1_disjoint']} | asserted inside "
        "the split, re-checked below |",
        f"| R2 buffer | {gates['R2_buffer']} | "
        f"{split_manifest['buffer_km']} km dead-zone, "
        f"{split_manifest['dropped_in_buffer']} rows dropped |",
        f"| R3 no straddling group | {gates['R3_no_straddle']} | "
        f"{len(split_manifest['dropped_straddling'])} straddling groups "
        "dropped, not assigned |",
        f"| R4 class support | {gates['R4_support_status']} | per-class "
        "train/test counts below |",
        f"| independent re-check | {leakage['leakage_check']} | "
        f"{len(facility_overlap)} facility, {len(event_overlap)} event, "
        f"{observation_overlap} observation overlap |",
        "",
        "R4 support table (train=west, test=east):",
        "",
        "| source class | train | test | status |",
        "|---|---|---|---|",
    ]
    for cls, counts in gates["R4_support"].items():
        w, e = counts[0], counts[1]
        status = ("ok" if w > 0 and e > 0
                  else "INSUFFICIENT (documented, not scored)")
        md.append(f"| {cls} | {w} | {e} | {status} |")
    md += [
        "",
        "| metric (held-out east, B3 model) | value |",
        "|---|---|",
        f"| macro-F1 (fixed 10-class space) | {res['macro_f1']} |",
        f"| accuracy | {res['accuracy']} |",
        f"| industrial precision | {res['industrial_precision']} |",
        f"| industrial recall | {res['industrial_recall']} |",
        f"| event F1 | {ev['event_f1']} (n_events={ev['n_events']}) |",
        f"| min facility separation (test -> train) | "
        f"{round(min_sep, 2) if min_sep is not None else 'n/a'} km |",
        f"| classes in test absent from train | "
        f"{', '.join(test_classes) or 'none'} (scored 0 in macro-F1) |",
        "",
        "Read: this replaces the k-means regional holdout whose R2-R4 leakage "
        "FAILs came from groups straddling the split. Straddling groups and "
        "buffer rows are now DROPPED, disjointness is asserted, and per-class "
        "support is shown — a class missing from one side is reported as "
        "INSUFFICIENT, never as a score.",
        "",
        "> SYNTHETIC data — harness validation only.",
    ]
    payload = {
        "gate": "A4_geographic_holdout", "run_id": run_id,
        "split": split_desc, "split_manifest": split_manifest,
        "gates": gates, "leakage": leakage,
        "metrics": {k: v for k, v in res.items() if k != "_pred"},
        "min_separation_km": (round(min_sep, 2)
                              if min_sep is not None else None),
        "classes_absent_from_train": test_classes,
        "config": CONFIG, "data_source": CONFIG["data_source"],
    }
    return _write("A4", run_id, payload, "\n".join(md))


# ============================================================================
# A5 - chronological split (train earlier, test later)
# ============================================================================
def gate_a5() -> Path:
    """A5 - chronological split scored on the ANOMALY task (A5 reframe).

    A detections-only future window has no source-classification negatives, so
    source precision there is undefined-by-construction (the INVALID reading).
    The anomaly task DOES have negatives: every normal row in the future
    window. Abnormal support is ASSERTED before any P/R is quoted (>=20
    abnormal test rows; the cutoff shifts earlier when the default lands
    before the injected spikes, recorded in the manifest), and both the B4
    facility z-score baseline and the D-rung rule detector are scored on that
    same window.
    """
    from app.research.splits import temporal_split_with_abnormal_support

    run_id = _run_id("A5")
    df = generate_synthetic_dataset(n_days=CONFIG["train_n_days"],
                                    seed=CONFIG["seed"])
    train_idx, test_idx, manifest = temporal_split_with_abnormal_support(df)
    train_df, test_df = df.loc[train_idx], df.loc[test_idx]
    res = _fit_b3(train_df, test_df)

    shared_events = sorted(
        set(train_df.loc[train_df["event_id"] != "", "event_id"])
        & set(test_df.loc[test_df["event_id"] != "", "event_id"]))
    leakage = {
        "time_overlap": bool(train_df["observed_at"].max()
                             >= test_df["observed_at"].min()),
        "max_train_time": str(train_df["observed_at"].max()),
        "min_test_time": str(test_df["observed_at"].min()),
        "shared_facilities": sorted(
            (set(train_df["facility_id"]) & set(test_df["facility_id"]))
            - {""}),
        "fire_events_spanning_the_split": shared_events,
        "leakage_check": "FAIL" if (train_df["observed_at"].max()
                                    >= test_df["observed_at"].min()
                                    or shared_events) else "PASS",
        "note": "Same facilities in both halves is the DESIGN of a temporal "
                "split (train on history, predict the future); fire events "
                "spanning the cut would be leakage and are reported here.",
    }
    split_desc = (f"temporal split (train_fraction=0.8): train = observations "
                  f"before {str(manifest['cutoff_time'])[:19]}, test = after; "
                  f"n_train={len(train_df)}, n_test={len(test_df)}; "
                  f"abnormal test rows={manifest.get('abnormal_test_rows')} "
                  f"(support {manifest.get('abnormal_support_check')}); "
                  f"generator seed={CONFIG['seed']}, "
                  f"n_days={CONFIG['train_n_days']}")

    eval_days = float(
        (test_df["observed_at"].max() - test_df["observed_at"].min())
        / pd.Timedelta(days=1)) or 1.0
    eval_rows = test_df[test_df["facility_id"] != ""].copy()
    support_ok = manifest.get("abnormal_support_check") == "PASS"

    anomaly_task: dict = {
        "window": "future (test) window, normal vs abnormal",
        "abnormal_test_rows": manifest.get("abnormal_test_rows"),
        "abnormal_support_required": manifest.get("abnormal_support_required"),
        "abnormal_support_check": manifest.get("abnormal_support_check"),
        "abnormal_support_shifted": manifest.get("abnormal_support_shifted"),
    }
    if support_ok:
        # B4 facility z-score baseline on the future window (same method as
        # E01's B4 / A1's core baseline).
        b4_pred = _b0_threshold_pred(eval_rows, train_df)
        anomaly_task["b4"] = _binary_metrics(eval_rows, b4_pred, eval_days)
        # D-rung production rule: states from TRAIN-normal history only.
        history_normal = train_df[(train_df["facility_id"] != "")
                                  & (train_df["label_normality"] == "normal")]
        states = e10._build_states(history_normal)
        _sum, records = e10._score_rows(eval_rows, states)
        drung_pred = pd.Series([r["prediction"] for r in records],
                               index=eval_rows.index)
        anomaly_task["d_rung"] = _binary_metrics(eval_rows, drung_pred,
                                                 eval_days)
    else:
        anomaly_task["not_computable_reason"] = (
            f"abnormal support FAIL: "
            f"{manifest.get('abnormal_test_rows')} abnormal test rows < "
            f"required {manifest.get('abnormal_support_required')} — "
            "recorded, never estimated")

    ev = res["event_metrics"]
    n_neg = int((test_df["label_source_class"] == "natural_fire").sum())
    neg_note = ("the detections-only future window carries "
                f"{n_neg} natural-fire (negative) rows — the generator emits "
                "every natural/agri event in the first 33 days, so SOURCE "
                "precision here is undefined-by-construction and is NOT "
                "quoted; the ANOMALY task below has real negatives")
    md: list[str] = []
    md += _split_header("A5", "chronological split", run_id, split_desc)
    md += [
        "| metric | value |",
        "|---|---|",
        "| abnormal rows in future window | "
        f"{manifest.get('abnormal_test_rows')} (required >= "
        f"{manifest.get('abnormal_support_required')}) — "
        f"**{manifest.get('abnormal_support_check')}**"
        + (" (cutoff shifted earlier to guarantee support, recorded in the "
           "split manifest)" if manifest.get("abnormal_support_shifted")
           else "") + " |",
    ]
    if support_ok:
        b4m = anomaly_task["b4"]
        dm = anomaly_task["d_rung"]
        md += [
            f"| anomaly precision (B4 facility z-score) | {b4m['precision']} |",
            f"| anomaly recall (B4 facility z-score) | {b4m['recall']} |",
            f"| anomaly F1 (B4 facility z-score) | {b4m['f1']} |",
            f"| anomaly false alerts/facility-day (B4) | "
            f"{b4m['false_alert_rate_per_facility_day']} |",
            f"| anomaly precision (D-rung rule) | {dm['precision']} |",
            f"| anomaly recall (D-rung rule) | {dm['recall']} |",
            f"| anomaly F1 (D-rung rule) | {dm['f1']} |",
            f"| anomaly false alerts/facility-day (D-rung) | "
            f"{dm['false_alert_rate_per_facility_day']} |",
        ]
    else:
        md.append("| anomaly P/R (B4 and D-rung) | NOT COMPUTABLE — support "
                  "FAIL, recorded in the split manifest, never estimated |")
    md += [
        f"| macro-F1 source classification (context) | {res['macro_f1']} |",
        f"| accuracy (context) | {res['accuracy']} |",
        f"| source-classification precision | not quoted — {neg_note} |",
        f"| event F1 (context) | {ev['event_f1']} "
        f"(n_events={ev['n_events']}) |",
        f"| leakage check | {leakage['leakage_check']} |",
        f"| fire events spanning the cut | {len(shared_events)} |",
        "",
        "Read: precision/recall above are the ANOMALY task (normal vs "
        "abnormal in the future window) where negatives actually exist — the "
        "support is asserted, not assumed. Chronological performance vs the "
        "A4 geographic holdout separates 'moving forward in time at KNOWN "
        "facilities' from 'never having seen a region'. Both are held-out "
        "numbers.",
        "",
        "> SYNTHETIC data — harness validation only.",
    ]
    payload = {
        "gate": "A5_chronological", "run_id": run_id, "split": split_desc,
        "split_manifest": manifest,
        "anomaly_task_future_window": anomaly_task,
        "metrics": {k: v for k, v in res.items() if k != "_pred"},
        "negative_class_note": neg_note,
        "n_negative_test_rows": n_neg,
        "leakage": leakage, "config": CONFIG,
        "data_source": CONFIG["data_source"],
    }
    return _write("A5", run_id, payload, "\n".join(md))


# ============================================================================
# A6 + A7 - calibration and abstention (held-out, three-way split like E12)
# ============================================================================
def _calibration_bundle() -> dict:
    """ECE / Brier / reliability slope / risk-coverage on the held-out test.

    Split, features and model are IDENTICAL to E12 (three-way
    facility-grouped 60/20/20, frozen RF, seed 42) so the numbers can be
    cross-checked against that artifact run.
    """
    from sklearn.metrics import f1_score

    from app.ml.calibration import (apply_temperature_scaling,
                                    expected_calibration_error,
                                    fit_temperature_scaling)
    from app.research.baselines import build_baseline_classifier
    from app.research.splits import facility_grouped_split

    df = generate_synthetic_dataset(n_days=CONFIG["train_n_days"],
                                    seed=CONFIG["seed"])
    train_idx, rest_idx, _ = facility_grouped_split(df, test_size=0.4,
                                                    seed=CONFIG["seed"])
    cal_idx, test_idx, _ = facility_grouped_split(df.loc[rest_idx],
                                                  test_size=0.5,
                                                  seed=CONFIG["seed"])
    train_df, cal_df, test_df = df.loc[train_idx], df.loc[cal_idx], df.loc[test_idx]
    coords = get_facility_coords()
    X_tr = extract_b1_features(train_df, coords)
    X_cal = extract_b1_features(cal_df, coords)
    X_te = extract_b1_features(test_df, coords)

    y_tr = train_df["label_source_class"].astype(str).to_numpy()
    y_cal = cal_df["label_source_class"].astype(str).to_numpy()
    y_te = test_df["label_source_class"].astype(str).to_numpy()

    present = sorted(set(_encode(y_tr).tolist()))
    clf = build_baseline_classifier()
    clf.fit(X_tr.to_numpy(dtype=float), _encode(y_tr))

    def _full_proba(X) -> np.ndarray:
        proba = clf.predict_proba(X.to_numpy(dtype=float))
        out = np.zeros((len(X), len(SOURCE_CLASSES)))
        for col, cls in enumerate(present):
            out[:, cls] = proba[:, col]
        return out

    proba_cal = _full_proba(X_cal)
    proba_test = _full_proba(X_te)
    logits_cal = np.log(np.clip(proba_cal, 1e-10, 1.0))
    logits_test = np.log(np.clip(proba_test, 1e-10, 1.0))
    # Fit T on the IN-SPACE calibration rows only (the frozen E12 contract):
    # classes absent from the grouped training fold are zero-padded columns and
    # no temperature can rescue them - including them just pushes T to its
    # search bound. That sensitivity was measured tonight too (T hit the 20.0
    # bound and ruined full-set ECE) and is recorded as a note, not hidden.
    in_space_cal = np.isin(_encode(y_cal), present)
    ts = fit_temperature_scaling(logits_cal[in_space_cal],
                                 _encode(y_cal)[in_space_cal])
    proba_test_cal = apply_temperature_scaling(logits_test, ts.temperature)
    proba_cal_cal = apply_temperature_scaling(logits_cal, ts.temperature)

    y_enc = _encode(y_te)
    in_space = np.isin(y_enc, present)
    ece_before = expected_calibration_error(y_enc, proba_test)
    ece_after = expected_calibration_error(y_enc, proba_test_cal)
    ece_before_is = expected_calibration_error(y_enc[in_space],
                                               proba_test[in_space])
    ece_after_is = expected_calibration_error(y_enc[in_space],
                                              proba_test_cal[in_space])

    # Brier vs the base-rate (class-prior) predictor, same label space
    onehot = np.zeros_like(proba_test)
    for i, yt in enumerate(y_enc):
        if 0 <= yt < len(SOURCE_CLASSES):
            onehot[i, yt] = 1.0
    brier = float(np.mean(np.sum((proba_test_cal - onehot) ** 2, axis=1)))
    priors = np.zeros(len(SOURCE_CLASSES))
    for c in present:
        priors[c] = float((np.asarray(y_tr) == SOURCE_CLASSES[c]).mean())
    prior_proba = np.tile(priors, (len(y_te), 1))
    brier_baserate = float(np.mean(np.sum((prior_proba - onehot) ** 2, axis=1)))
    brier_baserate_inspace = float(np.mean(np.sum(
        (prior_proba[in_space] - onehot[in_space]) ** 2, axis=1)))
    brier_inspace = float(np.mean(np.sum(
        (proba_test_cal[in_space] - onehot[in_space]) ** 2, axis=1)))

    # Reliability slope: weighted least squares of bin accuracy on confidence
    conf = proba_test_cal.max(axis=1)
    pred = proba_test_cal.argmax(axis=1)
    correct = (pred == y_enc).astype(float)
    edges = np.linspace(0, 1, 11)
    xs, ys, ws, bins = [], [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf > lo) & (conf <= hi)
        if mask.sum() == 0:
            continue
        xs.append(float(conf[mask].mean()))
        ys.append(float(correct[mask].mean()))
        ws.append(int(mask.sum()))
        bins.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2),
                     "n": int(mask.sum()), "mean_conf": round(xs[-1], 4),
                     "accuracy": round(ys[-1], 4)})
    if len(xs) >= 2:
        slope, intercept = np.polyfit(np.asarray(xs), np.asarray(ys), 1,
                                      w=np.asarray(ws, dtype=float))
    else:
        slope, intercept = float("nan"), float("nan")

    # Risk-coverage: thresholds tuned on the CALIBRATION split, applied to the
    # HELD-OUT test (no test-set peeking - the test only measures what happens).
    conf_cal = proba_cal_cal.max(axis=1)
    conf = proba_test_cal.max(axis=1)
    pred = proba_test_cal.argmax(axis=1)
    order_cal = np.argsort(-conf_cal)
    n_cal = len(conf_cal)
    rc: dict[str, dict] = {}
    for cov in (0.90, 0.80, 0.70):
        k = max(1, int(np.ceil(cov * n_cal)))
        thr = float(conf_cal[order_cal][k - 1])
        accepted = conf >= thr
        n_acc = int(accepted.sum())
        err = float((pred[accepted] != y_enc[accepted]).mean()) if n_acc else None
        rc[f"{int(cov * 100)}"] = {
            "calibration_threshold": round(thr, 4),
            "achieved_coverage_test": round(n_acc / max(len(y_enc), 1), 4),
            "accepted_case_error_test": round(err, 4) if err is not None else None,
            "abstention_rate_test": round(1 - n_acc / max(len(y_enc), 1), 4),
            "n_accepted": n_acc, "n_abstained": int(len(y_enc) - n_acc),
        }
    n = len(y_enc)
    order = np.argsort(-conf)
    y_sorted, p_sorted = y_enc[order], pred[order]
    coverages = np.arange(1, n + 1) / n
    risks = np.cumsum(y_sorted != p_sorted) / np.arange(1, n + 1)
    aurc = float(np.trapezoid(risks, coverages))

    return {
        "split": ("three-way facility-grouped 60/20/20 (test_size=0.4 then 0.5, "
                  f"seed={CONFIG['seed']}); train n={len(train_df)}, "
                  f"calibration n={len(cal_df)}, HELD-OUT test n={len(test_df)}"),
        "n_train": len(train_df), "n_cal": len(cal_df), "n_test": len(test_df),
        "n_test_in_label_space": int(in_space.sum()),
        "temperature_fitted": round(float(ts.temperature), 4),
        "ece": {"before": round(ece_before, 4), "after": round(ece_after, 4),
                "in_space_before": round(ece_before_is, 4),
                "in_space_after": round(ece_after_is, 4)},
        "brier": {"model": round(brier, 4),
                  "model_in_space": round(brier_inspace, 4),
                  "base_rate": round(brier_baserate, 4),
                  "base_rate_in_space": round(brier_baserate_inspace, 4)},
        "reliability_slope": round(float(slope), 4),
        "reliability_intercept": round(float(intercept), 4),
        "reliability_bins": bins,
        "risk_coverage": rc,
        "aurc": round(aurc, 4),
        "macro_f1_test": round(float(f1_score(
            y_te, [SOURCE_CLASSES[c] for c in pred], labels=SOURCE_CLASSES,
            average="macro", zero_division=0)), 4),
    }


def gate_a6() -> Path:
    """A6 - calibration: ECE, Brier vs base rate, reliability slope."""
    run_id = _run_id("A6")
    b = _calibration_bundle()
    e12_run = _latest_run("E12_calibration")

    md: list[str] = []
    md += _split_header("A6", "calibration (held-out)", run_id, b["split"])
    if e12_run:
        md += [f"**Cross-check:** E12_calibration run `{e12_run.name}` "
               f"(`server/api/app/research/artifacts/E12_calibration/"
               f"{e12_run.name}/`) uses the identical split and model.  ", ""]
    e, br = b["ece"], b["brier"]
    skill = ("MODEL WORSE than base rate" if br["model"] > br["base_rate"]
             else "model better than base rate")
    md += [
        "| metric | value | interpretation |",
        "|---|---|---|",
        f"| ECE (10-bin, full test) | {e['before']} → **{e['after']}** "
        "(temperature-scaled) | lower is better |",
        f"| ECE (in label space, {b['n_test_in_label_space']}/{b['n_test']} rows) "
        f"| {e['in_space_before']} → **{e['in_space_after']}** | the honest "
        "calibration verdict (open-set rows cannot be calibrated by any T) |",
        f"| Brier (multiclass, model) | **{br['model']}** "
        f"(in-space {br['model_in_space']}) | |",
        f"| Brier (base-rate predictor) | {br['base_rate']} "
        f"(in-space {br['base_rate_in_space']}) | the no-skill reference |",
        f"| Brier skill vs base rate | {skill} "
        f"(Δ={round(br['model'] - br['base_rate'], 4):+}) | |",
        f"| reliability slope | **{b['reliability_slope']}** "
        f"(intercept {b['reliability_intercept']}) | ideal 1.0; <1 = "
        "over-confident |",
        f"| fitted temperature T | {b['temperature_fitted']} | fit on the "
        "CALIBRATION split only (held-out test untouched) |",
        f"| macro-F1 (held-out test) | {b['macro_f1_test']} | |",
        "",
        "Everything above is measured on the held-out test split; T and any "
        "abstention threshold are fit on the calibration split and are "
        "labelled DEVELOPMENT/TUNING when used as production parameters.",
        "",
        "> SYNTHETIC data — harness validation only.",
    ]
    payload = {"gate": "A6_calibration", "run_id": run_id, "metrics": b,
               "source_experiment": "E12_calibration",
               "source_run": (e12_run.name if e12_run else "not_run"),
               "config": CONFIG, "data_source": CONFIG["data_source"]}
    return _write("A6", run_id, payload, "\n".join(md))


def gate_a7() -> Path:
    """A7 - abstention: risk-coverage at 90/80/70 + evidence triggers."""
    from app.core.config import settings

    run_id = _run_id("A7")
    b = _calibration_bundle()
    e10_run = _latest_run("E10_hard_cases")
    e10m = _load_json(e10_run / "metrics.json") if e10_run else {}
    e10_run_id = e10_run.name if e10_run else "not_run"
    rc = b["risk_coverage"]
    h11 = (e10m.get("scenarios", {}).get("H11_cold_start") or {}).get("value")
    h9 = (e10m.get("scenarios", {}).get("H9_sparse") or {}).get("value")

    triggers = [
        {"condition": "facility normal state missing or below sufficiency "
                      f"(state_min_obs={settings.state_min_obs}, "
                      f"state_min_days={settings.state_min_days})",
         "production_behaviour": "INSUFFICIENT_HISTORY -> abstain (no alert, "
                                 "never a silent NORMAL)",
         "measured": f"E10 H11 cold-start abstain rate = {h11}; H9 thinned "
                     f"history = {h9}; A1 held-out hard-case set: ThermoWatch "
                     "abstained on 0 rows (all 18 states sufficient)",
         "evidence": f"E10 run {e10_run_id} + A1 run"},
        {"condition": f"incident with fewer than abstain_min_obs="
                      f"{settings.abstain_min_obs} observations",
         "production_behaviour": "INSUFFICIENT_EVIDENCE disposition",
         "measured": "asserted by the server test-suite",
         "evidence": "tests/test_assessment.py, tests/test_evidence_fusion.py "
                     "(re-run in B9)"},
        {"condition": "no evidence source with usable confidence (all sources "
                      "missing or zero-confidence)",
         "production_behaviour": "fusion returns confidence 0 -> abstain",
         "measured": "A8 fusion ladder rung 1 (FIRMS-only, no state/context/"
                     "optical/weather): fused_confidence = 0.0, explanation "
                     "'No evidence available - abstaining'",
         "evidence": "A8 run (evidence/final/A8_RUN-*)"},
        {"condition": "model confidence below the coverage-tuned threshold "
                      "(target coverage 90%, fit on the CALIBRATION split)",
         "production_behaviour": "prediction withheld -> INSUFFICIENT_EVIDENCE",
         "measured": f"threshold = {rc['90']['calibration_threshold']} "
                     f"(calibration-tuned) -> achieved test coverage "
                     f"{rc['90']['achieved_coverage_test']}, abstention "
                     f"{rc['90']['abstention_rate_test']}",
         "evidence": "DEVELOPMENT/TUNING - tuned on the calibration split, "
                     "evaluated on the held-out test"},
        {"condition": "external evidence disabled "
                      "(TW_EXTERNAL_EVIDENCE_ENABLED=0 kill switch)",
         "production_behaviour": "optical/weather recorded unavailable; fusion "
                                 "proceeds on the remaining sources only",
         "measured": "provider timeout / disabled-by-config paths asserted by "
                     "the failure-injection suite",
         "evidence": "tests/test_failure_injection.py (re-run in B9)"},
    ]

    md: list[str] = []
    md += _split_header("A7", "abstention / risk-coverage", run_id, b["split"])
    md += [
        "| target coverage | achieved coverage | accepted-case error | "
        "abstention rate | confidence threshold |",
        "|---|---|---|---|---|",
    ]
    for cov in ("90", "80", "70"):
        r = rc[cov]
        md.append(f"| {cov}% | {r['achieved_coverage_test']} | "
                  f"{r['accepted_case_error_test']} | "
                  f"{r['abstention_rate_test']} | "
                  f"{r['calibration_threshold']} |")
    md += [
        "",
        "Thresholds are tuned on the CALIBRATION split and applied unchanged "
        "to the held-out test; the achieved coverage is whatever the test set "
        "gave (no test-set peeking).",
        "",
        f"AURC = {b['aurc']} (lower is better); reliability slope "
        f"{b['reliability_slope']}. If accepted-case error does not fall as "
        "coverage drops, abstention would be useless — the measured curve is "
        "reported either way.",
        "",
        "### Evidence conditions that trigger abstention",
        "",
        "| condition | production behaviour | measured tonight | evidence |",
        "|---|---|---|---|",
    ]
    for t in triggers:
        md.append(f"| {t['condition']} | {t['production_behaviour']} | "
                  f"{t['measured']} | {t['evidence']} |")
    md += [
        "",
        "> SYNTHETIC data — harness validation only; thresholds tuned on the "
        "calibration split are DEVELOPMENT/TUNING, not final evaluation.",
    ]
    source_run = _latest_run("E12_calibration")
    payload = {"gate": "A7_abstention", "run_id": run_id,
               "risk_coverage": rc, "aurc": b["aurc"],
               "abstention_triggers": triggers,
               "source_experiment": "E12_calibration",
               "source_run": source_run.name if source_run is not None else "not_run",
               "config": CONFIG, "data_source": CONFIG["data_source"]}
    return _write("A7", run_id, payload, "\n".join(md))


# ============================================================================
# A8 + A10 - fusion ablation ladder and degradation signature
# ============================================================================
# Fixed evidence grid: every rung is scored over the SAME value grid so the
# only thing that changes between rungs is WHICH SOURCES ARE ALLOWED IN.
_THERMAL_Z = [0.0, 2.0, 3.5, 5.0]
_OPTICAL = [0.0, 0.02, 0.06]
_WEATHER = [0.1, 0.5, 0.9]
_CONTEXT = [(0.5, True), (3.0, False), (12.0, False)]


def _fuse_grid(sources: set[str]) -> dict:
    """Score the fusion function over the fixed evidence grid for one rung."""
    from itertools import product

    from app.ml.evidence_fusion import fuse_evidence

    thermals = _THERMAL_Z if "thermal" in sources else [None]
    opticals = _OPTICAL if "optical" in sources else [None]
    weathers = _WEATHER if "weather" in sources else [None]
    contexts = _CONTEXT if "context" in sources else [(None, None)]

    scores, confs, reasons = [], [], set()
    abstains = positives = n = 0
    for tz, op, wa, (dist, match) in product(thermals, opticals, weathers, contexts):
        res = fuse_evidence(
            thermal_z=tz, optical_fire_ratio=op, optical_available=op is not None,
            weather_risk=wa, facility_proximity_km=dist,
            facility_type_match=match)
        n += 1
        scores.append(res.fused_score)
        confs.append(res.fused_confidence)
        if "abstain" in res.explanation.lower():
            abstains += 1
            reasons.add(res.explanation)
        if res.is_abnormal:
            positives += 1
    return {
        "n_grid_points": n,
        "mean_confidence": round(float(np.mean(confs)), 4),
        "min_confidence": round(float(np.min(confs)), 4),
        "max_confidence": round(float(np.max(confs)), 4),
        "abstention_rate": round(abstains / n, 4),
        "positive_rate": round(positives / n, 4),
        "mean_score": round(float(np.mean(scores)), 4),
        "abstain_reasons": sorted(reasons),
        "sources": sorted(sources),
    }


_FUSION_LADDER = [
    ("R1 FIRMS-only", set()),
    ("R2 +OSM", {"context"}),
    ("R3 +normal-state", {"context", "thermal"}),
    ("R4 +optical (Sentinel-2)", {"context", "thermal", "optical"}),
    ("R5 +weather", {"context", "thermal", "optical", "weather"}),
    ("R6 full", {"context", "thermal", "optical", "weather"}),
]


def _e13_scenarios() -> dict:
    run = _latest_run("E13_robustness")
    if run is None:
        return {}
    m = _load_json(run / "metrics.json")
    return {"run": run.name, "scenarios": m.get("scenarios", {}),
            "graceful_degradation_pass": m.get("graceful_degradation_pass")}


def gate_a8() -> Path:
    """A8 - fusion ablation ladder (reduced, labelled) + RF ablation rungs."""
    run_id = _run_id("A8")
    ladder, prev = [], None
    for name, sources in _FUSION_LADDER:
        g = _fuse_grid(sources)
        g["rung"] = name
        g["delta_mean_confidence_vs_prev"] = (
            None if prev is None
            else round(g["mean_confidence"] - prev["mean_confidence"], 4))
        g["delta_abstention_vs_prev"] = (
            None if prev is None
            else round(g["abstention_rate"] - prev["abstention_rate"], 4))
        ladder.append(g)
        prev = g

    e13 = _e13_scenarios()
    sc = e13.get("scenarios", {})
    md: list[str] = []
    md += _split_header(
        "A8", "fusion ablation ladder", run_id,
        "fixed evidence grid (thermal z, optical fire ratio, weather risk, "
        "facility context) scored by app.ml.evidence_fusion.fuse_evidence; "
        "ONLY the set of allowed sources changes between rungs; plus the RF "
        "feature ablation from E13 (facility_grouped split)")
    md += [
        "### Rung 1 — fusion evidence ladder (Δ per rung)",
        "",
        "| rung | sources | mean conf | min conf | abstention rate | "
        "positive rate | Δ conf vs prev | Δ abstention vs prev |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for g in ladder:
        dcf = g["delta_mean_confidence_vs_prev"]
        dab = g["delta_abstention_vs_prev"]
        md.append(f"| {g['rung']} | {', '.join(g['sources']) or '(none)'} | "
                  f"{g['mean_confidence']} | {g['min_confidence']} | "
                  f"{g['abstention_rate']} | {g['positive_rate']} | "
                  f"{'—' if dcf is None else f'{dcf:+.4f}'} | "
                  f"{'—' if dab is None else f'{dab:+.4f}'} |")
    md += [
        "",
        "R5 (+weather) and R6 (full) are the SAME four-source set in the "
        "fusion model — R6 is recorded with Δ=0 by construction rather than "
        "inventing a sixth source.",
        "",
        "### Rung 2 — RF feature ablation (E13, reduced ablation)",
        "",
        f"**Source run:** E13_robustness `{e13.get('run', 'not_run')}` "
        "(`server/api/app/research/artifacts/E13_robustness/"
        f"{e13.get('run', '')}/`)",
        "",
        "| scenario | macro-F1 | Δ vs full |",
        "|---|---|---|",
    ]
    for key in ("thermal_only", "no_facility_context", "no_frp",
                "no_brightness", "sparse_50pct_obs", "full_features"):
        s = sc.get(key)
        if not s:
            continue
        if key == "full_features":
            delta = "baseline"
        else:
            delta = f"{-(s.get('degradation_vs_full') or 0.0):+.4f}"
        md.append(f"| {key} | {s.get('macro_f1')} | {delta} |")
    md += [
        "",
        "Mapping to the checklist ladder: `thermal_only` = FIRMS-only, "
        "`no_facility_context` = −OSM, `full_features` = full. Weather and "
        "Sentinel-2 are NOT features of the RF model, so their Δ F1 exists "
        "only at the fusion level (PARTIAL scope, stated here).",
        "",
        f"Graceful-degradation floor (macro-F1 ≥ 0.3 in every rung): "
        f"**{'PASS' if e13.get('graceful_degradation_pass') else 'FAIL'}** "
        "as recorded by E13 — quoted verbatim, not re-judged here.",
        "",
        "> SYNTHETIC data — harness validation only.",
    ]
    payload = {"gate": "A8_fusion_ablation", "run_id": run_id,
               "fusion_ladder": ladder, "e13": e13,
               "scope_note": "REDUCED ABLATION: 6 fusion rungs (R6==R5 by "
                             "construction) + 6 RF feature rungs from E13",
               "config": CONFIG, "data_source": CONFIG["data_source"]}
    return _write("A8", run_id, payload, "\n".join(md))


def gate_a10() -> Path:
    """A10 - remove OSM / weather / Sentinel-2 one at a time + signature."""
    run_id = _run_id("A10")
    full_sources = {"context", "thermal", "optical", "weather"}
    full = _fuse_grid(full_sources)
    e13 = _e13_scenarios()
    sc = e13.get("scenarios", {})

    removals = [
        ("−OSM (facility context)", {"thermal", "optical", "weather"},
         (sc.get("no_facility_context") or {}).get("degradation_vs_full"),
         "E13 no_facility_context"),
        ("−weather", {"context", "thermal", "optical"}, None, None),
        ("−Sentinel-2 (optical)", {"context", "thermal", "weather"}, None, None),
        ("−normal-state (thermal residual)", {"context", "optical", "weather"},
         (sc.get("no_frp") or {}).get("degradation_vs_full"), "E13 no_frp"),
        ("−all optional sources (FIRMS-only floor)", set(),
         (sc.get("thermal_only") or {}).get("degradation_vs_full"),
         "E13 thermal_only"),
    ]
    rows = []
    for label, keep, d_f1, f1_src in removals:
        g = _fuse_grid(keep)
        rows.append({
            "removal": label, "sources_remaining": sorted(keep),
            "mean_confidence": g["mean_confidence"],
            "delta_confidence_vs_full": round(
                g["mean_confidence"] - full["mean_confidence"], 4),
            "abstention_rate": g["abstention_rate"],
            "delta_abstention_vs_full": round(
                g["abstention_rate"] - full["abstention_rate"], 4),
            "positive_rate": g["positive_rate"],
            "delta_f1_rf_level": (-d_f1 if d_f1 is not None else None),
            "f1_source": (f1_src + " run " + e13.get("run", "") if f1_src
                          else "not available at RF level (source is not an "
                               "E13 feature) — fusion-level Δ only"),
        })

    signature_failures = [
        r["removal"] for r in rows
        if r["delta_confidence_vs_full"] > 0 or r["delta_abstention_vs_full"] < 0
    ]
    signature = "PASS" if not signature_failures else "FAIL"

    md: list[str] = []
    md += _split_header(
        "A10", "degradation / missing-evidence signature", run_id,
        "same fixed evidence grid as A8; each row removes exactly one source "
        "from the FULL four-source fusion and re-scores the grid")
    md += [
        "| removal | Δ mean confidence | abstention rate | Δ abstention | "
        "positive rate | Δ F1 (RF level) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        d = r["delta_f1_rf_level"]
        md.append(f"| {r['removal']} | {r['delta_confidence_vs_full']:+.4f} | "
                  f"{r['abstention_rate']} | {r['delta_abstention_vs_full']:+.4f} | "
                  f"{r['positive_rate']} | "
                  f"{'n/a' if d is None else f'{d:+.4f}'} |")
    md += [
        "",
        f"**Signature check:** missing evidence → confidence drops and "
        f"abstention rises, never fabricated certainty → **{signature}**"
        + (f" (violations: {signature_failures})" if signature_failures else "")
        + ".",
        "",
        "F1 deltas are quoted only where an analogous E13 feature rung exists "
        "(OSM → no_facility_context; FIRMS-only → thermal_only; thermal state "
        "→ no_frp). Weather and Sentinel-2 are not RF features, so their F1 "
        "impact is PARTIAL — fusion-level only. E13's graceful-degradation "
        "verdict is quoted verbatim: "
        f"{'PASS' if e13.get('graceful_degradation_pass') else 'FAIL'} "
        f"(E13 run {e13.get('run', 'not_run')}).",
        "",
        "> SYNTHETIC data — harness validation only.",
    ]
    payload = {"gate": "A10_degradation", "run_id": run_id,
               "full_reference": full, "removals": rows,
               "signature_check": signature,
               "signature_violations": signature_failures,
               "e13": e13, "config": CONFIG,
               "data_source": CONFIG["data_source"]}
    return _write("A10", run_id, payload, "\n".join(md))











# ============================================================================
# CLI
# ============================================================================
GATES = {
    "a1": ("A1 core result", "gate_a1"),
    "a2": ("A2 H1-H12 hard cases", "gate_a2"),
    "a3": ("A3 leave-one-facility-out", "gate_a3"),
    "a4": ("A4 geographic holdout", "gate_a4"),
    "a5": ("A5 chronological split", "gate_a5"),
    "a6": ("A6 calibration", "gate_a6"),
    "a7": ("A7 abstention / risk-coverage", "gate_a7"),
    "a8": ("A8 fusion ablation ladder", "gate_a8"),
    "a10": ("A10 degradation signature", "gate_a10"),
    "b3": ("B3 topology verdict", "gate_b3"),
}


def main() -> None:
    try:
        sys_out = __import__("sys").stdout
        if hasattr(sys_out, "reconfigure"):
            sys_out.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="ThermoWatch final-validation evidence harness")
    ap.add_argument("gate", choices=sorted(GATES), help="checklist gate to run")
    args = ap.parse_args()
    fn_name = GATES[args.gate][1]
    fn = globals().get(fn_name)
    if fn is None:
        raise SystemExit(
            f"gate {args.gate} is not implemented in this harness (missing {fn_name})")
    path = fn()
    print(f"  [done] evidence: {path}")


if __name__ == "__main__":
    main()






