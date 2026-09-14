# Active Context

> Status as of 2026-09-14 · HEAD `main` = `5845fa0` (Session 23 pack applied on top of the dirty working tree; uncommitted).

## Current Focus
- Session 23 fully gated (**pytest 34 · vitest 83 · tsc · claims · build**) and **Session
  23.5 (live OSM scene context)** implemented and live-verified against the real Overpass
  API (Jamshedpur: 226 building footprints, 400 roads, 16 water), now at **pytest 42 ·
  vitest 89 · tsc clean · claims pass (169 files) · build warning-free**.
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
The working tree had **many uncommitted modifications before Session 23** (pre-existing
dev-environment drift across client/server/scripts/docs). Session 23 added the untracked
files above on top of that. **Do NOT assume the committed HEAD represents the working
code** — consider working-tree diffs before making changes.

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
1. Review/commit the large uncommitted working tree (or confirm it is just environment drift).
2. Re-verify CORS curl + Vercel deployment hash == repo HEAD before demo (§6-1/6-2).
3. Post-SIH queue (T8+): ReliefWeb appname, Guardian key, source-tier badges, LLM wire brief,
   globe-side wire pins.