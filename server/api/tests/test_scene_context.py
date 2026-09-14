"""Scene context (OSM Overpass proxy) — parsing, caps, cache, fallback, endpoint."""
import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import scene_context as sc

client = TestClient(app)


def _geom(o_lat, o_lon, n, size=0.001):
    return [{"lat": o_lat, "lon": o_lon},
            {"lat": o_lat, "lon": o_lon + size},
            {"lat": o_lat - size, "lon": o_lon + size},
            {"lat": o_lat - size, "lon": o_lon},
            {"lat": o_lat, "lon": o_lon}]


def _buildings(n, tags=None):
    els = []
    for i in range(n):
        els.append({"type": "way", "id": 100 + i, "tags": tags or {"building": "industrial"},
                    "geometry": _geom(22.8, 86.0, i, 0.0008)})
    return els


def _ctx_body(n_bld=4):
    return {"elements": [
        {"type": "node", "id": 1, "lat": 22.81, "lon": 86.21,
         "tags": {"natural": "tree", "diameter_crown": "10"}},
        {"type": "way", "id": 2, "tags": {"height": "12 m", "building": "industrial"},
         "geometry": _geom(22.8, 86.2, 0)},
        {"type": "way", "id": 3, "tags": {"building:levels": "3", "building": "residential"},
         "geometry": _geom(22.8 + 0.001, 86.2, 0)},
        {"type": "way", "id": 4, "tags": {"building": "house"},
         "geometry": _geom(22.8 - 0.001, 86.2, 0)},
        {"type": "way", "id": 5, "tags": {"highway": "secondary"},
         "geometry": [{"lat": 22.79, "lon": 86.19}, {"lat": 22.8, "lon": 86.2}]},
        {"type": "way", "id": 6, "tags": {"natural": "water"},
         "geometry": _geom(22.82, 86.22, 0)},
        {"type": "way", "id": 7, "tags": {"landuse": "forest"},
         "geometry": _geom(22.78, 86.24, 0)},
        *_buildings(n_bld),
    ]}


def _route(body, status=200, call=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if call:
            call["n"] += 1
        if status != 200:
            return httpx.Response(status, json={"remark": "err"})
        return httpx.Response(200, json=body)
    return handler


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_heights_and_kinds():
    assert sc._height_m({"height": "12 m"}, "generic") == (12.0, "tag:height")
    assert sc._height_m({"building:levels": "3"}, "residential") == (9.6, "tag:levels")
    assert sc._height_m({}, "industrial") == (8.0, "estimated")
    assert sc._kind({"building": "factory"}) == "industrial"
    assert sc._kind({"building": "retail"}) == "commercial"
    assert sc._kind({"building": "hut"}) == "residential"
    assert sc._kind({"building": "yes"}) == "generic"


def test_parse_heights_crowns_and_lists():
    out = sc._parse(_ctx_body(), 22.8, 86.2)
    b = {x["id"]: x for x in out["buildings"]}
    assert b[2]["height_m"] == 12.0 and b[2]["height_source"] == "tag:height"
    assert b[3]["height_source"] == "tag:levels"
    assert b[4]["height_source"] == "estimated" and b[4]["kind"] == "residential"
    assert out["trees"][0]["crown_m"] == 5.0
    assert out["roads"][0]["cls"] == "secondary"
    assert len(out["water"]) == 1 and len(out["wood"]) == 1


def test_caps_enforced():
    out = sc._parse(_ctx_body(n_bld=700), 22.8, 86.2)
    assert len(out["buildings"]) == sc.CAPS["buildings"]


def test_cache_and_single_fetch():
    sc.reset_cache()
    calls = {"n": 0}
    c = _client(_route(_ctx_body(), call=calls))
    doc1 = asyncio.run(sc.get_context(22.8, 86.2, client=c))
    assert doc1["source"] == "osm-overpass"
    assert doc1["counts"]["buildings"] == 7  # 3 tagged + 4 generic from fixture
    asyncio.run(sc.get_context(22.8, 86.2, client=c))  # cached -> no second call
    assert calls["n"] == 1


def test_instance_fallback():
    sc.reset_cache()
    state = {"tries": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        state["tries"] += 1
        if state["tries"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=_ctx_body())

    c = _client(flaky)
    doc = asyncio.run(sc.get_context(22.8, 86.2, client=c))
    assert doc["source"] == "osm-overpass"


def test_all_down_is_unavailable_not_error():
    sc.reset_cache()
    c = _client(lambda r: httpx.Response(500))
    doc = asyncio.run(sc.get_context(22.8, 86.2, client=c))
    assert doc["source"] == "unavailable"
    assert doc["counts"] == {}


def test_endpoint_200_and_validation():
    sc.reset_cache()
    sc._CACHE[(22.8, 86.2, 1200)] = (time.time(), {"source": "osm-overpass",
                                                   "snapshot_at": "x", "radius_m": 1200,
                                                   "center": {"lat": 22.8, "lon": 86.2},
                                                   "attribution": "c",
                                                   "counts": {"buildings": 2},
                                                   "buildings": [], "trees": [],
                                                   "roads": [], "wood": [],
                                                   "landuse": [], "water": []})
    r = client.get("/api/v1/scene/context", params={"lat": 22.8, "lon": 86.2})
    assert r.status_code == 200 and r.json()["source"] == "osm-overpass"
    assert client.get("/api/v1/scene/context", params={"lat": 95, "lon": 86}).status_code == 422


def test_fresh_rate_guard():
    sc.reset_cache()
    sc.mark_refresh(22.8, 86.2, 1200)
    assert sc.can_refresh(22.8, 86.2, 1200) is False
    r = client.get("/api/v1/scene/context",
                   params={"lat": 22.8, "lon": 86.2, "fresh": "true"})
    assert r.status_code == 429