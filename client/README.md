# ThermoWatch Console (client) — SIH26162 · NTRO
Vite 7 + React 19 + TypeScript (strict) mission console: 2D MapLibre / 3D globe dual viewport,
MUI theme layer, FastAPI WS live feed with offline sim fallback, BYO-key AI agent, manual ML run panel.

See the **root README** for the full monorepo run instructions (API + ingest + client).

```bash
npm install
npm run dev          # http://localhost:5173
npm run typecheck    # strict TS gate
npm run build        # typecheck + production bundle
```

Optional env (see `.env.example`): `VITE_API_URL` — FastAPI base (default `http://localhost:8000`).
When the API is unreachable the console automatically serves the deterministic local sim feed.

## Shortcuts
`1`/`2` viewport · `space` hold feed · `o p a f g m` workspaces · `esc` close dossier

## Honesty notes (judge-proof)
FIRMS latency is 3–6 h → UI says **near-real-time**, never "real-time". Persistence rule (≥5 d / 400 m cell) mirrors FIRMS STA. Classification is multi-class (IND/PRS/WLD/AGR), not binary.

