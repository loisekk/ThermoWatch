"""LIVE WIRE — open-source news corroboration providers (zero-secret).

Providers: GDELT DOC 2.0 (article list), GDELT GEO 2.0 (geojson mentions),
NASA EONET v3 (curated natural events), GDACS (EC-JRC/UN alerts).
Server-cached TTL 300 s, single-flight per provider, last-good-on-error with a
`stale` flag: a provider outage is visible, never a 500, never a blank panel.

Honesty contract: items are UNVERIFIED open-source reporting; wording is
"near-real-time wire" only; corroboration is never confirmation.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

TTL_S = 300.0
TIMEOUT_S = 8.0
UA = "ThermoWatch-SIH26162/1.0 (SIH research dashboard)"

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GEO_URL = "https://api.gdeltproject.org/api/v2/geo/geo"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events"

DOC_QUERY = (
    '("(fire OR blaze OR wildfire)" OR ("crop burning" OR stubble) OR '
    '((industrial OR factory OR "steel plant" OR refinery) AND (fire OR blaze))) '
    "sourcecountry:india"
)
GEO_QUERY = '(fire OR wildfire OR "crop burning" OR "industrial fire")'

_CATEGORY_TERMS = {
    "agricultural": ("crop", "stubble", "straw burning", "parali"),
    "industrial": ("factory", "industrial", "steel", "refinery", "plant", "warehouse"),
    "wildfire": ("wildfire", "forest fire", "blaze", "fire"),
    "disaster": ("disaster", "evacuat", "cyclone", "flood", "earthquake"),
}


def _first(d: dict, keys: Iterable[str], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str) -> str:
    """Tolerant ISO-8601 parse; GDELT's compact %Y%m%dT%H%M%SZ first, then fromisoformat."""
    s = (raw or "").strip()
    if not s:
        return _iso(datetime.now(timezone.utc))
    try:
        return _iso(datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
        return _iso(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
    except ValueError:
        return _iso(datetime.now(timezone.utc))


def _item_id(provider: str, key: str) -> str:
    return f"{provider}:{hashlib.sha1((key or 'empty').encode('utf-8')).hexdigest()[:12]}"


def _categories(title: str) -> list[str]:
    t = title.lower()
    return [c for c, terms in _CATEGORY_TERMS.items() if any(w in t for w in terms)]


def _matched_terms(title: str) -> list[str]:
    t = title.lower()
    return [w for w in ("fire", "blaze", "wildfire", "stubble", "crop", "factory",
                        "industrial", "steel", "refinery") if w in t]


@dataclass
class NewsItem:
    provider: str
    grade: str  # "event" | "geo-mention" | "article-country"
    title: str
    url: str
    published_at: str | None
    lat: float | None = None
    lon: float | None = None
    country: str | None = None
    source_domain: str | None = None
    categories: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return _item_id(self.provider, self.url or f"{self.title}@{self.lat},{self.lon}")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "provider": self.provider, "grade": self.grade,
            "title": self.title, "url": self.url, "published_at": self.published_at,
            "lat": self.lat, "lon": self.lon, "country": self.country,
            "source_domain": self.source_domain, "categories": self.categories,
            "matched_terms": self.matched_terms,
        }


@dataclass
class ProviderStatus:
    provider: str
    ok: bool
    stale: bool
    last_sync_at: str | None
    items: int
    latency_ms: int
    error: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class _Cached:
    items: list[NewsItem] = field(default_factory=list)
    at: float = 0.0
    ok: bool = False
    latency_ms: int = 0
    error: str | None = None



# ---------------------------------------------------------------- normalizers
def norm_gdelt_doc(payload: Any) -> list[NewsItem]:
    arts = payload.get("articles") if isinstance(payload, dict) else payload
    out: list[NewsItem] = []
    for a in arts or []:
        if not isinstance(a, dict):
            continue
        title = _first(a, ("title",)) or ""
        url = _first(a, ("url",)) or ""
        if not title or not url:
            continue
        out.append(NewsItem(
            provider="gdelt-doc", grade="article-country", title=title, url=url,
            published_at=_parse_iso(_first(a, ("seendate",)) or ""),
            country=_first(a, ("sourcecountrycode",)),
            source_domain=_first(a, ("domain",)),
            categories=_categories(title), matched_terms=_matched_terms(title)))
    return out


def norm_gdelt_geo(payload: Any) -> list[NewsItem]:
    out: list[NewsItem] = []
    for f in (payload or {}).get("features", []):
        geom = (f or {}).get("geometry") or {}
        coords = geom.get("coordinates") or []
        props = f.get("properties") or {}
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        title = _first(props, ("name", "title", "label")) or "GDELT location mention"
        url = _first(props, ("url", "shareimage", "link")) or ""
        out.append(NewsItem(
            provider="gdelt-geo", grade="geo-mention",
            title=f"News geography: {title}", url=url,
            published_at=_parse_iso(str(_first(props, ("date", "published_at")) or "")),
            lon=float(coords[0]), lat=float(coords[1]),
            categories=_categories(title), matched_terms=_matched_terms(title)))
    return out


def norm_eonet(payload: Any) -> list[NewsItem]:
    out: list[NewsItem] = []
    for ev in (payload or {}).get("events", []):
        geos = ev.get("geometry") or []
        if not geos:
            continue
        coords = geos[-1].get("coordinates") or []
        if len(coords) < 2:
            continue
        title = _first(ev, ("title",)) or "EONET event"
        cat_ids = [c.get("id") for c in ev.get("categories", [])]
        srcs = ev.get("sources") or []
        url = _first(ev, ("link",)) or (srcs[0].get("url") if srcs else "") \
            or "https://eonet.gsfc.nasa.gov/"
        out.append(NewsItem(
            provider="eonet", grade="event", title=title, url=url,
            published_at=_parse_iso(str(_first(geos[-1], ("date",)) or "")),
            lon=float(coords[0]), lat=float(coords[1]),
            categories=["wildfire"] if "wildfires" in cat_ids else ["disaster"],
            matched_terms=_matched_terms(title)))
    return out


def norm_gdacs(payload: Any) -> list[NewsItem]:
    out: list[NewsItem] = []
    evs = payload.get("results") if isinstance(payload, dict) and "results" in payload \
        else (payload.get("events") if isinstance(payload, dict) else payload)
    if not isinstance(evs, list):
        return []
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        lat = _first(ev, ("latitude", "lat"))
        lon = _first(ev, ("longitude", "lon", "lng"))
        loc = ev.get("location")
        if isinstance(loc, dict):
            lat = lat if lat is not None else _first(loc, ("lat", "latitude"))
            lon = lon if lon is not None else _first(loc, ("lon", "lng", "longitude"))
        if lat is None or lon is None:
            continue
        etype = _first(ev, ("eventtype", "event_type")) or "?"
        title = _first(ev, ("name", "title")) or f"GDACS {etype} alert"
        eid = _first(ev, ("eventid", "event_id")) or ""
        out.append(NewsItem(
            provider="gdacs", grade="event", title=str(title),
            url=(f"https://www.gdacs.org/report.aspx?eventtype={etype}&eventid={eid}"
                 f"&episodeid={_first(ev, ('episodeid',), 1)}"),
            published_at=_parse_iso(str(_first(ev, ("validdate", "fromdate",
                                                    "startdate")) or "")),
            lat=float(lat), lon=float(lon),
            country=_first(ev, ("country",)),
            categories=["wildfire"] if etype == "WF" else ["disaster"],
            matched_terms=_matched_terms(str(title))))
    return out

_CACHE: dict[str, _Cached] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def reset_cache() -> None:  # tests
    _CACHE.clear()


# ------------------------------------------------------------------- fetchers
async def _fetch_gdelt_doc(client: httpx.AsyncClient, wh: int, bbox: str) -> list[NewsItem]:
    r = await client.get(GDELT_DOC_URL, params={
        "query": DOC_QUERY, "mode": "artlist", "format": "json",
        "sort": "datedesc", "maxrecords": 100, "timespan": f"{wh}h"})
    r.raise_for_status()
    return norm_gdelt_doc(r.json())


async def _fetch_gdelt_geo(client: httpx.AsyncClient, wh: int, bbox: str) -> list[NewsItem]:
    r = await client.get(GDELT_GEO_URL, params={
        "query": GEO_QUERY, "format": "geojson", "timespan": f"{min(wh, 24 * 7)}h"})
    r.raise_for_status()
    return norm_gdelt_geo(r.json())


async def _fetch_eonet(client: httpx.AsyncClient, wh: int, bbox: str) -> list[NewsItem]:
    params: dict[str, Any] = {"category": "wildfires", "status": "open",
                              "days": max(1, min(wh // 24 or 1, 30))}
    if bbox:
        params["bbox"] = bbox
    r = await client.get(EONET_URL, params=params)
    r.raise_for_status()
    return norm_eonet(r.json())


async def _fetch_gdacs(client: httpx.AsyncClient, wh: int, bbox: str) -> list[NewsItem]:
    now = datetime.now(timezone.utc)
    r = await client.get(GDACS_URL, params={
        "eventtype": "WF",
        "startdate": (now - timedelta(hours=wh)).strftime("%Y-%m-%d"),
        "enddate": now.strftime("%Y-%m-%d")})
    r.raise_for_status()
    return norm_gdacs(r.json())


_PROVIDERS = {
    "gdelt-doc": _fetch_gdelt_doc,
    "gdelt-geo": _fetch_gdelt_geo,
    "eonet": _fetch_eonet,
    "gdacs": _fetch_gdacs,
}

PROVIDERS = tuple(_PROVIDERS)


async def _fetch_one(name: str, wh: int, bbox: str,
                     client: httpx.AsyncClient) -> tuple[ProviderStatus, list[NewsItem]]:
    lock = _LOCKS.setdefault(name, asyncio.Lock())
    async with lock:
        cur = _CACHE.get(name)
        if cur and cur.ok and (time.monotonic() - cur.at) < TTL_S:
            return ProviderStatus(
                name, True, False, _iso(datetime.now(timezone.utc)
                - timedelta(seconds=time.monotonic() - cur.at)),
                len(cur.items), cur.latency_ms), cur.items
        t0 = time.monotonic()
        try:
            items = await _PROVIDERS[name](client, wh, bbox)
            _CACHE[name] = _Cached(items=items, at=t0, ok=True,
                                   latency_ms=int((time.monotonic() - t0) * 1000))
            return ProviderStatus(name, True, False, _iso(datetime.now(timezone.utc)),
                                  len(items), _CACHE[name].latency_ms), items
        except Exception as exc:  # noqa: BLE001 — last-good honesty: stale, never a 500
            prev = _CACHE.get(name)
            if prev and prev.ok:
                prev.error = str(exc)[:200]
                return ProviderStatus(name, True, True, _iso(datetime.now(timezone.utc)
                                      - timedelta(seconds=time.monotonic() - prev.at)),
                                      len(prev.items), prev.latency_ms, prev.error), prev.items
            _CACHE[name] = _Cached(at=t0, ok=False, error=str(exc)[:200],
                                   latency_ms=int((time.monotonic() - t0) * 1000))
            return ProviderStatus(name, False, False, None, 0,
                                  _CACHE[name].latency_ms, _CACHE[name].error), []


async def fetch_all(window_hours: int = 24, bbox: str = "68,6,98,36",
                    client: httpx.AsyncClient | None = None):
    """-> (statuses, items). Inject `client` in tests (httpx.MockTransport)."""
    own = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": UA},
                                   follow_redirects=True)
    try:
        results = await asyncio.gather(*[_fetch_one(n, window_hours, bbox, client)
                                         for n in _PROVIDERS])
    finally:
        if own:
            await client.aclose()
    statuses = [r[0] for r in results]
    items: list[NewsItem] = []
    seen: set[str] = set()
    for _, its in results:
        for it in its:
            if it.id not in seen:
                seen.add(it.id)
                items.append(it)
    items.sort(key=lambda i: i.published_at or "", reverse=True)
    return statuses, items

