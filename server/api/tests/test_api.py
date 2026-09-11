import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import event_store


@pytest.fixture()
def client():
    event_store._reset_for_tests()
    with TestClient(app) as c:  # lifespan seeds history
        yield c


def _det(lat, lon, frp=150):
    return {"latitude": lat, "longitude": lon, "frp": frp, "bright_ti4": 350, "confidence": 85,
            "satellite": "VIIRS-SNPP", "daynight": "N", "acq_epoch_ms": 1_750_000_000_000}


def test_healthz(client):
    r = client.get("/api/v1/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "near-real-time" in r.json()["realtime_claim"]


def test_ingest_roundtrip(client):
    r = client.post("/api/v1/ingest/events", json=[_det(11.11, 71.11), _det(11.12, 71.12)])
    assert r.status_code == 201 and r.json()["ingested"] == 2
    ev = client.get("/api/v1/events?window_hours=24").json()
    assert len(ev) >= 2


def test_predict_validation(client):
    ok = client.post("/api/v1/predict", json={"frp": 200, "persist_days": 8})
    assert ok.status_code == 200
    body = ok.json()
    assert body["classification"]["primary"] in ("industrial", "persistent", "wildfire", "agricultural")
    assert 0 <= body["risk"]["score"] <= 100
    assert client.post("/api/v1/predict", json={"frp": -5}).status_code == 422


def test_model_card(client):
    r = client.get("/api/v1/model/card")
    assert r.status_code == 200
    assert r.json()["served_by"] in ("tw-ensemble-v1", "stgnn-v0", "heuristic-ensemble-v0")
    assert len(r.json()["classes"]) == 10
