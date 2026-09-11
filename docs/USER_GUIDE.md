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
| `X` `H` | Analytics · History |
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

### Live console ticker
Tags each WebSocket event with its taxonomy color: `fire:new` (ember), `fire:classified`
(green), `persistence:detected` (amber), `alert:triggered` (red), `system:status` (steel).

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
- ML is trained on **synthetic + OSM-proximity signatures**; live FIRMS archive refinement
  is the stated next step. `MODIS->VIIRS` cross-sensor transfer is untested and disclosed.

## Limitations (claim-safe)
- Near-real-time only (FIRMS 3-6 h latency).
- Proxy labels: synthetic/OSM-proximity, not on-site verified.
- Accuracy reported per class (F1 / P / R), never a bare "100%".
- Clouds block optical/thermal detection; SAR is future scope.