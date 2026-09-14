# Active Context

> Status as of 2026-09-15 · HEAD `main` = `a53b8d2` — T9 clarity pass + T10 GL pin ladder +
> T13 3D-for-any-hotspot, all gated (vitest 24 files / 108 tests · tsc 0 · pytest 44 ·
> claim_audit PASS 171). Working tree CLEAN. `origin/main` still at `5845fa0` (push owed).

## Current Focus
- **T9 cartographic clarity pass is APPLIED, GATED and COMMITTED (`ef5f7a6`)** — cased roads
  (casing + ×0.62 fill passes), roof caps ×1.18 + EdgesGeometry outlines, scatter-based
  canopy over REAL wood polygons, halo labels (facility/water/wood/landuse/roads, cap 12),
  scale bar + north arrow, hover provenance tooltip (`OSM way … (height source)`), OSM
  MESHES truth chip, carto palette in `cartography.ts` (pure, tested).
- **CRASH FIX (same commit):** every `mergeGeometries` site now guards empty arrays —
  three.js reads `geometries[0].index` first, so an empty road fill pass (all
  residential/service), degenerate patch rings, or empty shore list threw
  `Cannot read properties of undefined (reading 'index')` and killed the dialog.
  The long-red `buildOsmScene: stats + dispose` test covers exactly that path.
- **T10 GL rescue ladder (`f5f2b68`)** — `glSelfCheck.ts` (pure `pixelVariance` +
  `resolveSceneRenderer`); canvas-first routing restored; one-shot frame-2 readPixels
  uniform-raster check; `webglcontextlost` reported; frozen-frame watchdog (two 1.5 s
  checks, no per-frame readPixels); `setClearColor(CARTO.ground)` bans white paint;
  local `SceneErrorBoundary` → CanvasScene in-dialog; pin ladder = one remount, second
  death = permanent honest chip `GL RASTER UNRELIABLE HERE (reason) — PINNED TO CANVAS2D`.
- **T13 3D-for-any-hotspot (`a53b8d2`)** — `useUIStore.openScene/closeScene`, shortcut
  `V` (opens the selected event's scene), dossier header `3D scene · V` action,
  deep link `app.html?…&scene=<eventId>` (dialog opens when the event exists).
- Continuous hardening of the FIRMS-live ingestion pipeline and deployment story
  (Render API + GH Actions `ingest-cron` every 15 min, Vercel client, CORS robustness).
- The dev machine has broken WebGL frame presentation → rendering resilience
  (canvas-first, rAF shim, self-tests, T10 pin ladder) is a first-class product concern.
- Demo-day readiness: docker-compose runbook + honest banners + Model Card with real metrics.

## Most Recent Changes (Session 23, uncommitted)
- **LIVE WIRE (server):** `services/news_wire.py` (GDELT DOC/GEO 2.0 · EONET · GDACS,
  TTL 300 s, single-flight, last-good stale flag) + `api/v1/news.py` feed/providers with
  server-side FIRMS correlation (≤75 km / ≤72 h). Router, tests added.
- **Detection buffer:** `services/detection_buffer.py` per-cell ring (500×400, LRU), hooked
  in `pipeline.enrich()` (covers live ingest + sim seed), `GET /events/{id}/detections`.
- **Client:** `features/news/` (types, client, correlate, channels — 6 verified YouTube IDs,
  wireBrief, NewsWirePanel), `store/useNewsStore.ts` (5-min poll, backoff, TV state),
  ResizeHandle + clamped persists panel sizes (RightDock/EventDrawer/FacilityDrawer),
  shortcuts `N`, deep-link `panel=n`, `tw_summarize_wire` agent tool.
- **Scene 2.0:** `sceneData.ts` (pure) + `threeBuilders.ts`; per-detection sprites + 2σ
  ellipse + plume + replay in ThreeScene; canvas parity dots/ellipse in CanvasScene;
  Scene3DViewer fetch + honest centroid-mode fallback chip.
- **T8 — live OSM context (Session 23.5):** Overpass proxy (`scene_context.py` +
  `/api/v1/scene/context`, POST form, 3-instance chain ×2 passes, 6 h cache,
  single-flight, 60 s/cell refresh guard); `osmScene.ts` (real footprints extruded +
  instanced trees + road ribbons + water/wood/landuse patches); mode chips
  OSM LIVE/SPARSE/unavailable→SCHEMATIC, anti-confusion `≈X m from OSM way…` callout,
  drawer SCENE CONTEXT PROVENANCE section; canvas simplified parity, shadows ≤400 bld.
  Live-verified at Jamshedpur.
- **Gates/docs:** claim_audit patterns (near-lookbehind-guarded), `check_news_channels.mjs`
  (exit 0), README/USER_GUIDE/ARCHITECTURE updated.

## Working Tree State (IMPORTANT)
- **CLEAN as of commit `1d61b2d`** (2026-09-14 ~23:16 IST). The whole Session 20→23.5 stack
  plus prior environment drift went into ONE commit with the T8 message, because router.py
  imports the then-untracked news/scene modules — the tree was only coherent as a unit.

## Active Decisions & Considerations
- News wire is **poll-based** (5-min client, 300 s server TTL): the WS taxonomy
  (KB §21.6) stays verbatim — no new WS frame types.
- Detection buffer keys on the **~400 m cell**, not the event id: in this codebase every
  FIRMS detection IS an event, so the honest per-detection scene for an event = the raw
  VIIRS detections recorded in its cell. `/events/{id}/detections` resolves event → cell.
- Replay scrubber feeds the Three render loop through a ref (no context teardown);
  plume is labelled illustrative, ellipse is a 2σ covariance (measured), never a guess.
- All six broadcast-strip channel ids verified 2026-09-14 by `check_news_channels.mjs`.

## Next Steps (open items)
1. **S24 remainder (pack issued, not yet built):** T11 real ground (GIBS z13 crop →
   ground CanvasTexture + AWS terrarium z12 displacement, honest FLAT/unavailable
   chips, lazy after first presented frame, shared tile cache) · T12 place names
   (`scripts/build_places.mjs` → `places-50m.json`, `lib/geo/places.ts` ladders,
   2D/3D labels, LOCAL NAMES z≥7 layer, `ViewLocationChip` breadcrumb) · T14 detail
   controls (`tw.sceneOpts.v1`, DETAIL FULL/FAST, per-feature toggle chips — depends
   on T11 for imagery/terrain toggles) · perf folds (static matrices, sprite pool,
   replay visibility flips). Hover-tooltip `3D` chip in globe/map was consciously
   SKIPPED: cursor-following tooltips cannot host clickable actions.
2. Push 5 commits to origin (`origin/main` at `5845fa0`) → CORS curl + Vercel hash
   check → Vercel redeploy **no-cache**.
3. Rehearse full demo (≤5 min script + scene beat + forced-GL pin moment) by
   **Sep 17**, then submit (buffer Sep 18–19).
4. Post-SIH queue: ReliefWeb provider, Guardian key, source-tier badges, LLM wire
   brief, globe-side wire pins.