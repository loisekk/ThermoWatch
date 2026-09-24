"""Deterministic demo scenario runner (Phase 7).

Drives the full analyst loop against a LIVE API over HTTP with a fixed seed,
so every run exercises the SAME synthetic evidence path:

  health probe -> ingest (seeded VIIRS rows) -> incident queue lookup
              -> evidence dossier -> analyst review -> markdown report

Degradation contract (mirrors the load-test harness):
  - Probes ``/health/ready`` first (falls back to ``/health/live``) at the
    API ROOT (both health endpoints are root-mounted, NOT under /v2).
  - API unreachable or DB not ready -> report written with ``status`` set,
    every step marked skipped, exit code 0 (a demo never fails the build).
  - Data endpoints all use the ``/v2`` prefix.
  - Rows are deterministic for a given ``--seed``; a replay of the same seed
    hits ingest idempotency (duplicates counted, nothing double-inserted),
    which the report records rather than treats as an error.

Usage:
    python -m app.tools.demo_scenario
    python -m app.tools.demo_scenario --base-url http://localhost:8000 --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.research.config import MODEL_SEED

REPORTS_DIR = Path(__file__).parent / "reports"
DEFAULT_REPORT = REPORTS_DIR / "demo_scenario.json"

# Deterministic VIIRS row template — same contract POST /v2/observations
# validates (mirrors the phase-4/7 test fixtures).
_ROW_BASE = {
    "bright_ti4": 320.5, "bright_ti5": 300.2, "scan": 0.45, "track": 0.4,
    "satellite": "N", "instrument": "VIIRS", "confidence": "H",
    "daynight": "D", "frp": 25.5,
}


def _seeded_rows(seed: int, n: int) -> list[dict]:
    """N VIIRS rows fully determined by ``seed`` (same lat/lon/frp per seed)."""
    rng = random.Random(seed)
    rows: list[dict] = []
    for i in range(n):
        # Spread over the Gujarat fixture box, stable 3-decimal rounding.
        lat = round(22.30 + rng.random() * 0.40, 3)
        lon = round(69.90 + rng.random() * 0.40, 3)
        rows.append({
            **_ROW_BASE,
            "latitude": lat,
            "longitude": lon,
            # Deterministic timestamps: 2026-09-23, hour cycles 08..19.
            "acq_date": "2026-09-23",
            "acq_time": f"{8 + (i % 12):02d}{(i * 7) % 60:02d}",
            "frp": round(18.0 + rng.random() * 30.0, 1),
        })
    return rows


async def _probe_health(client: httpx.AsyncClient) -> tuple[bool, str, dict]:
    """Root health probe: /health/ready first, fallback /health/live."""
    for path in ("/health/ready", "/health/live"):
        try:
            r = await client.get(path)
        except httpx.HTTPError as exc:
            return False, path, {"error": str(exc)}
        if r.status_code == 200:
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text[:200]}
            return True, path, body
    return False, "/health/ready", {"status_code": r.status_code}


# =====================================================================
# Scenario steps
# =====================================================================
async def run_scenario(client: httpx.AsyncClient, seed: int, n_rows: int,
                       run_nonce: str) -> dict:
    """Execute the analyst loop; every step records status + key evidence."""
    steps: dict[str, dict] = {}
    report: dict = {
        "steps": steps,
        "status": "ok",
    }

    rows = _seeded_rows(seed, n_rows)
    report["n_rows"] = len(rows)
    report["row_fingerprint"] = {
        "first": {k: rows[0][k] for k in ("latitude", "longitude", "frp",
                                          "acq_date", "acq_time")},
        "last": {k: rows[-1][k] for k in ("latitude", "longitude", "frp",
                                          "acq_date", "acq_time")},
    }

    # --- 1. Ingest (deterministic rows, per-run batch id) ----------------
    ing = await client.post("/v2/observations", json={
        "observations": rows,
        "source_batch_id": f"demo-{seed}-{run_nonce}",
    })
    ing_body = ing.json() if ing.status_code == 201 else {}
    steps["ingest"] = {
        "status_code": ing.status_code,
        "accepted": ing_body.get("accepted"),
        "duplicates": ing_body.get("duplicates"),
        "quarantined": ing_body.get("quarantined"),
        "incidents_touched": ing_body.get("incidents_touched"),
        "assessments": ing_body.get("assessments"),
    }
    if ing.status_code != 201:
        report["status"] = "ingest_failed"
        return report

    # --- 2. Find the seeded incident in the queue ------------------------
    q = await client.get("/v2/incidents", params={"limit": 50})
    incidents = q.json().get("incidents", []) if q.status_code == 200 else []
    seeded_lats = {r["latitude"] for r in rows}
    match = next(
        (i for i in incidents
         if any(abs(i["centroid_latitude"] - lat) < 0.05 for lat in seeded_lats)),
        None,
    )
    steps["queue"] = {
        "status_code": q.status_code,
        "matched_incident": match["id"] if match else None,
    }
    if match is None:
        report["status"] = "no_incident_matched"
        return report

    incident_id = match["id"]
    version = match["version"]

    # --- 3. Evidence dossier ---------------------------------------------
    d = await client.get(f"/v2/incidents/{incident_id}")
    d_body = d.json() if d.status_code == 200 else {}
    cur = d_body.get("current_assessment")
    steps["dossier"] = {
        "status_code": d.status_code,
        "observation_count": d_body.get("observation_count"),
        "assessment_status": cur.get("status") if isinstance(cur, dict) else None,
        "activity_state": (
            cur.get("activity_state") if isinstance(cur, dict) else None
        ),
        "has_reviews_key": "reviews" in d_body,
    }

    # --- 4. Analyst review (escalate with a substantive note) -------------
    rev = await client.post(f"/v2/incidents/{incident_id}/reviews", json={
        "action": "escalated",
        "note": "Demo scenario: persistent thermal anomaly flagged for "
                "analyst handoff (seeded run, not a field observation).",
        "expected_incident_version": version,
        "idempotency_key": f"demo-{seed}-{run_nonce}",
    })
    steps["review"] = {
        "status_code": rev.status_code,
        "new_version": (rev.json() or {}).get("new_version")
        if rev.status_code == 201 else None,
    }

    # --- 5. Markdown report export ---------------------------------------
    rep = await client.get(f"/v2/incidents/{incident_id}/report")
    steps["report"] = {
        "status_code": rep.status_code,
        "content_type": rep.headers.get("content-type", ""),
        "bytes": len(rep.content),
        "has_caveats": "Caveats" in rep.text,
    }

    ok = (
        steps["dossier"]["status_code"] == 200
        and steps["review"]["status_code"] == 201
        and steps["report"]["status_code"] == 200
        and steps["report"]["has_caveats"]
    )
    report["status"] = "ok" if ok else "partial"
    report["incident_id"] = incident_id
    return report


def _write_report(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


async def _amain(args: argparse.Namespace, run_nonce: str) -> dict:
    report: dict = {
        "tool": "demo_scenario",
        "seed": args.seed,
        "base_url": args.base_url,
        "run_nonce": run_nonce,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "status": "api_unreachable",
    }
    timeouts = httpx.Timeout(10.0)
    try:
        async with httpx.AsyncClient(
            base_url=args.base_url, timeout=timeouts,
        ) as client:
            reachable, probe_path, probe_body = await _probe_health(client)
            report["health"] = {
                "probe_path": probe_path,
                "reachable": reachable,
                "body": probe_body,
            }
            if not reachable:
                report["skipped"] = "API unreachable"
                return report
            if probe_path != "/health/ready":
                # ready was tried first and failed -> DB degraded; fall back
                # to liveness only. Demo steps need the DB, so skip them.
                report["status"] = "db_not_ready"
                report["skipped"] = (
                    "/health/ready not 200 (database unreachable); "
                    "fell back to /health/live"
                )
                return report

            result = await run_scenario(
                client, args.seed, args.rows, run_nonce,
            )
            report.update(result)
            report["seed"] = args.seed
            report["base_url"] = args.base_url
            report["run_nonce"] = run_nonce
            return report
    except Exception as exc:  # noqa: BLE001 — demo never fails the build
        report["status"] = "error"
        report["skipped"] = f"{type(exc).__name__}: {exc}"
        return report


def main() -> None:
    ap = argparse.ArgumentParser(description="ThermoWatch deterministic demo")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--seed", type=int, default=MODEL_SEED)
    ap.add_argument("--rows", type=int, default=8)
    ap.add_argument("--out", default=str(DEFAULT_REPORT))
    args = ap.parse_args()

    # Batch/idempotency uniqueness only — the ROW DATA itself (lat/lon/frp/
    # times) is fully determined by --seed, so evidence paths replay cleanly.
    run_nonce = uuid.uuid4().hex[:8]

    report = asyncio.run(_amain(args, run_nonce))
    path = _write_report(report, Path(args.out))

    status = report.get("status")
    if status != "ok":
        print(f"  [skip] demo not complete — "
              f"{report.get('skipped', status)}")
    else:
        print(f"  [done] incident {report.get('incident_id')}: "
              f"ingest {report['steps']['ingest']['accepted']} rows, "
              f"review "
              f"{report['steps']['review']['status_code']}, "
              f"report "
              f"{report['steps']['report']['status_code']}")
    print(f"  [ok] report written to {path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
