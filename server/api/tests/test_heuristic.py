from app.services import heuristic

BASE = {"frp": 100, "brightness_k": 330, "night_ratio": 0.3, "diurnal_variance": 0.4,
        "persist_days": 1, "facility_distance_km": None, "facility_hazard": None,
        "forest_proxy": 0.2, "agri_window": 0.1, "cluster_density": 0.3}


def test_scores_normalised():
    out = heuristic.classify(dict(BASE))
    assert abs(sum(out["scores"].values()) - 1.0) < 1e-6
    assert out["primary"] in ("industrial", "persistent", "wildfire", "agricultural")
    assert 55 <= out["confidence"] <= 97


def test_proximity_shifts_to_industrial():
    near = heuristic.classify({**BASE, "facility_distance_km": 0.1, "facility_hazard": "G-III", "frp": 400})
    far = heuristic.classify({**BASE, "facility_distance_km": 20.0, "forest_proxy": 0.9})
    assert near["scores"]["industrial"] > far["scores"]["industrial"]
    assert far["scores"]["wildfire"] > near["scores"]["wildfire"]


def test_persistence_rule():
    out = heuristic.classify({**BASE, "persist_days": 12, "facility_distance_km": 0.3})
    assert out["scores"]["persistent"] > out["scores"]["industrial"]


def test_risk_bounds_and_monotonic():
    lo = heuristic.score_risk({**BASE, "frp": 10}, 60)
    hi = heuristic.score_risk({**BASE, "frp": 900, "persist_days": 20, "facility_hazard": "G-III"}, 90)
    assert 0 <= lo["score"] <= 100 and 0 <= hi["score"] <= 100
    assert hi["score"] > lo["score"]
    assert hi["level"] in ("low", "moderate", "high", "critical")


def test_spread_rings_grow():
    rings = heuristic.spread_rings(22.0, 79.0, 300, "wildfire", 6.0, 270.0)
    radii = [r["radius_km"] for r in rings]
    assert radii == sorted(radii) and len(rings) == 3
    assert len(rings[0]["polygon"]) == 33  # 32-gon closed
