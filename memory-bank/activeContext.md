# Active Context

> Status as of 2026-09-14 (late) · HEAD `main` = `1d61b2d` — "feat(scene): live OSM context —
> real buildings/trees/roads with honest degradation". The FULL working tree (Session 23 +
> 23.5 + prior drift) was committed in this single commit; working tree is now CLEAN.

## Current Focus
- **T8 (Session 23.5) is APPLIED, GATED, COMMITTED and LIVE-REHEARSED.** All gates re-verified
  post-commit: pytest 42 · vitest 22 files / 89 tests · tsc 0 errors · claim_audit PASS
  (169 files) · `npm run build` warning-free (1 m 1 s).
- Live rehearsal via Playwright (local API :8000 + Vite dev server): incident dossier
  TW-00008 → SCENE CONTEXT PROVENANCE fetched live from Overpass (516 buildings, 400 roads,
  height provenance 0 % tagged / 100 % estimated); 3D scene chip
  `CONTEXT: OSM LIVE · 516 bld / 2 trees · snapshot 1 m ago` + `refresh context` button;
  footer carries `context = osm buildings/vegetation/roads (live snapshot · © osm odbl)`.
- On THIS dev box the scene auto-routes to **canvas2d** even with "try GL" pressed — the
  GL gate is `capability?.rasterizes` (probe fails here, documented constraint). A genuine
  ThreeScene/WebGL frame can only be captured on a healthy host; canvas host + GL-attempt
  screenshots captured in rehearsal.
- Continuous hardening of the FIRMS-live ingestion pipeline and deployment story
  (Render API + GH Actions `ingest-cron` every 15 min, Vercel client, CORS robustness).
- The dev machine has broken WebGL frame presentation → rendering resilience
  (canvas-first, rAF shim, self-tests) is a first-class product concern, not a nice-to-have.
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
1. Push `1d61b2d` to origin when ready (`origin/main` still at `5845fa0`).
2. Re-verify CORS curl + Vercel deployment hash == repo HEAD before demo (§6-1/6-2) —
   still owed; Vercel rebuilds from the pushed commit.
3. Rehearse full demo (≤5 min script + 45 s scene beat) by **Sep 17**, then submit.
4. Post-SIH queue (T8+): ReliefWeb provider, Guardian key, source-tier badges, LLM wire
   brief, globe-side wire pins.