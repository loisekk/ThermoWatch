"""Rolling per-cell FIRMS detection history (live hotspot tracking, Scene 2.0).

Bounded memory: 500 detections/cell, cells evicted LRU beyond 400 ids. In this
codebase every FIRMS detection IS an event (TW-xxxxx), so the honest per-detection
scene for an event = every raw VIIRS 375 m detection recorded in that event's
400 m cell (and near-neighbours) — per-detection placement, never a centroid ball.
The sim seed funnels through the same `pipeline.enrich` hook, so demo mode gets
per-detection scenes without any second code path.
"""
from __future__ import annotations

import threading
from collections import OrderedDict, deque

from app.core.config import settings

_MAX_CELLS = 400
_MAX_PER_CELL = 500
_LOCK = threading.Lock()
_BUFFERS: "OrderedDict[str, deque]" = OrderedDict()

DAY_MS = 86_400_000


def record(cell: str, lat: float, lon: float, frp_mw: float,
           brightness_k: float, acq_epoch_ms: int, sat: str | None = None) -> None:
    with _LOCK:
        buf = _BUFFERS.get(cell)
        if buf is None:
            _BUFFERS[cell] = buf = deque(maxlen=_MAX_PER_CELL)
            _BUFFERS.move_to_end(cell)
            while len(_BUFFERS) > _MAX_CELLS:
                _BUFFERS.popitem(last=False)
        buf.append({"lat": lat, "lon": lon, "frp_mw": frp_mw,
                    "brightness_k": brightness_k, "acq_epoch_ms": acq_epoch_ms,
                    "acq_at": _iso(acq_epoch_ms), "sat": sat})


def _iso(epoch_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc) \
        .isoformat().replace("+00:00", "Z")


def known(cell: str) -> bool:
    with _LOCK:
        return bool(_BUFFERS.get(cell))


def snapshot(cell: str, days: int = 30) -> list[dict]:
    cutoff = _now_ms() - days * DAY_MS
    with _LOCK:
        buf = _BUFFERS.get(cell)
        if not buf:
            return []
        return [{k: d[k] for k in ("lat", "lon", "frp_mw", "brightness_k",
                                   "acq_epoch_ms", "acq_at", "sat")}
                for d in buf if d["acq_epoch_ms"] >= cutoff]


def reset() -> None:  # tests
    with _LOCK:
        _BUFFERS.clear()


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def cell_id(lat: float, lon: float) -> str:
    """Same 400 m cell key as the event store (kept in sync with TW_CELL_DEG)."""
    d = settings.cell_deg
    return f"{round(lat / d)}:{round(lon / d)}"
