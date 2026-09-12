from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.data.facilities import FACILITIES
from app.services import event_store

router = APIRouter()
DAY = 86_400_000

@router.get("/events")
def list_events(window_hours: int = Query(24, ge=1, le=24 * 30),
                classes: str | None = None, min_risk: int = 0):
    ev = event_store.all_events()
    cut = ev[-1]["detected_at"] - window_hours * 3_600_000 if ev else 0
    sel = [e for e in ev if e["detected_at"] >= cut and e["risk"]["score"] >= min_risk]
    if classes:
        want = set(classes.split(","))
        sel = [e for e in sel if e["classification"]["primary"] in want]
    return sel[-2000:]

@router.get("/events/{event_id}")
def get_event(event_id: str):
    e = event_store.get(event_id)
    if not e: raise HTTPException(404, "unknown event")
    return e

@router.get("/stats/kpis")
def kpis():
    ev = event_store.all_events()
    now = ev[-1]["detected_at"] if ev else 0
    l24 = [e for e in ev if e["detected_at"] >= now - DAY]
    p24 = [e for e in ev if now - 2 * DAY <= e["detected_at"] < now - DAY]
    ind = [e for e in l24 if e["classification"]["primary"] == "industrial"]
    pers = [e for e in ev if e["detected_at"] >= now - 7 * DAY and e["persistence"]["regime"] == "persistent"]
    return {"active24": len(l24), "delta24": len(l24) - len(p24),
            "industrial_share": round(100 * len(ind) / len(l24), 1) if l24 else 0,
            "persistent_count": len(pers),
            "mean_confidence": round(sum(e["classification"]["confidence"] for e in l24) / len(l24), 1) if l24 else 0}

@router.get("/facilities")
def facilities():
    return FACILITIES

@router.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    """Uptime-robot / cron keep-warm probe — no auth in front of it by design.
    HEAD is accepted too: uptime monitors probe with HEAD, and Starlette's default
    GET-only route would otherwise answer 405 (Render's internal GET checker is fine)."""
    return {
        "status": "ok",
        "service": "thermowatch-api",
        "version": "1.0.0-sih",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "realtime_claim": "near-real-time (FIRMS 3-6h latency)",
    }
