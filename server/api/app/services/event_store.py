"""In-memory event store with FIRMS-STA-aligned 400 m cell persistence tracking.
Repository interface keeps the DuckDB+H3 adapter a drop-in next step."""
import threading
from collections import defaultdict

from app.core.config import settings

_lock = threading.Lock()
_events: list[dict] = []
_cell_days: dict[str, set[int]] = defaultdict(set)          # cell → detection epoch-days
_cell_hits: dict[str, list[int]] = defaultdict(list)        # cell → detection epoch-ms (rolling 30 d)
_seq = 0

DAY_MS = 86_400_000
WINDOW_30D_MS = 30 * DAY_MS


def cell_id(lat: float, lon: float) -> str:
    d = settings.cell_deg
    return f"{round(lat / d)}:{round(lon / d)}"


def _count_30d(hits: list[int], epoch_ms: int) -> int:
    """Detections in the trailing 30-day window relative to the given timestamp."""
    cut = epoch_ms - WINDOW_30D_MS
    return sum(1 for t in hits if t > cut)


def persistence_for(cell: str, epoch_ms: int) -> dict:
    with _lock:
        days = _cell_days[cell]
        consecutive = 1
        d = epoch_ms // DAY_MS - 1
        while d in days:
            consecutive += 1
            d -= 1
        det30 = _count_30d(_cell_hits[cell], epoch_ms)
        regime = ("persistent" if consecutive >= settings.persistence_day_threshold
                  else "seasonal" if det30 >= 12 else "transient")
        return {"consecutive_days": consecutive, "detections_30d": det30, "regime": regime}


def record_cell(cell: str, epoch_ms: int) -> None:
    with _lock:
        _cell_days[cell].add(epoch_ms // DAY_MS)
        hits = _cell_hits[cell]
        hits.append(epoch_ms)
        # Prune beyond the rolling window to keep memory bounded.
        cut = epoch_ms - WINDOW_30D_MS
        _cell_hits[cell] = [t for t in hits if t > cut]


def append(event: dict) -> dict:
    global _seq
    with _lock:
        _seq += 1
        event["id"] = f"TW-{_seq:05d}"
        _events.append(event)
        if len(_events) > settings.max_events:
            del _events[: len(_events) - settings.max_events]
    return event


def all_events() -> list[dict]:
    with _lock:
        return list(_events)


def get(event_id: str) -> dict | None:
    with _lock:
        return next((e for e in _events if e["id"] == event_id), None)


def seed_if_empty() -> None:
    if _events:
        return
    from app.services.pipeline import enrich
    from app.services.simseed import generate_history
    for raw in generate_history():
        append(enrich(raw))


def _reset_for_tests() -> None:
    """Test-only: clear module state between pytest cases."""
    global _seq
    with _lock:
        _events.clear()
        _cell_days.clear()
        _cell_hits.clear()
        _seq = 0

