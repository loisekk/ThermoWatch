# Technical Context

## Technologies
| Layer | Tech |
|-------|------|
| Client | React 19, TypeScript 5.9, Vite 7, Tailwind CSS 4, Zustand 5, MUI 7 (+ icons, emotion), lucide-react, MapLibre GL 5, deck.gl 9, DuckDB-WASM 1.29, three 0.186, react-globe.gl 2.35, clsx |
| Client tests | Vitest 3.2 |
| API | Python, FastAPI ≥0.115, uvicorn, pydantic 2, pydantic-settings, scikit-learn ≥1.5, joblib, httpx (tests) |
| API tests | pytest ≥8.3 |
| Ingest | Bun, TypeScript 5.9, `@types/bun` |
| CI/CD | GitHub Actions (`ingest-cron.yml`), Docker / docker-compose, Render (API/WS), Vercel (client) |
| Optional ML | torch ≥2.4, torch-geometric ≥2.6, xgboost ≥2.1 (ST-GNN / XGBoost members; ensemble is the fallback) |

## Development Setup (Windows/powershell environment)
Three terminals (or `npm run install:all` at root):

```bash
# 1) FastAPI brain — port 8000
cd server/api
python -m venv .venv                     # already present (server/api/.venv)
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 2) Bun ingest worker — publishes detections → :8000
cd server/ingest && bun install && bun run dev

# 3) Client console — http://localhost:5173
cd client && npm install && npm run dev
```

Root convenience scripts (`package.json`): `dev:client`, `dev:api`, `dev:ingest`,
`install:all`, `train`, `test:api`, `test:client`, `test:claims`, `test`, `typecheck`.

## Verifying the Build (gates)
```bash
npm run test          # api pytest + client vitest + claim audit
npm run typecheck     # client tsc --noEmit + ingest bun typecheck
cd client && npm run build   # tsc --noEmit && vite build
```

## Environment Variables
| Variable | Default | Where |
|----------|---------|-------|
| `VITE_API_URL` | `http://localhost:8000` | client |
| `TW_CORS_ORIGINS` | `http://localhost:5173` | api |
| `TW_ORIGIN_REGEX` | `https://[a-z0-9.-]+\.vercel\.app\|http://localhost(:\d+)?\|http://127.0.0.1(:\d+)?` | api (CORS + WS parity) |
| `TW_INGEST_TOKEN` | `""` (optional shared secret for POST /ingest/events) | api + ingest |
| `TW_PERSISTENCE_DAY_THRESHOLD` | `5` | api (STA rule) |
| `TW_CELL_DEG` | `0.004` | api (~400 m cell proxy) |
| `TW_MAX_EVENTS` | `5000` | api rolling buffer |
| `TW_API_URL` | `http://localhost:8000` | ingest |
| `FIRMS_API_KEY` | `""` (sim feed otherwise) | ingest (also `VITE_FIRMS_API_KEY` alias) |
| `POLL_MS` | `900000` (15 min; compose uses 60000) | ingest |
| `SINGLE_SHOT` | off | ingest (cron mode = `1`) |
| `FIRMS_API_KEY` / `TW_API_URL` / `TW_INGEST_TOKEN` | — | GitHub Actions secrets (`ingest-cron.yml`) |

## Key Commands & Data Paths
- ML training: `cd server/api && .venv\Scripts\python -m app.ml.train --source synthetic --samples 4000`
- Trained artifacts: `server/api/app/ml/models/model_bundle.joblib` (gitignored, 30 MB),
  `model_multimodal.joblib`, `eval_report.json` (committed — Model Card source of truth).
- FIRMS self-test: `cd server/ingest && bun run firms:test` (needs `.env` with key).
- Ingest env template: `server/ingest/.env.example` → `.env`
  (`TW_API_URL=http://127.0.0.1:8000` — Bun resolves localhost to ::1, uvicorn binds IPv4).
- Client assets: `client/public/textures/earth-night.jpg`, `client/src/assets/world-110m.json`.
- Landing/dashboard split: `client/index.html` (landing) · `client/app.html` (React dashboard).
  Deep links: `/app.html?vp=3d&panel=k&lat=..&lon=..`.

## Deployment Notes
- **docker-compose** (`docker-compose.yml`): api:8000 (uvicorn, in-memory store), ingest
  (depends on api, `POLL_MS=60000`), client:5173 (dev server). Volumes mount `server/api`
  incl. `app/ml/models`.
- **Render** hosts the API/WS and only *receives* data; the Bun worker runs locally or on
  GH Actions cron. Build command on Render to serve the trained ensemble:
  `pip install -r requirements.txt && python -m app.ml.train --source synthetic --samples 4000`
  → API then reports `served_by: tw-ensemble-v1`.
- **Vercel** hosts the client; CORS uses regex allow-list so every preview/deployment URL works.
- **Healthz** (`/api/v1/healthz`) accepts HEAD for uptime-monitor probes and returns
  version + timestamp; the ingest-cron also uses it as the keep-warm ping.
- Server tests: `server/api/tests/` (test_api, test_event_store, test_heuristic,
  test_history_response, test_multimodal_features, test_pipeline). Client tests live beside
  sources in `__tests__/` folders (vitest). Dockerfiles exist for api/ingest/client.

## Known Constraints / Gotchas
- FIRMS rate limit ~100 req/h → `POLL_MS=900000` gives ~4 req/h; archive-edge calibration is
  limited to ~3 probe requests at boot.
- FIRMS latency 3–6 h → honest "near-real-time" language only.
- The dev box has broken WebGL frame presentation → canvas-default AUTO routing everywhere;
  GL engines are explicit opt-in (MAPLIBRE / GL toggles) with honest amber chips.
- Trained bundle is gitignored → any fresh deploy without a build-time train step falls back
  to `heuristic/v1` (still honest, labelled).
- Cross-sensor MODIS→VIIRS transfer untested (documented limitation on the Model Card).
- All data is in-memory on the API (rolling 5000-event buffer) — no database.
- `.venv`, node_modules committed-ignored; `server/api/app/ml/models/model_bundle.joblib`
  ignored but `eval_report.json` intentionally tracked.