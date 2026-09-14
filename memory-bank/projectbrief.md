# ThermoWatch — Project Brief

## Identity
- **Project name:** ThermoWatch
- **Competition:** Smart India Hackathon 2025 · Problem ID **SIH26162** (NTRO)
- **Repo:** https://github.com/loisekk/ThermoWatch.git (branch `main`)
- **One-liner:** Multi-class industrial fire classification + persistent thermal source intelligence.

## Core Mission
Detect and classify industrial fires and persistent thermal sources using satellite thermal
anomalies (NASA FIRMS), correlate them with OSM industrial facilities and land-cover context,
run a spatio-temporal ML classifier, and present everything in a 2D/3D GIS console with an
AI agent, history analytics, response recommendations and a model card.

## Monorepo Layout (each package manages its own deps)
| Package | Path | Stack | Role |
|---------|------|-------|------|
| `client`   | `client/`       | React 19 + Vite + Tailwind + Zustand + MapLibre + deck.gl + DuckDB-WASM + three.js + globe.gl | 2D/3D GIS console |
| `api`      | `server/api/`   | FastAPI + pydantic v2 + scikit-learn + joblib | feature engineering, ML inference, persistence, risk, WS, history, response |
| `ingest`   | `server/ingest/`| Bun + TypeScript | FIRMS poller / publisher (also Docker + GH-cron mode) |

## Key Functional Requirements
1. Poll NASA FIRMS (MODIS + VIIRS) for thermal detections over India and classify them into
   industrial fire sub-types (10-way: refinery, steel, gas_flare, cement, smelter,
   waste_incineration, power_plant, chemical, unknown_industrial, natural_fire), projected
   to a 4-class UI (industrial / persistent / wildfire / agricultural).
2. Track persistence per ~400 m cell using the FIRMS STA rule (≥ 5 detection-days).
3. Correlate detections with OSM industrial facilities (< 3 km haversine) for context.
4. Score risk = intensity × persistence × hazard (NBC 2016 hazard classes).
5. Stream live events through a WebSocket with a KB-derived event taxonomy.
6. Provide history (180-day window), response recommendations (fire stations/resources),
   a Model Card with real metrics, and a BYO-key AI agent.
7. Guarantee a rendered frame on any host: canvas-first rendering with capability probes,
   rAF shim, WebGL context-loss recovery (never a black viewport).

## Honesty Contract (judge-proof)
- Say **near-real-time** (FIRMS latency is 3–6 h), never bare "real-time".
- Persistence = ≥ 5 detection-days per 400 m cell (STA rule).
- Report **macro-F1 per class**, never bare "accuracy" or "100%".
- No "first-ever" / novelty claims. Automated gate: `scripts/claim_audit.py` (wired into
  `npm test`).
- Model Card must quote REAL numbers from `eval_report.json`, never placeholders.

## Success Criteria / Gates
- `npm run test` green (API pytest + client vitest + claims audit)
- `npm run typecheck` green (client `tsc --noEmit` + ingest `bun typecheck`)
- `cd client && npm run build` green
- Demo runbook in `docs/DEPLOYMENT.md` works on a clean machine.

## Out of Scope (documented Future Scope)
- Cesium 3D-Tiles, SAR-based detection, cross-sensor (MODIS→VIIRS) calibration, h3 res-9
  grid upgrade (current proxy: `cell_deg = 0.004`).