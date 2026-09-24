"""Load-test harness for the ThermoWatch API (Phase 7).

Runs a fixed sequence of phases against a LIVE API over HTTP and writes a
JSON report. Phases:

  cold       — cold-request latency (fresh connection pool) on the hot read
               endpoints (queue, observation list, health).
  ingest     — ingest ramp: batches of synthetic VIIRS rows at rising
               concurrency; measures row throughput + accepted/duplicate/
               quarantined counts.
  query      — read-path latency: queue first page, activity-filtered queue
               (post-filter scan), bbox + deep-page observation list.
  db_growth  — grows the observations table toward ``settings.loadtest_db_rows``
               (batched, pipeline off) while sampling queue latency at fixed
               checkpoints — the latency-vs-table-size curve.
  sustained  — mixed read+write load for a fixed duration; reports achieved
               request rate, error rate and p50/p95 per operation class.

Safety / degradation contract:
  - Probes ``/health/ready`` first (falls back to ``/health/live``) before any
    phase. API unreachable  -> report written with every phase SKIPPED,
    exit code 0 (a load test never takes the build down).
  - ``/health/ready`` not 200 (DB degraded) -> DB-dependent phases are skipped
    the same way; only health numbers are recorded.
  - The harness only ever *adds* synthetic rows (unique per run via seed +
    nonce) — it never deletes or mutates existing data.

Usage:
    python -m app.tools.loadtest
    python -m app.tools.loadtest --phases cold,query --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from app.research.config import MODEL_SEED

REPORTS_DIR = Path(__file__).parent / "reports"
DEFAULT_REPORT = REPORTS_DIR / "loadtest_report.json"

# Synthetic VIIRS CSV row — mirrors the shape POST /v2/observations validates
# (same contract the phase-4 tests exercise).
_VIIRS_BASE = {
    "bright_ti4": 320.5, "bright_ti5": 300.2, "scan": 0.45, "track": 0.4,
    "acq_date": "2026-09-23", "acq_time": "1530", "satellite": "N",
    "instrument": "VIIRS", "confidence": "H", "daynight": "D", "frp": 25.5,
    # Box around the Gujarat test facilities — same region the fixtures use.
    "latitude": 22.47, "longitude": 70.07,
}


# =====================================================================
# Small utilities
# =====================================================================
def _pct(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (ms). None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(int(round(p / 100.0 * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[idx], 2)


def _latency_stats(samples_ms: list[float]) -> dict:
    return {
        "n": len(samples_ms),
        "p50_ms": _pct(samples_ms, 50),
        "p95_ms": _pct(samples_ms, 95),
        "max_ms": round(max(samples_ms), 2) if samples_ms else None,
        "mean_ms": round(statistics.fmean(samples_ms), 2) if samples_ms else None,
    }


def _make_rows(n: int, rng: random.Random, nonce: str) -> list[dict]:
    """N unique synthetic VIIRS rows.

    Uniqueness comes from jittered coordinates + per-row acq_time so reruns
    never idempotently collide with each other or with fixture history —
    duplicates would silently deflate the ingest numbers.
    """
    rows = []
    # Spread the nonce across lat/lon/acq_time spaces deterministically.
    seed_int = int(uuid.uuid5(uuid.NAMESPACE_URL, nonce).int % 1_000_000)
    for i in range(n):
        row = dict(_VIIRS_BASE)
        row["latitude"] = round(22.0 + ((seed_int + i * 7) % 900_000) * 1e-6, 6)
        row["longitude"] = round(69.5 + ((seed_int * 3 + i * 11) % 900_000) * 1e-6, 6)
        minute = (seed_int + i) % 1440
        row["acq_time"] = f"{minute // 60:02d}{minute % 60:02d}"
        row["frp"] = round(rng.uniform(5.0, 80.0), 2)
        rows.append(row)
    return rows


async def _probe_api(base_url: str) -> dict:
    """Health probe: /health/ready first, /health/live as fallback.

    Returns {"reachable": bool, "ready": bool, ...health payloads...}.
    """
    info: dict = {"base_url": base_url, "reachable": False, "ready": False}
    timeouts = httpx.Timeout(5.0)
    try:
        async with httpx.AsyncClient(timeout=timeouts) as client:
            try:
                r = await client.get(f"{base_url}/health/ready")
                info["ready"] = r.status_code == 200
                info["ready_payload"] = r.json()
                info["reachable"] = True
                return info
            except (httpx.HTTPError, ValueError):
                pass  # ready endpoint down or non-JSON — try liveness
            try:
                r = await client.get(f"{base_url}/health/live")
                info["reachable"] = r.status_code == 200
                info["live_payload"] = r.json() if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                pass
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        info["error"] = str(exc)
    return info


def _write_report(report: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out


# =====================================================================
# Phases
# =====================================================================
async def phase_cold(base_url: str, repeats: int = 5) -> dict:
    """Fresh-connection latency on hot read endpoints (pool opened per call)."""
    endpoints = [
        ("health_ready", "GET", "/health/ready"),
        ("incidents_first_page", "GET", "/v2/incidents?limit=50"),
        ("observations_page", "GET", "/v2/observations?page_size=100"),
    ]
    out: dict[str, dict | list[str]] = {}
    errors: list[str] = []
    for name, method, path in endpoints:
        samples: list[float] = []
        status_counts: dict[int, int] = {}
        # Each repetition opens its own pool -> measures cold request cost.
        for _ in range(repeats):
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                    r = await client.request(method, f"{base_url}{path}")
                samples.append((time.perf_counter() - t0) * 1000.0)
                status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
            except httpx.HTTPError as exc:
                errors.append(f"{name}: {exc}")
        out[name] = {**_latency_stats(samples), "status_counts": status_counts}
    if errors:
        out["_errors"] = errors
    return out


async def phase_ingest(
    base_url: str, *, batch_size: int, batches: int, seed: int,
) -> dict:
    """Ingest ramp: sequential -> concurrent batches, rows/sec measured.

    process=true (production default) so the numbers include association +
    assessment, i.e. what a real FIRMS pull costs.
    """
    rng = random.Random(seed)
    nonce = uuid.uuid4().hex[:12]
    levels = [1, 2, 4]
    ramp: list[dict] = []
    totals = {"accepted": 0, "duplicates": 0, "quarantined": 0, "assessments": 0}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        for concurrency in levels:
            lat: list[float] = []
            acc = dup = quar = asm = 0
            seq = 0  # assigned BEFORE spawning -> no concurrent nonce collision

            async def one_batch(batch_seq: int) -> None:
                nonlocal acc, dup, quar, asm
                rows = _make_rows(batch_size, rng, f"{nonce}-{concurrency}-{batch_seq}")
                t0 = time.perf_counter()
                r = await client.post(
                    f"{base_url}/v2/observations",
                    json={"observations": rows,
                          "source_batch_id": f"lt-{nonce}-{concurrency}-{batch_seq}"},
                )
                lat.append((time.perf_counter() - t0) * 1000.0)
                if r.status_code == 201:
                    body = r.json()
                    acc += body.get("accepted", 0)
                    dup += body.get("duplicates", 0)
                    quar += body.get("quarantined", 0)
                    asm += body.get("assessments", 0)
                else:
                    raise RuntimeError(f"ingest {r.status_code}: {r.text[:200]}")

            t_start = time.perf_counter()
            try:
                for _ in range(batches):
                    group = []
                    for _ in range(concurrency):
                        group.append(one_batch(seq))
                        seq += 1
                    await asyncio.gather(*group)
            except Exception as exc:  # noqa: BLE001 — record, don't kill the run
                ramp.append({"concurrency": concurrency, "error": str(exc)})
                continue
            elapsed = time.perf_counter() - t_start
            rows_sent = batches * concurrency * batch_size
            ramp.append({
                "concurrency": concurrency,
                "batches": batches * concurrency,
                "rows_sent": rows_sent,
                "accepted": acc, "duplicates": dup, "quarantined": quar,
                "assessments": asm,
                "elapsed_s": round(elapsed, 2),
                "rows_per_s": round(rows_sent / elapsed, 1) if elapsed else None,
                "latency": _latency_stats(lat),
            })
            totals["accepted"] += acc
            totals["duplicates"] += dup
            totals["quarantined"] += quar
            totals["assessments"] += asm
    return {"ramp": ramp, "totals": totals, "batch_size": batch_size,
            "nonce": nonce}


async def phase_query(base_url: str, repeats: int = 10) -> dict:
    """Read-path latency across the three query shapes the UI actually uses."""
    endpoints = [
        ("queue_filtered", "GET",
         "/v2/incidents?limit=50&activity=acute&min_confidence=0.5"),
        ("observations_bbox", "GET",
         "/v2/observations?bbox=69.5,22.0,70.5,23.0&page_size=200"),
        ("observations_deep_page", "GET",
         "/v2/observations?page=10&page_size=200"),
        ("observations_sensor_time", "GET",
         "/v2/observations?sensor=viirs&min_confidence=nominal&page_size=100"),
    ]
    out: dict[str, dict | list[str]] = {}
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for name, method, path in endpoints:
            samples: list[float] = []
            status_counts: dict[int, int] = {}
            for _ in range(repeats):
                t0 = time.perf_counter()
                try:
                    r = await client.request(method, f"{base_url}{path}")
                    samples.append((time.perf_counter() - t0) * 1000.0)
                    status_counts[r.status_code] = (
                        status_counts.get(r.status_code, 0) + 1
                    )
                except httpx.HTTPError as exc:
                    errors.append(f"{name}: {exc}")
            out[name] = {**_latency_stats(samples), "status_counts": status_counts}
            if errors:
                out["_errors"] = errors
    return out


async def phase_db_growth(
    base_url: str, *, target_rows: int, batch_size: int, checkpoints: int,
) -> dict:
    """Grow the observations table toward ``target_rows`` (pipeline OFF).

    Rows are inserted with process=false (raw persistence only — the growth
    curve is about table size, not pipeline cost), and queue/observation
    latency is sampled at evenly spaced row-count checkpoints.
    """
    nonce = uuid.uuid4().hex[:12]
    rng = random.Random(MODEL_SEED)
    samples: list[dict] = []
    inserted = 0
    dup = quar = 0
    seq = 0
    t_start = time.perf_counter()

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:

        async def measure() -> dict:
            """One queue + one bbox read at the current table size."""
            out: dict = {}
            t0 = time.perf_counter()
            r = await client.get(f"{base_url}/v2/incidents?limit=50")
            out["queue_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            out["queue_status"] = r.status_code
            t0 = time.perf_counter()
            r = await client.get(
                f"{base_url}/v2/observations"
                "?bbox=69.5,22.0,70.5,23.0&page_size=100"
            )
            out["bbox_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            out["bbox_status"] = r.status_code
            return out

        while inserted < target_rows:
            n = min(batch_size, target_rows - inserted)
            rows = _make_rows(n, rng, f"growth-{nonce}-{seq}")
            r = await client.post(
                f"{base_url}/v2/observations?process=false",
                json={"observations": rows,
                      "source_batch_id": f"ltg-{nonce}-{seq}"},
            )
            seq += 1
            if r.status_code != 201:
                return {
                    "status": "error",
                    "http_status": r.status_code,
                    "detail": r.text[:300],
                    "rows_inserted": inserted,
                }
            body = r.json()
            inserted += body.get("accepted", 0)
            dup += body.get("duplicates", 0)
            quar += body.get("quarantined", 0)
            # Checkpoint when we cross the next even fraction of the target.
            next_cp = int((len(samples) + 1) * target_rows / max(checkpoints, 1))
            if inserted >= next_cp or inserted >= target_rows:
                m = await measure()
                m["rows_total"] = inserted
                samples.append(m)

    elapsed = time.perf_counter() - t_start
    queue_ms = [s["queue_ms"] for s in samples if s.get("queue_ms") is not None]
    bbox_ms = [s["bbox_ms"] for s in samples if s.get("bbox_ms") is not None]
    return {
        "status": "ok",
        "target_rows": target_rows,
        "rows_inserted": inserted,
        "duplicates": dup,
        "quarantined": quar,
        "elapsed_s": round(elapsed, 2),
        "rows_per_s": round(inserted / elapsed, 1) if elapsed else None,
        "checkpoints": samples,
        "queue_latency": _latency_stats(queue_ms),
        "bbox_latency": _latency_stats(bbox_ms),
    }


async def phase_sustained(
    base_url: str, *, duration_s: int, readers: int, writers: int,
    batch_size: int, seed: int,
) -> dict:
    """Mixed load for ``duration_s`` seconds: readers + writers in parallel."""
    rng = random.Random(seed)
    nonce = uuid.uuid4().hex[:12]
    stop_at = time.monotonic() + duration_s
    lat: dict[str, list[float]] = {"read": [], "write": []}
    errors: dict[str, int] = {"read": 0, "write": 0}
    status_errors: dict[str, list[str]] = {"read": [], "write": []}
    reads = writes = 0
    seq = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:

        async def reader() -> None:
            nonlocal reads
            paths = [
                "/v2/incidents?limit=50",
                "/v2/observations?page_size=100",
                "/v2/observations?bbox=69.5,22.0,70.5,23.0&page_size=50",
            ]
            i = 0
            while time.monotonic() < stop_at:
                path = paths[i % len(paths)]
                i += 1
                t0 = time.perf_counter()
                try:
                    r = await client.get(f"{base_url}{path}")
                    lat["read"].append((time.perf_counter() - t0) * 1000.0)
                    if r.status_code >= 500:
                        errors["read"] += 1
                        status_errors["read"].append(f"{r.status_code} {path}")
                    else:
                        reads += 1
                except httpx.HTTPError:
                    errors["read"] += 1

        async def writer() -> None:
            nonlocal writes, seq
            while time.monotonic() < stop_at:
                my_seq = seq
                seq += 1
                rows = _make_rows(batch_size, rng, f"sus-{nonce}-{my_seq}")
                t0 = time.perf_counter()
                try:
                    r = await client.post(
                        f"{base_url}/v2/observations",
                        json={"observations": rows,
                              "source_batch_id": f"lts-{nonce}-{my_seq}"},
                    )
                    lat["write"].append((time.perf_counter() - t0) * 1000.0)
                    if r.status_code == 201:
                        writes += 1
                    else:
                        errors["write"] += 1
                        status_errors["write"].append(str(r.status_code))
                except httpx.HTTPError:
                    errors["write"] += 1
                await asyncio.sleep(0.25)  # keep writers from starving readers

        await asyncio.gather(
            *(reader() for _ in range(readers)),
            *(writer() for _ in range(writers)),
        )

    total_ok = reads + writes
    total = total_ok + sum(errors.values())
    return {
        "duration_s": duration_s,
        "readers": readers,
        "writers": writers,
        "requests_ok": {"read": reads, "write": writes},
        "requests_per_s": round(total_ok / duration_s, 1) if duration_s else None,
        "errors": errors,
        "error_examples": {k: v[:5] for k, v in status_errors.items() if v},
        "error_rate": round(sum(errors.values()) / max(total, 1), 4),
        "read_latency": _latency_stats(lat["read"]),
        "write_latency": _latency_stats(lat["write"]),
    }


# =====================================================================
# Main
# =====================================================================
ALL_PHASES = ("cold", "ingest", "query", "growth", "sustained")


async def _run(args: argparse.Namespace) -> dict:
    report: dict = {
        "tool": "loadtest",
        "base_url": args.base_url,
        "phases_requested": args.phases,
        "phases": {},
        "skipped": {},
    }

    probe = await _probe_api(args.base_url)
    report["health"] = probe
    if not probe["reachable"]:
        report["status"] = "api_unreachable"
        report["skipped"] = {p: "API unreachable" for p in args.phases}
        return report
    if not probe["ready"]:
        # Live but not ready (DB down): every phase here needs the DB except
        # health itself — skip rather than generate misleading numbers.
        report["status"] = "api_not_ready"
        report["skipped"] = {
            p: "health/ready reported not_ready (database unreachable)"
            for p in args.phases
        }
        return report

    report["status"] = "ok"
    wanted = args.phases

    if "cold" in wanted:
        print("  [phase] cold latency ...")
        report["phases"]["cold"] = await phase_cold(args.base_url)
    if "ingest" in wanted:
        print("  [phase] ingest ramp ...")
        report["phases"]["ingest"] = await phase_ingest(
            args.base_url, batch_size=args.batch_size,
            batches=args.batches, seed=args.seed,
        )
    if "query" in wanted:
        print("  [phase] query latency ...")
        report["phases"]["query"] = await phase_query(args.base_url)
    if "growth" in wanted:
        target = args.growth_rows or settings.loadtest_db_rows
        print(f"  [phase] db growth -> {target} rows ...")
        report["phases"]["growth"] = await phase_db_growth(
            args.base_url, target_rows=target,
            batch_size=args.growth_batch, checkpoints=args.growth_checkpoints,
        )
    if "sustained" in wanted:
        print(f"  [phase] sustained mixed load ({args.duration}s) ...")
        report["phases"]["sustained"] = await phase_sustained(
            args.base_url, duration_s=args.duration,
            readers=args.readers, writers=args.writers,
            batch_size=args.batch_size, seed=args.seed,
        )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="ThermoWatch API load test")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument(
        "--phases", default=",".join(ALL_PHASES),
        help=f"Comma-separated subset of: {','.join(ALL_PHASES)}",
    )
    ap.add_argument("--batch-size", type=int, default=50,
                    help="Rows per ingest batch (ingest + sustained phases)")
    ap.add_argument("--batches", type=int, default=4,
                    help="Batch groups per concurrency level (ingest phase)")
    ap.add_argument("--seed", type=int, default=MODEL_SEED)
    ap.add_argument("--growth-rows", type=int, default=None,
                    help=f"Target rows for growth phase "
                         f"(default: settings.loadtest_db_rows="
                         f"{settings.loadtest_db_rows})")
    ap.add_argument("--growth-batch", type=int, default=500)
    ap.add_argument("--growth-checkpoints", type=int, default=5)
    ap.add_argument("--duration", type=int, default=20,
                    help="Seconds for the sustained phase")
    ap.add_argument("--readers", type=int, default=4)
    ap.add_argument("--writers", type=int, default=2)
    ap.add_argument("--out", default=str(DEFAULT_REPORT))
    args = ap.parse_args()

    requested = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = [p for p in requested if p not in ALL_PHASES]
    if unknown:
        ap.error(f"unknown phase(s): {', '.join(unknown)}")
    args.phases = requested

    report = asyncio.run(_run(args))
    path = _write_report(report, Path(args.out))

    status = report["status"]
    if status != "ok":
        reason = "; ".join(
            f"{p}: {why}" for p, why in report["skipped"].items()
        ) or status
        print(f"  [skip] load test not run — {reason}")
        print(f"  [ok] report written to {path}")
        sys.exit(0)  # graceful degradation: never fail the build

    for name, data in report["phases"].items():
        print(f"  [done] {name}: {json.dumps(data, default=str)[:200]}")
    print(f"  [ok] report written to {path}")


if __name__ == "__main__":
    main()