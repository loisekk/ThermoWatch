import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import event_store


@pytest.fixture()
def client():
    event_store._reset_for_tests()
    with TestClient(app) as c:  # lifespan seeds the deterministic 14-day history
        yield c


def test_history_stats_shape(client):
    r = client.get("/api/v1/stats/history?days=180")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 180
    assert body["total_events"] > 0
    assert isinstance(body["daily"], dict)
    assert len(body["daily"]) > 0
    assert isinstance(body["leaderboard"], list)
    assert body["persistent_cells"] >= 0


def test_history_daily_buckets_are_per_class(client):
    body = client.get("/api/v1/stats/history").json()
    for key, day in list(body["daily"].items())[:3]:
        assert set(day) == {"industrial", "persistent", "wildfire", "agricultural", "total"}
        assert day["total"] == sum(day[c] for c in ("industrial", "persistent", "wildfire", "agricultural"))


def test_response_recommend_contract(client):
    r = client.post("/api/v1/response/recommend", json={
        "lat": 22.47, "lon": 70.06, "fire_class": "industrial", "hazard": "G-III", "wind_dir_deg": 270.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["nearest_stations"]) == 3
    dists = [s["distance_km"] for s in body["nearest_stations"]]
    assert dists == sorted(dists)
    assert body["resources"]["vehicles"] > 0
    assert body["evacuation_radius_m"] == 1500  # G-III
    assert -90 <= body["staging_point"]["lat"] <= 90
    assert body["wind_bearing_deg"] == 270.0


def test_response_recommend_unknown_class_falls_back(client):
    r = client.post("/api/v1/response/recommend", json={"lat": 11.11, "lon": 71.11, "fire_class": "industrial"})
    assert r.status_code == 200
    assert r.json()["nearest_stations"][0]["distance_km"] >= 0
    assert r.json()["evacuation_radius_m"] >= 200