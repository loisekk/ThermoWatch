"""Consolidated model benchmark report (Phase 7).

Reads the LATEST run of every experiment artifact directory (E00-E14) and
emits one consolidated ``benchmark_report.json`` + ``benchmark_report.md``
under ``app/tools/reports/``. This is the single evidence table backing the
model-performance section of the release bundle.

Design contract:
- Read-only over artifacts: nothing is recomputed, re-tuned or re-run — the
  report quotes what the pre-registered experiment runs recorded.
- Missing experiments (e.g. the E02 normality-matrix splits, whose artifact
  directories may not exist on this checkout) are reported as ``not_run``
  with the reason, never silently dropped and never faked.
- Gate results are quoted verbatim, INCLUDING failures (E10 currently fails
  H1/H5 with attribution recorded in that run) — this tool reports, it does
  not judge.
- No capability claims: only measured numbers with their source experiment.

Usage:
    python -m app.tools.model_benchmark
    python -m app.tools.model_benchmark --artifacts-dir <path> --out-dir <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.research.config import ARTIFACTS_DIR

REPORTS_DIR = Path(__file__).parent / "reports"
DEFAULT_JSON = REPORTS_DIR / "benchmark_report.json"
DEFAULT_MD = REPORTS_DIR / "benchmark_report.md"

# Experiment -> section title. E02 is special-cased (two split dirs, may be
# absent); everything else is one dir with a latest timestamped run.
SECTIONS: list[tuple[str, str]] = [
    ("E00_data_audit", "Data audit (E00)"),
    ("E01_baselines", "Baseline comparison (E01)"),
    ("E02_normality_matrix", "Normality matrix (E02)"),
    ("E10_hard_cases", "Hard-case benchmark (E10)"),
    ("E11_lofo", "Leave-one-facility-out (E11)"),
    ("E12_calibration", "Calibration & abstention (E12)"),
    ("E13_robustness", "Feature ablation / degradation (E13)"),
    ("E14_data_efficiency", "Data efficiency (E14)"),
]


# =====================================================================
# Artifact loading
# =====================================================================
def _latest_run(exp_dir: Path) -> Path | None:
    """Latest timestamped run dir, or None when the experiment has no runs."""
    if not exp_dir.is_dir():
        return None
    runs = sorted(d for d in exp_dir.iterdir() if d.is_dir())
    return runs[-1] if runs else None


def _load_metrics(run_dir: Path) -> dict | None:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.is_file():
        return None
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _section_missing(experiment: str, reason: str) -> dict:
    return {"experiment": experiment, "status": "not_run", "reason": reason}


def _load_section(experiment: str, artifacts_dir: Path) -> tuple[dict, Path | None]:
    """Resolve the latest run for one experiment -> (section, run_dir|None)."""
    if experiment == "E02_normality_matrix":
        # E02 writes one dir per split; BOTH must exist to count as run.
        runs = {
            split: _latest_run(artifacts_dir / f"{experiment}_{split}")
            for split in ("train", "test")
        }
        if any(r is None for r in runs.values()):
            missing = [s for s, r in runs.items() if r is None]
            return (
                _section_missing(experiment, f"no artifacts for split(s): "
                                             f"{', '.join(missing)}"),
                None,
            )
        # Merge the two split runs (metrics keyed by split).
        merged: dict = {
            "experiment": experiment,
            "status": "ok",
            "run": runs["test"].name if runs["test"] is not None else None,
            "splits": {},
        }

        for split, run in runs.items():
            assert run is not None
            m = _load_metrics(run)
            merged["splits"][split] = {
                "run": run.name,
                "metrics": m if m is not None else None,
            }
        return merged, runs["test"]

    run = _latest_run(artifacts_dir / experiment)
    if run is None:
        return (
            _section_missing(experiment, "experiment directory has no runs"),
            None,
        )
    metrics = _load_metrics(run)
    if metrics is None:
        return (
            _section_missing(experiment, "metrics.json missing or unreadable"),
            run,
        )
    return {
        "experiment": experiment,
        "status": "ok",
        "run": run.name,
        "metrics": metrics,
    }, run


# =====================================================================
# Headline-metric extraction (quotes recorded values, never recomputes)
# =====================================================================
def _extract_e00(m: dict) -> dict:
    return {
        "dataset_version": m.get("dataset_version"),
        "source": m.get("source"),
        "n_observations": (m.get("coverage_table") or {}).get("n_observations"),
        "n_facilities": (m.get("coverage_table") or {}).get("n_facilities"),
        "label_distribution": m.get("label_distribution"),
        "normality_distribution": m.get("normality_distribution"),
        "leakage_verdict": (m.get("leakage_report") or {}).get("verdict"),
        "leakage_risks": (m.get("leakage_report") or {}).get("risks"),
        "decision_verdict": (m.get("decision") or {}).get("verdict"),
    }


def _extract_e01(m: dict) -> dict:
    table = m.get("comparison_table") or []
    return {
        "split": m.get("split_manifest_summary"),
        "comparison_table": [
            {
                "baseline": row.get("baseline"),
                "macro_f1": row.get("macro_f1"),
                "abnormal_f1": row.get("abnormal_f1"),
                "false_alert_rate": row.get("false_alert_rate"),
                "ece": row.get("ece"),
            }
            for row in table
        ],
        "note": "macro_f1 is None for B4 (rule baseline reports abnormal_f1)",
    }


def _extract_e10(m: dict) -> dict:
    gates = m.get("gates") or []
    return {
        "gates": [
            {
                "gate": g.get("gate"),
                "value": g.get("value"),
                "operator": g.get("operator"),
                "threshold": g.get("threshold"),
                "pass": g.get("pass"),
            }
            for g in gates
        ],
        "gates_summary": m.get("gates_summary"),
        "documented_gaps": m.get("documented_gaps"),
        "scenarios": {
            name: {
                "flagged_rate": s.get("flagged_rate"),
                "abstain_rate": s.get("abstain_rate"),
                "flag_attribution": s.get("flag_attribution"),
            }
            for name, s in (m.get("scenarios") or {}).items()
        },
    }


def _extract_e11(m: dict) -> dict:
    return {
        "aggregate": m.get("aggregate"),
        "per_facility": [
            {
                "facility_id": f.get("facility_id"),
                "accuracy": f.get("accuracy"),
                "n_test": f.get("n_test"),
            }
            for f in (m.get("per_facility") or [])
        ],
    }


def _extract_e12(m: dict) -> dict:
    return {
        "temperature_scaling": m.get("temperature_scaling"),
        "test_evaluation_90pct": m.get("test_evaluation_90pct"),
        "aurc": m.get("aurc"),
    }


def _extract_e13(m: dict) -> dict:
    return {
        "graceful_degradation_pass": m.get("graceful_degradation_pass"),
        "scenarios": {
            name: {"macro_f1": s.get("macro_f1"), "n_test": s.get("n_test")}
            for name, s in (m.get("scenarios") or {}).items()
        },
    }


def _extract_e14(m: dict) -> dict:
    return {
        "minimum_viable_history_days": m.get("minimum_viable_history_days"),
        "learning_curve": [
            {
                "history_days": p.get("history_days"),
                "abstain_rate": p.get("abstain_rate"),
                "anomaly_f1": p.get("anomaly_f1"),
                "false_alert_rate": p.get("false_alert_rate"),
            }
            for p in (m.get("learning_curve") or [])
        ],
    }


def _extract_e02(section: dict) -> dict:
    return {
        "splits": {
            split: {"run": s.get("run"), "has_metrics": s.get("metrics") is not None}
            for split, s in (section.get("splits") or {}).items()
        },
    }


EXTRACTORS = {
    "E00_data_audit": _extract_e00,
    "E01_baselines": _extract_e01,
    "E02_normality_matrix": _extract_e02,
    "E10_hard_cases": _extract_e10,
    "E11_lofo": _extract_e11,
    "E12_calibration": _extract_e12,
    "E13_robustness": _extract_e13,
    "E14_data_efficiency": _extract_e14,
}


def display_path(path: Path) -> str:
    """Checkout-relative form of ``path`` for reports meant to be shared.

    An absolute path would stamp the developer's machine layout (and therefore
    their username: ``C:\\Users\\<name>\\...``) into a report that gets attached
    to releases. Falls back to the bare directory name for paths outside the
    checkout.
    """
    resolved = path.resolve()
    for parent in resolved.parents:
        if (parent / ".git").exists():
            return resolved.relative_to(parent).as_posix()
    return resolved.name


def build_report(artifacts_dir: Path) -> dict:
    """Load every section, extract headlines, assemble the report dict."""
    sections: dict[str, dict] = {}
    for experiment, _title in SECTIONS:
        raw, _run = _load_section(experiment, artifacts_dir)
        entry: dict = {
            "experiment": experiment,
            "status": raw["status"],
        }
        if raw["status"] != "ok":
            entry["reason"] = raw.get("reason", "unknown")
            entry["headline"] = None
        else:
            entry["run"] = raw.get("run")
            extractor = EXTRACTORS[experiment]
            entry["headline"] = (
                extractor(raw["metrics"]) if experiment != "E02_normality_matrix"
                else extractor(raw)
            )
        sections[experiment] = entry

    e10 = (sections.get("E10_hard_cases") or {}).get("headline") or {}
    gates_summary = e10.get("gates_summary") or {}

    return {
        "tool": "model_benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts_dir": display_path(artifacts_dir),
        "n_sections": len(sections),
        "n_run": sum(1 for s in sections.values() if s["status"] == "ok"),
        "n_not_run": sum(1 for s in sections.values() if s["status"] != "ok"),
        "gate_summary_e10": {
            "n_pass": gates_summary.get("n_pass"),
            "n_total": gates_summary.get("n_total"),
            "all_pass": gates_summary.get("all_pass"),
        },
        "sections": sections,
    }


# =====================================================================
# Markdown rendering
# =====================================================================
def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def render_markdown(report: dict) -> str:
    titles = dict(SECTIONS)
    lines: list[str] = [
        "# Model Benchmark Report",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Artifacts:** `{report['artifacts_dir']}`",
        f"- **Sections run:** {report['n_run']}/{report['n_sections']}"
        f" ({report['n_not_run']} not run)",
        "",
        "Values below are quoted verbatim from the recorded experiment runs;",
        "nothing is recomputed here. Macro-F1 is reported per class/baseline,",
        "never as a bare accuracy figure.",
        "",
    ]

    for experiment, title in titles.items():
        section = report["sections"][experiment]
        lines.append(f"## {title}")
        lines.append("")
        if section["status"] != "ok":
            lines += [
                f"> **NOT RUN** — {section.get('reason', 'unknown reason')}",
                "",
            ]
            continue

        lines.append(f"*Run:* `{section['run']}`")
        lines.append("")
        h = section["headline"] or {}

        if experiment == "E00_data_audit":
            lines += [
                f"- Observations: {_fmt(h.get('n_observations'))} | "
                f"facilities: {_fmt(h.get('n_facilities'))} | "
                f"source: {_fmt(h.get('source'))}",
                f"- Data decision: **{_fmt(h.get('decision_verdict'))}** | "
                f"leakage review: **{_fmt(h.get('leakage_verdict'))}**",
                "",
            ]
        elif experiment == "E01_baselines":
            lines += ["| Baseline | macro-F1 | abnormal-F1 | false-alert rate | ECE |",
                      "|---|---|---|---|---|"]
            for row in h.get("comparison_table") or []:
                lines.append(
                    f"| {row['baseline']} | {_fmt(row['macro_f1'])} "
                    f"| {_fmt(row['abnormal_f1'])} "
                    f"| {_fmt(row['false_alert_rate'])} | {_fmt(row['ece'])} |"
                )
            lines.append("")
        elif experiment == "E10_hard_cases":
            gs = h.get("gates_summary") or {}
            lines.append(
                f"- Gates: **{_fmt(gs.get('n_pass'))}/"
                f"{_fmt(gs.get('n_total'))} pass** "
                f"(all_pass={_fmt(gs.get('all_pass'))})"
            )
            lines += ["", "| Gate | Value | Op | Threshold | Pass |",
                      "|---|---|---|---|---|"]
            for g in h.get("gates") or []:
                lines.append(
                    f"| {g['gate']} | {_fmt(g['value'])} | {g['operator']} "
                    f"| {_fmt(g['threshold'])} | {'PASS' if g['pass'] else 'FAIL'} |"
                )
            lines.append("")
            gaps = h.get("documented_gaps") or {}
            if gaps:
                lines.append("Documented gaps (not covered by this generator):")
                for name, gap in gaps.items():
                    reason = gap.get("reason", gap.get("description", ""))
                    lines.append(f"- `{name}`: {reason}")
                lines.append("")


        elif experiment == "E11_lofo":
            agg = h.get("aggregate") or {}
            lines += [
                f"- Folds: {_fmt(agg.get('n_folds'))} | "
                f"mean accuracy: {_fmt(agg.get('mean_accuracy'))} "
                f"± {_fmt(agg.get('std_accuracy'))}",
                f"- Facility-type identification rate: "
                f"**{_fmt(agg.get('facility_type_identification_rate'))}**",
                "",
            ]
        elif experiment == "E12_calibration":
            ts = h.get("temperature_scaling") or {}
            te = h.get("test_evaluation_90pct") or {}
            lines += [
                f"- Temperature scaling: ECE {_fmt(ts.get('ece_before'))} → "
                f"{_fmt(ts.get('ece_after'))} "
                f"(improvement {_fmt(ts.get('ece_improvement'))})",
                f"- Selective eval @90% target coverage: achieved "
                f"{_fmt(te.get('achieved_coverage'))}, selective risk "
                f"{_fmt(te.get('selective_risk'))}",
                "",
            ]
        elif experiment == "E13_robustness":
            lines.append(
                f"- Graceful degradation gate: "
                f"**{'PASS' if h.get('graceful_degradation_pass') else 'FAIL'}**"
            )
            lines += ["", "| Scenario | macro-F1 | n_test |", "|---|---|---|"]
            for name, s in (h.get("scenarios") or {}).items():
                lines.append(
                    f"| {name} | {_fmt(s.get('macro_f1'))} "
                    f"| {_fmt(s.get('n_test'))} |"
                )
            lines.append("")
        elif experiment == "E14_data_efficiency":
            lines.append(
                f"- Minimum viable history: "
                f"**{_fmt(h.get('minimum_viable_history_days'))} days**"
            )
            lines += ["",
                      "| History days | abstain rate | anomaly F1 | false-alert rate |",
                      "|---|---|---|---|"]
            for p in h.get("learning_curve") or []:
                lines.append(
                    f"| {p['history_days']} | {_fmt(p['abstain_rate'])} "
                    f"| {_fmt(p['anomaly_f1'])} | {_fmt(p['false_alert_rate'])} |"
                )
            lines.append("")
        elif experiment == "E02_normality_matrix":
            for split, s in (h.get("splits") or {}).items():
                lines.append(
                    f"- split `{split}`: run `{_fmt(s.get('run'))}`, "
                    f"metrics recorded: {_fmt(s.get('has_metrics'))}"
                )
            lines.append("")

    lines += [
        "---",
        "",
        "*Figures are measured outputs of the pre-registered experiment",
        "configuration; see each run's MANIFEST.json for the frozen config",
        "and dataset/split manifests.*",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Consolidated ThermoWatch model benchmark report"
    )
    ap.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    ap.add_argument("--out-json", default=str(DEFAULT_JSON))
    ap.add_argument("--out-md", default=str(DEFAULT_MD))
    args = ap.parse_args()

    artifacts = Path(args.artifacts_dir)
    report = build_report(artifacts)

    json_path = Path(args.out_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    md_path = Path(args.out_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"  [done] sections run: {report['n_run']}/{report['n_sections']}")
    gs = report["gate_summary_e10"]
    if gs.get("n_total"):
        print(f"  [done] E10 gates: {gs['n_pass']}/{gs['n_total']} pass")
    for name, section in report["sections"].items():
        if section["status"] != "ok":
            print(f"  [not-run] {name}: {section.get('reason')}")
    print(f"  [ok] JSON report: {json_path}")
    print(f"  [ok] Markdown report: {md_path}")


if __name__ == "__main__":
    main()
