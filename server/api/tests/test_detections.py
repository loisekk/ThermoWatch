"""Per-cell detection ring buffer + /events/{id}/detections endpoint (Scene 2.0)."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.services import detection_buffer as db

client = TestClient(app)

NOW_MS = int(time.time() * 1000)


def _rec(cell: str, n: int = 3) -> None:
    for i in range(n):
        db.record(cell, 22.8 + i * 0.001, 86.2 + i * 0.001, 40 + i, 320 + i,
                  NOW_MS - i * 3_600_000, "VIIRS")


def test_record_snapshot():
    db.reset()
    _rec("100:200")
    snap = db.snapshot("100:200")
    assert len(snap) == 3 and snap[0]["frp_mw"] == 40
    assert snap[0]["acq_at"].endswith("Z")
    assert db.known("100:200") and not db.known("999:999")


def test_cap_500_per_cell():
    db.reset()
    for i in range(600):
        db.record("c", 22.0, 86.0, 10, 300, NOW_MS)
    assert len(db.snapshot("c")) == 500


def test_days_filter():
    db.reset()
    db.record("d", 1.0, 2.0, 10, 300, NOW_MS - 40 * db.DAY_MS)
    db.record("d", 1.0, 2.0, 10, 300, NOW_MS)
    assert len(db.snapshot("d", days=30)) == 1


def test_lru_cell_eviction():
    db.reset()
    for c in range(400):
        db.record(str(c), 1.0, 2.0, 10, 300, NOW_MS)
    db.record("400", 1.0, 2.0, 10, 300, NOW_MS)  # pushes out the LRU entry
    assert not db.known("0") and db.known("400")


def test_endpoint_200_and_404():
    db.reset()
    assert client.get("/api/v1/events/NOPE-1/detections").status_code == 404
    _rec(db.cell_id(22.8, 86.2), 1)
    # Resolve a real event seeded on that cell via the store
    from app.services import event_store
    ev = next(e for e in event_store.all_events() if e["cell"] == db.cell_id(22.8, 86.2))
    r = client.get(f"/api/v1/events/{ev['id']}/detections?days=30")
    assert r.status_code == 200 and r.json()["count"] == 1
    assert {"lat", "lon", "frp_mw", "brightness_k", "acq_at", "sat"} <= set(r.json()["detections"][0])
