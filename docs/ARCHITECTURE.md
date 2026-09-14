# ThermoWatch — Architecture

SIH26162 · multi-class industrial fire classification & persistent thermal source intelligence

## System overview

```
┌───────────────────────────────┐        ┌───────────────────────────────┐
│       NASA FIRMS API          │        │  OSM industrial facilities    │
│  (MODIS + VIIRS, 3-6 h)       │        │  (static seed, client+server) │
└──────────────┬────────────────┘        └───────────────┬───────────────┘
               │ FIRMS CSV (area query)                  │
               ▼                                         │
┌───────────────────────────────┐                        │
│  Bun ingest worker            │                        │
│  server/ingest/src            │                        │
│  poll · publish · retry-queue │                        │
└──────────────┬────────────────┘                        │
               │ POST /api/v1/ingest/events              │
               ▼                                         ▼
┌───────────────────────────────────────────────────────────────────┐
│  FastAPI backend (server/api)                                       │
│  · feature engineering   (FRP, brightness, diurnal, persist-days)   │
│  · OSM correlation       (haversine < 3 km)                         │
│  · ML classification     (skyline ensemble 10-way -> 4-class UI)    │
│  · persistence           (400 m cell, STA >= 5 detection-days)      │
│  · risk scoring          (intensity x persistence x hazard)         │
│  · WS taxonomy           fire:new / fire:classified /               │
│                           persistence:detected / alert:triggered /   │
│                           system:status (30 s heartbeat)             │
│  · history + response    /stats/history · /response/recommend        │
└──────────────┬──────────────────────────────────────────────────────┘
               │ GET /api/v1/events · WS /api/v1/ws/live
               ▼
┌───────────────────────────────────────────────────────────────────┐
│  React console (Vite)                                              │
│  · 2D MapLibre / 3D globe.gl, canvas fallbacks, renderer self-test │
│  · incident scene (three.js | canvas2d)                            │
│  · AI agent (BYO key, tool-calling)                                │
│  · history, model card, response plans, alert board                │
└───────────────────────────────────────────────────────────────────┘
```

## Data flow

1. **Ingestion** — Bun polls FIRMS (rate-limit aware), posts a batch to FastAPI.
   With no key configured the API seeds a deterministic 14-day history; the client
   falls back to a local sim feed when the API is offline.
2. **Classification** — `pipeline.enrich` builds features, correlates the nearest OSM
   facility, runs the classifier, scores risk, updates STA persistence, stores + broadcasts.
3. **Visualization** — the WS frames drive the Zustand store; the ticker color-tags each
   taxonomy type; new events render across map, globe and analytics layers.
4. **Analytics** — Advanced Mode loads the event buffer into DuckDB-WASM for client-side
   spatial queries (hex density, extrusion, spread forecast).

## ML pipeline

**Train** (`server/api/app/ml/train.py`)
```
python -m app.ml.train --source synthetic --samples 4000
  -> ml/models/model_bundle.joblib + eval_report.json
```
- RF + HistGB probability-averaged ensemble over 10 classes.
- Output contract locked for a future ST-GNN/XGBoost member swap.

**Infer** (`app/ml/inference.py`)
- Precedence: trained bundle -> ST-GNN -> heuristic ensemble.
- UI projection: 10-way posterior -> 4 classes (industrial/persistent/wildfire/agricultural).
- Provenance always reports which stage served the prediction.

## Renderer resilience

Sessions 10-12 rendered every GL engine unusable on some hosts (embedded/remote-capture
webviews with a dead `requestAnimationFrame`). The console therefore:

1. Probes rAF at boot (`lib/runtime/rafShim.ts`); dead rAF is replaced by a
   `setInterval(16 ms)` driver **before React mounts** — MapLibre / three.js / globe.gl
   pick it up transparently and start presenting frames.
2. Routes renderers **canvas-first** (`probeRenderer()` capability), upgrading to GL only
   when WebGL rasterization *and* a live frame loop are proven.
3. The incident scene and 3D orb each ship a canvas fallback that needs no GL, no rAF,
   no CDN — a rendered frame is guaranteed on any host.

## Repo layout

```
client/          React 19 + Vite + Tailwind + Zustand console
server/api       FastAPI: ingestion, ML, persistence, WS, history, response
server/ingest    Bun FIRMS worker
scripts/         claim-audit grep gate (wired into npm test)
docs/            this guide set
```

## Claim-safety (automated)

`python scripts/claim_audit.py` fails the build on forbidden claims: bare `real-time`
(unless near-/negated), `novel`, `first-of-its-kind`, `prevents`, `100% accuracy`,
`guarantee`. The app's honest vocabulary: *near-real-time*, *integrated approach*,
*supports*, and concrete F1/P/R numbers from the eval report.

## Session 23 — LIVE WIRE, per-detection scene, resizable panels

### News wire (`server/api/app/services/news_wire.py`)
- **Providers (zero-secret, polled by the API):** GDELT DOC 2.0 (`article-country`),
  GDELT GEO 2.0 (`geo-mention`), NASA EONET v3 (`event`), GDACS EC-JRC/UN (`event`).
- **Cache & failure contract:** per-provider TTL 300 s, single-flight via asyncio locks,
  last-good-on-error with a visible `stale` flag. A provider outage is a badge and a
  stale list — never a 500, never a blank panel. First-call failure reports `ok=false`.
- **Honesty:** items are UNVERIFIED open-source reporting on a *near-real-time wire*
  (provider latency 15 min–6 h); corroboration is distance/time signal, not confirmation.
- **Endpoints:** `GET /api/v1/news/feed` (window/bbox/limit) and `GET /api/v1/news/providers`.
  Each item with coordinates is server-correlated to recent FIRMS events
  (≤ 75 km, ≤ 72 h) → `nearby_event_ids`, `correlation_km`, `correlation_dt_h`.

### Detection buffer (`server/api/app/services/detection_buffer.py`)
- In-memory per-cell ring buffer keyed by the same ~400 m cell as the event store
  (500 detections/cell, 400 cells LRU). `pipeline.enrich()` records every classified
  detection, so the live ingest path and the sim seed share one hook.
- `GET /api/v1/events/{id}/detections?days=30` resolves the event's cell and returns its
  raw detections (lat/lon/frp/brightness/acq time/sat).

### Scene 2.0 (`client/src/features/scene/`)
- `sceneData.ts` pure math (ENU metres, 2σ cluster ellipse, FRP radius, brightness ramp,
  replay window) — unit-tested with zero renderer imports.
- `threeBuilders.ts` additive-sprite hotspot field (one sprite per VIIRS 375 m detection),
  ellipse line, illustrative plume (labelled not a dispersion model). All builders return
  `dispose()` for WebGL context-loss remounts.
- `CanvasScene` draws the same dots + ellipse in isometric parity (plume/replay off, labelled).
- `Scene3DViewer` fetches the detections on open; without a buffer it falls back to the
  centroid fire core with an honest `per-detection unavailable — centroid mode` chip.
  Replay scrubber filters sprites by acquisition time (`acq_epoch_ms <= t`).

### Resizable surfaces
- `useUIStore` gains `panelSizes` clamped by `PANEL_CLAMP` ([min, max, default]), persisted
  to `localStorage tw.panelSizes.v1`. `ResizeHandle` (drag / arrow keys / double-click
  reset) is mounted on RightDock, EventDrawer and FacilityDrawer.
- Shortcut `N` + deep link `panel=n` open the LIVE WIRE panel; the store polls every 5 min
  (hidden-tab pause, exponential backoff to 15 min on errors).

### Scene context — live OSM surroundings (`services/scene_context.py`, T8)
- **Doctrine:** "real" = fetched from the world, never invented. Sparse OSM renders
  sparse; unreachable OSM renders the labelled SCHEMATIC fallback. No infill, ever.
- **Fetch:** Overpass `around` query (buildings, `natural=tree`, wood/forest, landuse,
  highway classes, water) — instance fallback `overpass-api.de` → `overpass.kumi.systems`,
  26 s timeout, cache TTL 6 h keyed on (lat, lon, radius), single-flight per key,
  total failure → `source: "unavailable"` (HTTP 200, honest).
- **Caps (nearest-first):** 600 buildings · 1500 trees · 400 roads · 200 polys/layer.
- **Heights:** `height` tag → `tag:height`; `building:levels` × 3.2 m → `tag:levels`;
  else kind default → `estimated` (provenance split surfaced in the drawer).
- **Fresh refresh:** `fresh=1` rate-guarded server-side (min 60 s/cell, else 429).
- **Endpoint:** `GET /api/v1/scene/context?lat&lon&radius_m&fresh` (router `api/v1/scene.py`).
- **Client:** `features/scene/osmScene.ts` — merged per-kind footprint prisms
  (ExtrudeGeometry + BufferGeometryUtils), instanced trees (canopy cone/blob + trunk,
  ±20 % seeded jitter), merged road ribbons (per-class half-widths), flat
  water/wood/landuse patches, wood canopy scatter (labelled illustrative), canvas-texture
  label sprite for the `≈X m from OSM way …` callout. ACES tone mapping, sRGB output,
  scene fog, PCF soft shadows only when buildings ≤ 400 (perf guard). Canvas parity:
  filled footprint top-faces (≤80), tree dots (≤300), road strokes, patch fills.

### Agent
- `tw_summarize_wire` tool returns the rule-based brief from the news store (no LLM);
  LLM-authored briefs are post-SIH scope.