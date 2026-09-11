"""Historical analysis endpoint (PS deliverable: "Historical analysis dashboard")."""
from collections import Counter

from fastapi import APIRouter

from app.services import event_store

router = APIRouter()
DAY_MS = 86_400_000
CLASSES = ("industrial", "persistent", "wildfire", "agricultural")


@router.get("/stats/history")
def history_stats(days: int = 180):
    """Daily aggregates per class + facility leaderboard + persistence trend.

    `days` is a server-retention window: the in-memory store returns whatever
    falls inside it (14-day deterministic seed, or the live rolling buffer).
    """
    ev = event_store.all_events()
    now = max((e["detected_at"] for e in ev), default=0)
    cut = now - days * DAY_MS
    hist = [e for e in ev if e["detected_at"] >= cut]

    daily: dict[str, dict[str, int]] = {}
    for e in hist:
        key = str(e["detected_at"] // DAY_MS)
        row = daily.setdefault(key, {c: 0 for c in CLASSES} | {"total": 0})
        cls = e["classification"]["primary"]
        row[cls] += 1
        row["total"] += 1

    fac = Counter(e["nearest_facility_id"] for e in hist if e["nearest_facility_id"])
    leaderboard = [{"facility_id": fid, "count": n} for fid, n in fac.most_common(10)]

    # Distinct 400 m cells in a persistent STA regime — not raw detections,
    # so double-counted daily hits never inflate the "persistent sources" figure.
    persistent_cells = len({e["cell"] for e in hist if e["persistence"]["regime"] == "persistent"})

    return {
        "days": days,
        "total_events": len(hist),
        "daily": daily,
        "leaderboard": leaderboard,
        "persistent_cells": persistent_cells,
    }