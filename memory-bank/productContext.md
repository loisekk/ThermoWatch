# Product Context

## Why This Project Exists
SIH26162 (NTRO) asks for AI-based detection and classification of **industrial fires and
persistent thermal sources**. Industrial fires have severe safety, economic and regulatory
consequences; persistent heat plumes (refineries, gas flares, steel/cement plants) are a
daily real-world phenomenon largely hidden from plain satellite browsing. ThermoWatch turns
public FIRMS thermal anomaly data into an actionable, near-real-time intelligence console
for monitoring and response planning.

## Problems It Solves
1. **Raw FIRMS detections are unlabeled points** — users can't tell a refinery flare from a
   crop fire. ThermoWatch classifies them (10-way → 4-class UI).
2. **Persistence is the signal that matters** — a plant that burns for days is different from
   a one-off fire. STA persistence tracking per 400 m cell surfaces both.
3. **Context is everything** — a detection 2 km from a chemical plant is a different story
   than one in open farmland. OSM facility correlation + landcover + population add context.
4. **Machine learning must be honest** — the product ships a real Model Card with real
   macro-F1 and per-class P/R/F1 from a committed `eval_report.json`.
5. **Remote judging environments break WebGL** — every GL-only viewport was unusable on some
   hosts, so the console is canvas-first with probes, shims and self-tests.

## How It Should Work (User Experience)
- Landing page (`client/index.html` at `/`) probes the backend; every CTA deep-links into
  the console (`app.html?vp=3d&panel=k&lat=..&lon=..`).
- Console: 2D map / 3D globe viewports (keys `1`/`2`), live ticker color-tagging WS event
  types, click any fire dot → incident dossier (class scores, risk drivers, context
  hypotheses, response plan, 3D scene).
- Advanced Mode on the 2D viewport adds time slider, hex density, facility extrusion, spread
  rings and client-side DuckDB-WASM spatial SQL.
- History panel (`H`), AI Agent (`G`, BYO key stored locally), Manual Model Run (`M`),
  Model Card (`K`), Viewport Self-Test (`T`).
- With no backend running, the client falls back to a local deterministic sim feed so the
  console is always demo-able.

## User Goals
- Monitor industrial fire risk in near real time.
- Identify which facilities persist as thermal sources.
- Get class-probabilities, risk scores and response recommendations for any detection.
- Trust the numbers (per-class F1, honest provenance, disclosed limitations).

## Experience Principles
- **Never black.** Renderers self-probe; canvas engines paint first; GL takes over only when
  proven. Press `T` for a four-line verdict (canvas2d / webgl / raf / stage).
- **Honest labels.** `BACKEND LIVE` vs `SIMULATED` banners, `heuristic/v1` vs `tw-ensemble-v1`
  provenance, ambient chips when a viewport may stay black.
- **Instant storyboarding.** One-click dossiers, deep links, keyboard-first navigation.