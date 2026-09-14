"""LIVE WIRE endpoints. Poll-based (no WS taxonomy change — KB §21.6 stays verbatim).

Server-side corroboration: items carrying coordinates are matched against recent
FIRMS events (<= 75 km, <= 72 h) so the panel can show `↔ TW-xxxxx (12.4 km)` —
correlation is a distance/time signal for analysts, never verification.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.services import event_store, news_wire
from app.services.geo import haversine_km

router = APIRouter(prefix="/news", tags=["news"])

CORR_RADIUS_KM = 75.0
CORR_WINDOW_H = 72.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _recent_event_anchors(hours: float) -> list[tuple[str, float, float, int]]:
    """(id, lat, lon, detected_at_ms) of events inside the correlation window."""
    cut_ms = int((datetime.now(timezone.utc).timestamp() - hours * 3600) * 1000)
    return [(e["id"], e["lat"], e["lon"], e["detected_at"])
            for e in event_store.all_events() if e["detected_at"] >= cut_ms]


def _correlate(item: dict, anchors: list[tuple[str, float, float, int]]) -> dict:
    if item["lat"] is None or item["lon"] is None or not anchors:
        return {"nearby_event_ids": [], "correlation_km": None, "correlation_dt_h": None}
    pub_ms: int | None = None
    if item["published_at"]:
        try:
            pub_ms = int(datetime.fromisoformat(
                item["published_at"].replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pub_ms = None
    best: tuple[str, float, float] | None = None
    for eid, elat, elon, eat_ms in anchors:
        km = haversine_km(item["lat"], item["lon"], elat, elon)
        if km > CORR_RADIUS_KM:
            continue
        dt_h = abs(pub_ms - eat_ms) / 3_600_000 if pub_ms is not None else 0.0
        if pub_ms is not None and dt_h > CORR_WINDOW_H:
            continue
        if best is None or km < best[1]:
            best = (eid, km, dt_h)
    if best is None:
        return {"nearby_event_ids": [], "correlation_km": None, "correlation_dt_h": None}
    return {"nearby_event_ids": [best[0]],
            "correlation_km": round(best[1], 1),
            "correlation_dt_h": round(best[2], 1)}


@router.get("/feed")
async def feed(window_hours: int = Query(24, ge=1, le=168),
               bbox: str = Query("68,6,98,36"),
               limit: int = Query(120, ge=1, le=500)):
    statuses, items = await news_wire.fetch_all(window_hours=window_hours, bbox=bbox)
    anchors = _recent_event_anchors(CORR_WINDOW_H)
    out = []
    for it in items[:limit]:
        d = it.to_dict()
        d.update(_correlate(d, anchors))
        out.append(d)
    return {
        "generated_at": _now(), "ttl_s": news_wire.TTL_S,
        "window_hours": window_hours,
        "providers": [s.to_dict() for s in statuses],
        "items": out,
    }


@router.get("/providers")
async def providers():
    statuses, _ = await news_wire.fetch_all()
    return {"generated_at": _now(), "providers": [s.to_dict() for s in statuses]}
