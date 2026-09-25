"""Phase 0 — freeze the current implementation as the attribution baseline.

Records the CURRENT (failing) metrics as the baseline so every subsequent
improvement is attributable to a specific code change (plan section 3).
Never overwrites: each freeze is a NEW timestamped directory + git tag.

The frozen numbers are cross-checked against the artifacts already on disk
(``app/research/artifacts`` + ``evidence/final``) so a transcription error in
the score sheet cannot silently become "the baseline".

Usage:
    python -m app.tools.freeze_baseline --label pre-spatial-fix
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = API_ROOT / "app" / "research" / "artifacts"
FREEZE_DIR = ARTIFACTS / "_baselines"
REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = REPO_ROOT / "evidence" / "final"

# Pre-registered failure metrics from the A1-A5 score sheet (2026-09-25 run).
# These are the numbers the fixes must move; frozen here so nobody can
# silently re-baseline later.
SCORE_SHEET_BASELINE = {
    "recorded_at": "2026-09-25",
    "A1_core": {
        "thermowatch_fa_per_day": 12.30,
        "b0_fa_per_day": 0.375,
        "spatial_gate_share_of_normal_rows": 0.814,
        "verdict": "FAIL",
    },
    "A2_hard_cases": {
        "H1_false_alert_rate": 0.879, "H1_target": 0.10,
        "H5_recall": 0.250, "H5_bar": 0.50,
        "summary": "6 PASS / 2 FAIL / 4 PARTIAL",
    },
    "A4_geographic": "INVALID AS REPORTED (R2-R4 leakage validator)",
    "A5_temporal": "valid split; precision undefined (zero negatives in window)",
    "bars": {"H1": 0.10, "H2": 0.80, "H3": 0.80, "H4": 0.60,
             "H5": 0.50, "H11": 0.95},
}

# Where each frozen number must be re-derivable from, on disk.
_SCORE_SHEET_CHECKS = (
    ("A1_core.thermowatch_fa_per_day",
     ("A1", "methods", "ThermoWatch_full", "false_alerts_per_day")),
    ("A1_core.b0_fa_per_day",
     ("A1", "methods", "B0_threshold", "false_alerts_per_day")),
    ("A1_core.spatial_gate_share_of_normal_rows",
     ("A1", "gate_attribution_on_normal_rows", "spatial_fire_rate")),
    ("A2_hard_cases.H1_false_alert_rate", ("A2", "gates", "H1_false_alert_max")),
    ("A2_hard_cases.H5_recall", ("A2", "gates", "H5_recall_min")),
)


def git_sha() -> str:
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=API_ROOT, capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _load_evidence() -> dict[str, tuple[dict, str]]:
    """Load the A1/A2 evidence payloads keyed by gate letter (latest run each)."""
    out: dict[str, tuple[dict, str]] = {}
    if not EVIDENCE_DIR.exists():
        return out
    for letter in ("A1", "A2"):
        candidates = sorted(EVIDENCE_DIR.glob(f"{letter}_RUN-*.json"))
        if not candidates:
            continue
        path = candidates[-1]
        try:
            out[letter] = (json.loads(path.read_text(encoding="utf-8")), str(path))
        except Exception:
            continue
    return out


def _dig(payload, path: tuple):
    """Walk a path; a list node is resolved by its ``case``/``gate`` field."""
    node = payload
    for key in path:
        if isinstance(node, list):
            node = next((x for x in node if isinstance(x, dict)
                         and (x.get("case") == key or x.get("gate") == key)), None)
        elif isinstance(node, dict):
            node = node.get(key)
        else:
            return None
        if node is None:
            return None
    if isinstance(node, dict):
        return node.get("value", node)
    return node
def verify_against_artifacts() -> dict:
    """Re-derive the frozen numbers from on-disk evidence — never from memory."""
    evidence = _load_evidence()
    verified: dict[str, dict] = {}
    for label, path in _SCORE_SHEET_CHECKS:
        value, source = None, "evidence/final (no run found)"
        if path[0] in evidence:
            payload, source = evidence[path[0]]
            value = _dig(payload, path[1:])
        verified[label] = {"value": value, "source": source}

    # The A1/A2 payloads point at the E10 run they scored; record it too.
    e10_runs = sorted((ARTIFACTS / "E10_hard_cases").glob("*/metrics.json")) \
        if (ARTIFACTS / "E10_hard_cases").exists() else []
    if e10_runs:
        try:
            metrics = json.loads(e10_runs[-1].read_text(encoding="utf-8"))
            sc = metrics.get("scenarios", {})
            verified["E10_artifact.H1_false_alert_rate"] = {
                "value": sc.get("H1_normal_persistent", {}).get("flagged_rate"),
                "source": str(e10_runs[-1]),
            }
            verified["E10_artifact.H5_recall"] = {
                "value": sc.get("H5_duration_anomaly", {}).get("flagged_rate"),
                "source": str(e10_runs[-1]),
            }
        except Exception:
            pass
    return verified


def _matches(sheet_value: float, disk_value, tol: float = 5e-3) -> bool:
    if disk_value is None:
        return False
    try:
        return abs(float(sheet_value) - float(disk_value)) <= tol
    except (TypeError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True,
                    help="e.g. pre-spatial-fix, post-spatial-fix")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = FREEZE_DIR / f"{ts}_{args.label}"
    out.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot every current experiment artifact (read-only copy)
    copied, snapshot_of = 0, {}
    if ARTIFACTS.exists():
        for exp_dir in sorted(ARTIFACTS.iterdir()):
            if not exp_dir.is_dir() or exp_dir.name.startswith("_"):
                continue
            runs = sorted(p for p in exp_dir.iterdir() if p.is_dir())
            if not runs:
                continue
            shutil.copytree(runs[-1], out / exp_dir.name, dirs_exist_ok=True)
            snapshot_of[exp_dir.name] = runs[-1].name
            copied += 1

    # 2. Cross-check the score sheet against the evidence already on disk
    verified = verify_against_artifacts()
    checks = {label: value for label, value in (
        ("A1_core.thermowatch_fa_per_day", 12.30),
        ("A1_core.b0_fa_per_day", 0.375),
        ("A1_core.spatial_gate_share_of_normal_rows", 0.814),
        ("A2_hard_cases.H1_false_alert_rate", 0.879),
        ("A2_hard_cases.H5_recall", 0.250),
    )}
    consistency: dict[str, dict] = {}
    n_match = 0
    for key, sheet_value in checks.items():
        info = verified.get(key, {})
        ok = _matches(sheet_value, info.get("value"))
        n_match += int(ok)
        consistency[key] = {
            "score_sheet": sheet_value,
            "on_disk": info.get("value"),
            "match": ok,
            "source": info.get("source"),
        }
    if verified.get("E10_artifact.H1_false_alert_rate"):
        consistency["E10_artifact.H1_false_alert_rate"] = {
            "score_sheet": 0.879,
            "on_disk": verified["E10_artifact.H1_false_alert_rate"]["value"],
            "match": _matches(0.879,
                              verified["E10_artifact.H1_false_alert_rate"]["value"],
                              tol=5e-4),
            "source": verified["E10_artifact.H1_false_alert_rate"]["source"],
        }
        consistency["E10_artifact.H5_recall"] = {
            "score_sheet": 0.250,
            "on_disk": verified["E10_artifact.H5_recall"]["value"],
            "match": _matches(0.250, verified["E10_artifact.H5_recall"]["value"],
                              tol=5e-4),
            "source": verified["E10_artifact.H5_recall"]["source"],
        }

    manifest = {
        "label": args.label,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "score_sheet_baseline": SCORE_SHEET_BASELINE,
        "score_sheet_verified_against_artifacts": consistency,
        "n_headline_numbers_verified": n_match,
        "n_headline_numbers": len(checks),
        "artifacts_snapshot": copied,
        "snapshot_of": snapshot_of,
        "rule": "pre-registered bars; post-fix runs compare against THESE numbers",
    }
    (out / "BASELINE.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    # 3. Git tag so the code state is traceable
    tag = f"baseline/{args.label}/{ts}"
    try:
        subprocess.run(["git", "tag", "-a", tag, "-m",
                        f"Phase 0 baseline freeze: {args.label}"],
                       cwd=API_ROOT, check=True, timeout=10)
        print(f"  git tag created: {tag}")
    except Exception as e:
        print(f"  [warn] git tag failed ({e}) - commit first, then re-run")

    print(f"  baseline frozen -> {out}")
    print(f"  artifacts snapshot: {copied} experiments")
    print("  recorded failure metrics: H1 FA=0.879 (bar 0.10), "
          "H5 recall=0.250 (bar 0.50)")
    print(f"  score-sheet cross-check: {n_match}/{len(checks)} headline "
          f"numbers re-derived from on-disk evidence")
    for key, info in consistency.items():
        flag = "OK " if info["match"] else "!! "
        print(f"    {flag}{key}: sheet={info['score_sheet']} "
              f"disk={info['on_disk']}")
    if n_match < len(checks):
        print("  [warn] a frozen number could not be re-derived from the "
              "evidence on disk - kept as recorded, source noted in "
              "BASELINE.json")


if __name__ == "__main__":
    main()

