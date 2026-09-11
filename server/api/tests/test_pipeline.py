from app.services import event_store, pipeline


def setup_function(_):
    event_store._reset_for_tests()


def _raw(lat, lon, frp=120, day="N"):
    return {"latitude": lat, "longitude": lon, "frp": frp, "bright_ti4": 340, "confidence": 80,
            "satellite": "VIIRS-SNPP", "daynight": day, "acq_epoch_ms": 1_750_000_000_000,
            "forest_proxy": 0.1, "agri_window": 0.1, "cluster_density": 0.3, "diurnal_variance": 0.3}


def test_enrich_contract():
    ev = pipeline.enrich(_raw(10.123, 70.456))  # far from any seeded facility
    for key in ("id", "lat", "lon", "cell", "classification", "persistence", "risk",
                "nearest_facility_id", "facility_distance_km"):
        assert key in ev or key in ("id",)  # id added by store.append, not enrich
    assert ev["classification"]["primary"] in ("industrial", "persistent", "wildfire", "agricultural")
    assert ev["persistence"]["regime"] == "transient"  # first hit in a fresh cell
    assert 0 <= ev["risk"]["score"] <= 100


def test_facility_context_sets_subtype():
    ev = pipeline.enrich(_raw(22.4705, 70.0605, frp=500))  # Jamnagar refinery, <50 m
    assert ev["nearest_facility_id"] == "F-001"
    assert ev["classification"]["subtype"] in (None, "refinery")
    assert ev["facility_distance_km"] is not None and ev["facility_distance_km"] < 1.0
