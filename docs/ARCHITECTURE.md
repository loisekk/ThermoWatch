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