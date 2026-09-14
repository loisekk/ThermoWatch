"""LIVE WIRE service tests — normalizers, TTL cache/single-flight, stale last-good."""
import asyncio

import httpx

from app.services import news_wire as nw

DOC = {"articles": [{"url": "https://x.in/a", "title": "Steel plant fire in Jamshedpur",
                     "seendate": "20260914T060000Z", "domain": "x.in",
                     "sourcecountrycode": "IN"}]}
DOC_AGR = {"articles": [{"url": "https://x.in/b", "title": "Crop burning spreads across Punjab",
                         "seendate": "20260914T050000Z", "domain": "x.in",
                         "sourcecountrycode": "IN"}]}
GEO = {"features": [{"geometry": {"type": "Point", "coordinates": [86.2, 22.8]},
                     "properties": {"name": "Jamshedpur"}}]}
EONET = {"events": [{"id": "E1", "title": "Wildfire X", "link": "https://eonet/e1",
                     "categories": [{"id": "wildfires"}],
                     "geometry": [{"date": "2026-09-13T00:00:00Z",
                                   "coordinates": [77.0, 28.0], "type": "Point"}]}]}
GDACS = {"results": [{"eventid": 1, "episodeid": 1, "eventtype": "WF",
                      "latitude": 22.0, "longitude": 80.0,
                      "validdate": "2026-09-12T00:00:00Z", "country": "India"}]}


def _routes(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "api.gdeltproject.org":
        return httpx.Response(200, json=DOC if "/doc/" in str(request.url) else GEO)
    if host == "eonet.gsfc.nasa.gov":
        return httpx.Response(200, json=EONET)
    if host == "www.gdacs.org":
        return httpx.Response(200, json=GDACS)
    return httpx.Response(500)


def _client(routes) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(routes))


def test_normalizers():
    doc = nw.norm_gdelt_doc(DOC)[0]
    assert doc.grade == "article-country"
    assert doc.published_at == "2026-09-14T06:00:00Z"
    assert "industrial" in doc.categories
    assert nw.norm_gdelt_doc(DOC_AGR)[0].categories == ["agricultural"]
    g = nw.norm_gdelt_geo(GEO)[0]
    assert (g.lat, g.lon) == (22.8, 86.2) and g.grade == "geo-mention"
    e = nw.norm_eonet(EONET)[0]
    assert e.grade == "event" and e.categories == ["wildfire"]
    gd = nw.norm_gdacs(GDACS)[0]
    assert gd.url.startswith("https://www.gdacs.org/report.aspx")
    assert gd.lat == 22.0 and gd.country == "India"


def test_fetch_all_dedupes_and_sorts():
    nw.reset_cache()
    st, items = asyncio.run(nw.fetch_all(client=_client(_routes)))
    assert {s.provider for s in st} == {"gdelt-doc", "gdelt-geo", "eonet", "gdacs"}
    assert all(s.ok for s in st)
    assert len(items) == 4
    assert len({i.id for i in items}) == 4


def test_ttl_cache_single_flight():
    nw.reset_cache()
    calls = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _routes(request)

    client = _client(counting)
    asyncio.run(nw.fetch_all(client=client))
    first = calls["n"]
    assert first == 4  # one request per provider
    asyncio.run(nw.fetch_all(client=client))
    assert calls["n"] == first  # TTL cache: no refetch within window


def test_provider_error_is_stale_not_500():
    nw.reset_cache()
    state = {"fail": False}

    def flaky(request: httpx.Request) -> httpx.Response:
        if state["fail"] and request.url.host == "www.gdacs.org":
            return httpx.Response(500)
        return _routes(request)

    client = _client(flaky)
    asyncio.run(nw.fetch_all(client=client))
    # Expire only the gdacs entry (other providers stay TTL-fresh) so the second
    # round refetches it and hits the 500 -> last-good must serve, flagged stale.
    nw._CACHE["gdacs"].at = 0
    state["fail"] = True
    st, items = asyncio.run(nw.fetch_all(client=client))
    gd = [s for s in st if s.provider == "gdacs"][0]
    assert gd.stale is True and gd.ok is True
    assert any(i.provider == "gdacs" for i in items)  # last-good served


def test_first_call_error_reports_not_ok():
    nw.reset_cache()
    client = _client(lambda r: httpx.Response(500))
    st, items = asyncio.run(nw.fetch_all(client=client))
    assert all(s.ok is False for s in st) and items == []
    assert all(s.error for s in st)
