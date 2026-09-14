# ThermoWatch — User Guide

SIH26162 · AI-based detection & classification of industrial fires and persistent thermal sources · (NTRO)

## Quick start

```bash
git clone https://github.com/loisekk/ThermoPrism.git
npm run install:all          # client npm + api venv pip + ingest bun
docker-compose up            # api:8000 + ingest + client:5173
```

With no backend running the console starts on a **local deterministic sim feed** so you can
make a first pass immediately. Point the API at a real FIRMS key for the live story (see
[DEPLOYMENT.md](DEPLOYMENT.md)).

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1` / `2` | switch 2D / 3D viewport |
| `Space` | pause/resume live feed |
| `O` `P` `A` `F` | Overview · Persistence · Alerts · Facilities |
| `G` `M` `K` | AI Agent · Model Run · Model Card |
| `X` `H` `N` | Analytics · History · Live wire |
| `T` | viewport self-test (canvas2d / webgl / raf / stage) |
| `Esc` | close dossier |

## Features

### Map (2D) / Globe (3D) viewports
- Pan/zoom; drag the globe to orbit, wheel to zoom, click a dot for the dossier.
- Renderers auto-select: canvas engines paint first (never a black viewport); MapLibre /
  globe.gl / three.js take over once the capability probe proves WebGL rasterization **and**
  a live frame loop. Badges show the active engine (`VECTOR-110M`, `NIGHT-LIGHTS`, `CANVAS`).
- Press `T` for the four-line self-test verdict if a viewport ever looks wrong.

### Incident dossier (click any fire dot)
- Ensemble class scores, risk drivers, nearest OSM asset, context hypotheses.
- **Response recommendation**: nearest fire stations + ETA, resource table
  (vehicles/personnel/water), NBC evacuation radius, downwind staging point.
- **View 3D scene**: three.js where WebGL rasterizes, isometric canvas2d everywhere else.
- **Scene context (real world, not schematic)**: on scene-open the server pulls actual
  building footprints, trees, roads, water and land-use from OSM (Overpass, server-cached
  6 h, radius 1200 m). The context chip tells you exactly what you are looking at:
  - `CONTEXT: OSM LIVE · N bld / T trees · snapshot Xm ago` — real footprints.
  - `CONTEXT: OSM SPARSE · N bld — rendering what exists` — OSM is community-mapped;
    coverage varies by region, so sparse areas render sparse (no invented infill).
  - `CONTEXT: SCHEMATIC (OSM unreachable)` — legacy massing, clearly labelled.
- The drawer's **SCENE CONTEXT PROVENANCE** section shows the source, radius, snapshot
  time, per-layer counts, the height provenance split (tagged vs estimated) and the
  anti-confusion line: `top-FRP hotspot ≈X m from OSM way …` — the fire visibly sits
  next to a real mapped building. `REFRESH CONTEXT` force re-fetches (rate-guarded,
  min 60 s per cell server-side).

### Live console ticker
Tags each WebSocket event with its taxonomy color: `fire:new` (ember), `fire:classified`
(green), `persistence:detected` (amber), `alert:triggered` (red), `system:status` (steel).

### Live wire (key `N`)
- **Open-source corroboration panel** (GDELT DOC/GEO 2.0 · NASA EONET · GDACS), polled
  every 5 min. Provider chips show live per-provider health — a failure is a visible
  `stale`/`down` badge, never a blank panel.
- Items carry an honest grade glyph: `◆` event (EONET/GDACS), `◇` location mention (GDELT),
  `·` country-level article. Rows corroborated to a FIRMS event (< 75 km, < 72 h) show
  `↔ TW-xxxxx <km>` and fly you to the dossier when clicked.
- **Broadcast strip** (default OFF): lazy YouTube live embeds (Al Jazeera, DW, CNBC, Sky,
  WION, France 24). Streams are © their broadcasters; availability = broadcaster + network.
  The wire list below is the offline-safe surface. Channel IDs verified via
  `node scripts/check_news_channels.mjs`.
- **Wire brief** is a rule-based digest (history, no LLM) — clearly labelled.
- **Resize**: drag any panel edge, arrow keys nudge, double-click resets. Sizes persist.

### AI Agent
- BYO OpenAI/Anthropic key (stored locally in the browser only).
- Natural language + tool-calling: runs the ML model, queries events, fetches KPIs.

### Historical analysis (History panel, key `H`)
- 30-day stacked daily timeline by class, persistent-source leaderboard.
- Served by `/api/v1/stats/history` (server retention window).

### Model Card
- Real macro-F1 / per-class precision-recall from `eval_report.json`, confusion matrix,
  provenance (`served_by`), and an explicit limitations list — never placeholder numbers.

## Data sources & honesty rules
- **NASA FIRMS** (MODIS + VIIRS) — latency is 3-6 h, so we say **near-real-time**, never *real-time*.
- **OSM** industrial facilities — labels are proxies, not on-site verification.
- **News wire**: GDELT DOC/GEO 2.0 · NASA EONET · GDACS (EC-JRC/UN) — unverified open-source
  reporting; corroboration for analysts, never confirmation.
- ML is trained on **synthetic + OSM-proximity signatures**; live FIRMS archive refinement
  is the stated next step. `MODIS->VIIRS` cross-sensor transfer is untested and disclosed.

## Limitations (claim-safe)
- Near-real-time only (FIRMS 3-6 h latency).
- Proxy labels: synthetic/OSM-proximity, not on-site verified.
- Accuracy reported per class (F1 / P / R), never a bare "100%".
- Clouds block optical/thermal detection; SAR is future scope.