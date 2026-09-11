from app.services import event_store

DAY = 86_400_000


def setup_function(_):
    event_store._reset_for_tests()


def test_cell_id_stable():
    assert event_store.cell_id(22.4701, 70.0601) == event_store.cell_id(22.4702, 70.0602)


def test_consecutive_days_and_sta_rule():
    cell = "t1:t1"
    t0 = 1_750_000_000_000
    for d in range(6):
        event_store.record_cell(cell, t0 + d * DAY)
    out = event_store.persistence_for(cell, t0 + 5 * DAY)
    assert out["consecutive_days"] == 6
    assert out["regime"] == "persistent"  # STA rule: >=5 detection-days


def test_rolling_30d_window_not_counter():
    cell = "t2:t2"
    t0 = 1_750_000_000_000
    for d in range(40):  # 40 daily hits, only 30 may count
        event_store.record_cell(cell, t0 + d * DAY)
    out = event_store.persistence_for(cell, t0 + 39 * DAY)
    assert out["detections_30d"] <= 30


def test_append_assigns_ids_and_caps():
    e = event_store.append({"lat": 1.0, "lon": 2.0})
    assert e["id"].startswith("TW-")
    assert event_store.get(e["id"]) is not None
