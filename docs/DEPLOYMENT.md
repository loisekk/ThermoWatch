# ThermoWatch — Deployment

Three services: `api` (FastAPI), `ingest` (Bun FIRMS worker), `client` (Vite console).

## Option A — Docker Compose (recommended for the demo box)

```bash
# one-time: live FIRMS key (optional; sim seed works without it)
cp server/ingest/.env.example server/ingest/.env   # set FIRMS_API_KEY=…

docker-compose up --build
# client http://localhost:5173 · api http://localhost:8000/docs
```

Services, ports and env vars:

| Service | Port | Env | Notes |
|---------|------|-----|-------|
| `api` | 8000 | `TW_CORS_ORIGINS` | uvicorn, in-memory event store (seed on boot) |
| `ingest` | - | `TW_API_URL`, `FIRMS_API_KEY`, `POLL_MS` | publishes FIRMS batches |
| `client` | 5173 | `VITE_API_URL` | dev server; API base defaults to `http://localhost:8000` |

## Option B — bare metal

```bash
# 1) API
cd server/api
python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 2) Ingest worker (optional)
cd server/ingest && bun install && bun run src/main.ts

# 3) Client
cd client && npm install && npm run dev   # http://localhost:5173
```

## Environment reference

| Variable | Default | Where |
|----------|---------|-------|
| `VITE_API_URL` | `http://localhost:8000` | client |
| `TW_CORS_ORIGINS` | `http://localhost:5173` | api |
| `TW_PERSISTENCE_DAY_THRESHOLD` | `5` | api (STA rule) |
| `TW_CELL_DEG` | `0.004` | api (~400 m cell) |
| `TW_MAX_EVENTS` | `5000` | api rolling buffer |
| `FIRMS_API_KEY` + `TW_API_URL` | - | ingest |
| `POLL_MS` | `60000` | ingest |

## ML model training (recommended before the demo)

```bash
cd server/api && .venv\Scripts\python -m app.ml.train --source synthetic --samples 4000
# writes ml/models/model_bundle.joblib + eval_report.json; restart the API.
# The Model Card panel reads eval_report.json — quote THOSE numbers, never placeholders.
```

## Verification & gates

```bash
npm run test          # api pytest + client vitest + claim audit (forbidden claims)
npm run typecheck     # client tsc --noEmit + ingest bun typecheck
cd client && npm run build
```

## Demo-day runbook

1. `docker-compose up --build` (or the bare-metal trio above).
2. Open `http://localhost:5173`, confirm console ticker shows WS tags and `T` self-test is green.
3. Click a fire dot -> dossier -> **View 3D scene** -> response plan renders.
4. History panel (`H`) for the 180-day window; Model Card (`K`) for real metrics.
5. If a viewport is blank: press `T` and read the verdict (canvas2d / webgl / raf / stage).