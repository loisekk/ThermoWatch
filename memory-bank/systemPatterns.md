# System Architecture & Patterns

## High-Level Data Flow
```
NASA FIRMS (MODIS + VIIRS, 3–6 h)                 OSM industrial facilities (static seed, client+server)
        │ FIRMS CSV (area query, bbox)                     │
        ▼                                                  │
Bun ingest worker (server/ingest/src)                      │
  poll · publish · retry-queue                             │
        │ POST /api/v1/ingest/events                       │
        ▼                                                  ▼
FastAPI backend (server/api)
  · feature engineering (FRP, brightness, diurnal, persist-days)
  · OSM correlation (haversine < 3 km)
  · ML classification (ensemble 10-way → 4-class UI)
  · persistence (400 m cell, STA ≥ 5 detection-days)
  · risk scoring (intensity × persistence × hazard)
  · WS taxonomy (fire:new / fire:classified / persistence:detected /
                alert:triggered / system:status 30 s heartbeat)
  · history (180-day) + response recommendations
        │ GET /api/v1/events · WS /api/v1/ws/live
        ▼
React console (Vite)
  · 2D MapLibre / Canvas2D FallbackWorldMap
  · 3D react-globe.gl / CanvasGlobe fallback
  · incident scene (three.js | isometric canvas2d)
  · AI agent (BYO key, tool-calling)
  · Advanced Mode (deck.gl + DuckDB-WASM), history, model card, response plans
```

## Backend Architecture (server/api/app)
- `main.py` — FastAPI app, CORS (regex origin allow-list + exact list), lifespan seeds event
  store, warm-loads the ML model, starts WS heartbeat loop.
- `core/config.py` — pydantic-settings, env prefix `TW_`. Key defaults:
  `TW_CORS_ORIGINS=http://localhost:5173`, `TW_INGEST_TOKEN=""`,
  `TW_PERSISTENCE_DAY_THRESHOLD=5`, `TW_CELL_DEG=0.004` (~400 m), `TW_MAX_EVENTS=5000`;
  `TW_ORIGIN_REGEX` covers all `*.vercel.app` + localhost.
- `api/v1/` — routers: `events`, `ingest`, `predict`, `ml_inference`, `model`, `history`,
  `response`, `live` (WS). All prefixed `/api/v1`.
- `schemas/fire.py` — pydantic models for events, ingest POST body, predict request/response.
- `services/` — `pipeline.py` (enrich: features → facility correlation → classify → risk →
  STA persistence → broadcast), `event_store.py` (in-memory rolling buffer + seed),
  `geo.py`, `heuristic.py`, `landcover.py`, `population.py`, `response.py`, `simseed.py`,
  `weather.py`.
- `ml/` — `train.py` (ensemble training → `ml/models/`), `inference.py` (precedence:
  trained bundle → ST-GNN → heuristic), `ensemble.py`, `classifier.py`,
  `feature_engineering.py`, `features.py`, `model_loader.py`, `stgnn.py`, `dataset.py`,
  `dataset_multimodal.py`, `train_multimodal.py`.

### ML Contract
- **Train:** `python -m app.ml.train --source synthetic --samples 4000` (or
  `--archive firms_india.csv`). Outputs `model_bundle.joblib` + `eval_report.json`.
- **Infer:** precedence trained bundle → ST-GNN (if torch/torch-geometric installed) →
  heuristic ensemble. `served_by` provenance always reported.
- **UI projection:** 10-way posterior → 4 classes (industrial / persistent / wildfire /
  agricultural). `client/src/services/classification/classifier.ts`.
- **Current real metrics** (eval_report.json, trained 2026-09-08): macro-F1 0.8774 on a
  3995-sample synthetic stratified split. Per-class F1 e.g. gas_flare 1.0, refinery 0.9103.
  Model bundle is **gitignored** (30 MB); `eval_report.json` IS committed so the Model Card
  always shows real numbers.

## Ingest Worker (server/ingest/src)
- `config.ts` — `TW_API_URL` (default http://localhost:8000), `FIRMS_API_KEY`, `POLL_MS`
  (default 900 000), `TW_INGEST_TOKEN`, `SINGLE_SHOT`, `bbox = 68,6,98,36` (India).
- `firmsClient.ts` — FIRMS area endpoint `{KEY}/{SOURCE}/{bbox}/{days_back 1..5}/{YYYY-MM-DD}`;
  boot self-calibrates the archive edge (~3 probe requests).
- `publisher.ts` — posts batches to `POST /api/v1/ingest/events` with retry-queue.
- `simulator.ts` — deterministic sim feed when no `FIRMS_API_KEY`.
- Modes: local `bun run dev` loop, `SINGLE_SHOT=1` for the GitHub Actions cron
  (`ingest-cron.yml`, every 15 min, doubles as keep-warm ping), or Docker compose.

## Client Architecture (client/src)
- `app/` — `providers.tsx`; entry `App.tsx`, `main.tsx`.
- `store/` — Zustand stores: `useFireStore` (events/detections), `useUIStore` (viewport,
  panels, shortcuts), `useAnalyticsStore` (advanced-mode analytics), `useMapDiagStore`,
  agent store in `features/agent/agentStore.ts`.
- `components/` — layout (AppShell, SideRail, TopBar, StatusTicker) · panels (AlertFeed,
  ClassBreakdown, FacilityTable, KpiStrip, LayerPanel, PersistenceBoard, RightDock,
  TimelinePanel) · views (Map2DView, Globe3DView, ViewStage) · detail (EventDrawer,
  Scene3DViewer) · ui (Badge, Panel, Segmented, Donut, Sparkline) · system (ErrorBoundary).
- `features/` — agent (chat, orchestrator, tools), analytics (AdvancedModeToggle,
  AnalyticsPanel, DeckGLLayers, DuckDBEngine, TimeSlider, deckData), globe3d (CanvasGlobe),
  map2d (FallbackWorldMap, ViewportSelfTest, WebGLProbe), scene (ThreeScene, CanvasScene),
  ml (ManualPredictionPanel, predictPayload), model (ModelCardPanel), response (ResponsePlan),
  history, facility, context.
- `services/` — api (client, liveSocket, mappers), classification, firms (legacy client,
  types), osm (facilitySeed), persistence (tracker), risk (scorer), simulation (simulator).
- `lib/` — geo (countryIndex, featureCollection, graticule, sphereMap, tiles, viewClamp,
  distance), random (mulberry), runtime (rafShim), utils (cn, format).
- `hooks/` — useBackendFeed, useSimulationFeed, useDeepLink, useKeyboardShortcuts.
- `config/` — basemap, constants, imagery, regulatory, worldStyle. `types/domain.ts` central.

### Client rendering resilience (core pattern — Sessions 10–17, 20)
1. **rAF shim** (`lib/runtime/rafShim.ts`): boot probes `requestAnimationFrame` ~400 ms;
   if zero frames, an `setInterval(16 ms)` driver replaces it BEFORE React mounts.
2. **Canvas-first routing** (`features/map2d/WebGLProbe.ts` + `probeRenderer()`): verify
   rasterization via `readPixels` (context creation alone lies on GPU-blacklisted hosts);
   canvas engines paint immediately, GL upgrades only when proven.
3. **WebGL context-loss recovery**: single probe context released via `WEBGL_lose_context`;
   Globe3DView auto-remounts on lost/restored; frozen-frame polling falls back to the canvas
   orb + diag chip (`window.__twgl`).
4. **Canvas fallbacks guaranteed anywhere**: FallbackWorldMap (Canvas2D equirect), CanvasGlobe
   (orthographic canvas globe with inverse-sphere night-lights), CanvasScene (isometric
   incident scene). No GL, no rAF, no CDN required.
5. **2D basemap**: bundled Natural Earth 110m vector (`assets/world-110m.json`) + procedural
   15° graticule + optional night-lights / GIBS imagery (NASA GIBS XYZ, Mercator-corrected
   for canvas: 12 bands per tile in `lib/geo/tiles.ts`). No tile-server dependency.
6. **Advanced Mode**: deck.gl HexagonLayer (1 km hex, elevation = FRP), facility extrusions
   (height by NBC 2016 hazard), spread rings (6/12/24 h), DuckDB-WASM client-side spatial SQL
   (jsDelivr, lazy-loaded).

### AI Agent (client/src/features/agent)
- BYO OpenAI/Anthropic key — stored in browser localStorage, never auto-written to server.
- Tool-calling: runs the ML model, queries events, fetches KPIs.
- Self-explanatory backend-connectivity diagnostics + 12 s cold-start timeout.

## WebSocket Taxonomy (KB §21.6)
`fire:new` (ember) · `fire:classified` (green) · `persistence:detected` (amber) ·
`alert:triggered` (red) · `system:status` (steel, 30 s heartbeat).
Client ticker color-tags each type.

## Claim-Safety Gate
`scripts/claim_audit.py` fails the build on forbidden claims: bare `real-time` (unless
near-/negated), `novel`, `first-of-its-kind`, `prevents`, `100% accuracy`, `guarantee`.
Session 23 additions: `real-time news/wire/stream` must be `near-real-time` (near-lookbehind
guarded), `news confirms/verifies/proves` is banned (corroborates only), and plumes are
never "a dispersion model" (illustrative only).
Whitelisted honest vocabulary: *near-real-time*, *integrated approach*, *supports*,
concrete F1/P/R numbers from the eval report. Wired into root `npm test` as `test:claims`.