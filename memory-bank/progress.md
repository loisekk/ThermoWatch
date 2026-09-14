# Progress

> Status as of 2026-09-14. Source of truth for what works, what's left, and how decisions evolved.

## What Works (feature-complete console)
### Session 23 — LIVE WIRE, detection buffer, Scene 2.0, resizable panels
- News wire: GDELT DOC/GEO 2.0 + NASA EONET + GDACS providers (zero-secret, TTL 300 s,
  single-flight, stale-last-good), `GET /news/feed` + `/news/providers`, server-side
  FIRMS correlation (≤75 km/≤72 h). Tests: cache, dedupe, stale-on-error, first-call fail.
- Detection buffer: per-cell ring (500×400 LRU) fed by `pipeline.enrich()` (live + sim
  seed), `GET /events/{id}/detections`. Tests: cap, days filter, LRU, endpoint 200/404.
- Client live wire panel (`N`): provider health chips, 6 verified YouTube broadcast strip
  (default off), rule-based brief, correlated-row fly-to, 5-min poll w/ backoff.
- Scene 2.0: pure `sceneData` (ENU/ellipse/FRP ramp/replay) + `threeBuilders` sprites
  (one per VIIRS detection), plume (illustrative), 2σ ellipse, replay scrubber (Three),
  canvas parity dots/ellipse, honest centroid-mode fallback chip.
- Resize: RightDock/EventDrawer/FacilityDrawer via `ResizeHandle`, clamped + persisted
  (`tw.panelSizes.v1`). Agent tool `tw_summarize_wire`. `check_news_channels.mjs` gate.
- Gates: pytest 34 · vitest 83 (21 files) · tsc pass · claims pass · build warning-free.

### Session 23.5 — the scene becomes the actual place (live OSM context)
- Server Overpass proxy `services/scene_context.py` + `GET /api/v1/scene/context`:
  POST form queries to `overpass-api.de` → `overpass.kumi.systems` →
  `overpass.private.coffee` (GET/UA 406-block on the lead instance; cycling two
  passes survives transient 429/504), 60 s query timeout, 45 s client timeout,
  6 h cache, single-flight per key, fresh=1 rate-guarded (60 s/cell → 429).
- Parsing: `height`/`building:levels` (tagged) vs kind defaults (estimated),
  roads as 2+ point polylines (3+ for rings), nearest-first caps
  600 bld / 1500 trees / 400 roads / 200 polys.
- **Live-verified 2026-09-14 at Jamshedpur (22.804, 86.203):**
  `osm-overpass · buildings 226 · roads 400 (capped) · wood 1 · landuse 5 · water 16`.
- Client `osmScene.ts`: merged per-kind ExtrudeGeometry footprints (+BufferGeometryUtils),
  instanced trees (cone/blob + trunk, ±20 % seeded jitter), merged road ribbons
  (per-class half-widths), flat water/wood/landuse patches, wood canopy scatter
  (illustrative, ≤120), canvas label sprite. Pure helpers unit-tested
  (enuUnits/closedCCW/signedArea/roadRibbon/nearestBuildingM), dispose() clears groups.
- ThreeScene: OSM group replaces the procedural box when live; ACES + sRGB + fog +
  PCF shadows only when buildings ≤ 400. Scene3DViewer fetches on open (abortable,
  refresh-keyed): chips `OSM LIVE / OSM SPARSE (<3 bld) / SCHEMATIC (unreachable)`;
  `REFRESH CONTEXT` button; ant-confusion callout `≈X m from OSM way N…(kind)` for the
  top-FRP hotspot. CanvasScene parity: footprint top faces (≤80), tree dots (≤300),
  road strokes, patch fills. EventDrawer SCENE CONTEXT PROVENANCE section (counts,
  height split, nearest-building line, `OSM is community-mapped` honesty note).
- Gate status: pytest 42 · vitest 89 (21 files) · tsc clean · claims pass (169 files) ·
  build warning-free.

### Ingestion & data
- Bun ingest worker: FIRMS area-query polling (bbox 68,6,98,36 India), archive-edge
  calibration, retry-queue publisher, deterministic sim feed fallback, `SINGLE_SHOT` cron
  mode, `bun run firms:test` self-test.
- GitHub Actions `ingest-cron.yml` every 15 min (pulls → posts → keep-warm ping), seeded by
  secrets (FIRMS_API_KEY, TW_API_URL, TW_INGEST_TOKEN).
- FastAPI: POST /api/v1/ingest/events (optional ingest token), in-memory event store
  (5000-event rolling buffer) with `seed_if_empty`, GET /api/v1/events, WS /api/v1/ws/live.
- Healthz endpoint (HEAD + GET) returning version + timestamp for uptime monitors.

### ML / intelligence
- Ensemble training (RF + HistGB over 10 classes, probability-averaged) via
  `python -m app.ml.train --source synthetic --samples 4000` (or `--archive`); artifacts →
  `ml/models/model_bundle.joblib` + committed `eval_report.json`.
- Inference precedence: trained bundle → ST-GNN → heuristic ensemble, with `served_by`
  provenance. 10-way → 4-class UI projection.
- Real committed metrics: macro-F1 0.8774 (synthetic 3995 samples, stratified split).
- Feature engineering (FRP, brightness, diurnal, persist-days), OSM correlation (< 3 km),
  STA persistence (≥ 5 detection-days / ~400 m cell), risk scoring
  (intensity × persistence × hazard), multimodal training path (`train_multimodal.py`).
- POST /api/v1/predict (manual model run, full feature contract) + ml_inference route,
  model card route (`/api/v1/model/card`), history (`/api/v1/stats/history`, 180-day),
  response recommendations (`/api/v1/response/recommend`).

### Client console
- Landing (`index.html` → `/`) + React dashboard (`app.html`), deep-linkable
  (`?vp=3d&panel=k&lat=..&lon=..`), backend-probe banners (BACKEND LIVE / SIMULATED).
- 2D viewport: MapLibre (Mercator) OR Canvas2D FallbackWorldMap (Natural Earth 110m vector,
  graticule, night-lights, GIBS imagery), auto/canvas/maplibre selection + `T` self-test.
- 3D viewport: react-globe.gl orb OR CanvasGlobe (orthographic canvas fallback); starfield,
  hex-column facility extrusions; context-loss recovery.
- Incident scene: ThreeScene (GL) or CanvasScene (isometric) — always renders; dossiers with
  ensemble scores, risk drivers, context hypotheses, response plan, facility dossier.
- Live ticker with WS taxonomy color tags; keyboard shortcuts; pause/resume.
- AI Agent (BYO key, tool-calling: model run, event queries, KPIs) with connectivity
  diagnostics + 12 s cold-start timeout.
- Advanced Mode (2D): time slider/loop, deck.gl hex density (FRP elevation), facility
  extrusions (NBC hazard height), spread rings (6/12/24 h), DuckDB-WASM spatial SQL.
- History panel, Model Card panel (real metrics), Manual Model Run with scenario presets,
  persistence board, alerts feed, KPI strip.
- rAF shim + canvas-first routing + WebGL probe hygiene (probe context reuse + release via
  `WEBGL_lose_context`, frozen-frame polling, auto-remount).

### Quality gates
- `scripts/claim_audit.py` (forbidden claims) wired into `npm test`.
- API pytest suite (6 files), client vitest (colocated `__tests__`).
- Docs: ARCHITECTURE.md, DEPLOYMENT.md (incl. demo runbook), USER_GUIDE.md.

## What's Left / Known Gaps
- Working tree contains many uncommitted changes (see activeContext) — needs review/commit.
- MODIS→VIIRS cross-sensor transfer: untested, disclosed on Model Card.
- Live FIRMS archive-based training refinement: stated next step (currently synthetic).
- ST-GNN/XGBoost members optional (torch/torch-geometric not in default requirements).
- h3 res-9 grid is the documented upgrade path for the ~400 m cell proxy.
- No persistent database (in-memory only); persistence of history across restarts not built.
- Cesium 3D-Tiles documented as future scope.
- SAR-based detection and multi-modal (optical) fusion exist as `dataset_multimodal`/
  `train_multimodal` paths but are not the headline pipeline.

## Evolution of Key Decisions
1. **FIRMS over direct NASA sources** — FIRMS area endpoint is the ONLY key-gated pull
   mechanism; MODIS+VIIRS fused by FIRMS; bbox for India (no country-code endpoint).
2. **Ensemble (RF+HistGB) over deep learning as default** — deterministic, trainable in
   seconds on synthetic data, no heavy deps; ST-GNN designed as a swappable future member
   behind the same output contract.
3. **Canvas-first rendering (Sessions 10–17, 20)** — every GL engine proved unreliable on
   some judge/dev hosts (dead rAF or broken rasterization); canvas engines are the default
   AUTO path and GL is explicit opt-in; honesty chips when GL is forced.
4. **Regex origin allow-list for CORS/WS** — exact-match lists broke whenever Vercel rotated
   a preview URL; regex covers prod + all deployments + localhost.
5. **Bun worker as the only puller** — Render only receives; cron keeps the API warm and the
   feed fresh; local sim feed keeps the console demoable with zero credentials.
6. **eval_report.json committed, bundle gitignored** — Model Card stays truthful everywhere;
   Render's build command retrains when the bundle isn't there.

## Session Log (README narrative)
Session 7 Advanced Analytics · 8 world-grade 2D viewport · 9 renderer truth + incident
reasoning · 10–12 renderer-independent orb + scene + rAF shim · 13 WS taxonomy, history,
response engine · 14 ship sprint (claims gate, docs, Docker) · 15 canvas-default routing ·
16 imagery/screen-lock/facility dossier · 17 WebGL context-loss recovery · 20 Mercator-correct
GIBS on canvas. **23 LIVE WIRE (GDELT/EONET/GDACS + TV strip + brief), per-detection Scene
2.0 (sprites + ellipse + plume + replay), resizable dock/drawers.** Later live-FIRMS +
deployment sprint (see git log).