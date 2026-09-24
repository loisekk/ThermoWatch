# Security Review — ThermoWatch V2

**Scope:** the `server/api` (FastAPI + SQLAlchemy 2.0 async + PostgreSQL/PostGIS),
`server/ingest` (Bun worker) and `client` (React 19 + Vite) trees, the
`docker-compose` dev stack, and the Git history about to be published.
**Date:** 2026-09-24 · **Tree:** pre-freeze working tree on `main` (base `8d1457e`).

This document records **findings and posture**, not a certification. ThermoWatch is a
hackathon prototype: several controls a production deployment needs are deliberately
absent and are listed under *Accepted limitations* below. **Nothing here should be read
as "the system is secure".**

## Method

Static review (pattern scans over tracked **and** untracked files), dependency
auditing (`pip-audit`, `npm audit`), manual reading of every request-serving path,
and the repository's own gates (`pytest`, `tsc --noEmit`, `vitest`, `vite build`,
`scripts/claim_audit.py`).

Secret/PII scans were run with `git grep --untracked` so that files *not yet
committed* were covered — the interesting leaks in this tree were all in
never-committed scratch output, which a history-only scanner would have missed.

---

## 1. Secrets and credentials

| Check | Result | Evidence |
|---|---|---|
| Credential-shaped assignments in source (`api_key=`, `secret=`, `password=`, …) | **PASS** | zero hits outside `.env.example` placeholders and the docker-compose dev password (below) |
| Known token shapes (`AKIA…`, `sk-…`, `ghp_…`, `xox[bap]-…`) | **PASS** | zero hits across tracked + untracked files |
| Provider keys held only in settings/env | **PASS** | `FIRMS_API_KEY`, `TW_CDSE_CLIENT_ID/SECRET`, `TW_DATABASE_URL`, `TW_WRITE_TOKEN` are read through `pydantic-settings` (`app/core/config.py`) or `process.env` (`server/ingest/src/config.ts`); no literal values exist in source |
| Ingest worker never logs the FIRMS key | **PASS** | `firmsClient.ts` builds the URL but throws only `FIRMS ${status}`; `firmsTest.ts` logs status/row counts, never the key or the URL |
| Structlog/`logging` never emits auth material | **PASS** | the only `authorization`/`client_secret` hit in `server/api/app` is the *declaration* of `cdse_client_secret`; no header or token is logged |
| No secrets baked into Dockerfiles | **PASS** | `git grep -niE "secret\|key\|password" -- "**/Dockerfile"` → zero hits |
| `.env` never tracked | **PASS** | `git ls-files` matches only `.env.example` templates |

### 1.1 FIXED — local machine paths in shareable report artefacts

`server/api/app/tools/reports/benchmark_report.{json,md}` and
`release_evidence.json` contained the developer's absolute path, e.g.
`"artifacts_dir": "C:\\Users\\<user>\\Desktop\\Thermo-watch\\server\\api\\app\\research\\artifacts"`
and a `.venv\Lib\site-packages\...` line inside a captured pytest warning.

Two-part fix:

* **Generator** (`app/tools/model_benchmark.py`) now writes the *checkout-relative*
  path via a new `display_path()` helper, so regenerating cannot re-leak the
  layout.
* **Ignore rule** — `server/api/app/tools/reports/` and
  `server/api/app/research/results/` are gitignored. Both are regenerable output
  (timestamped filenames, nothing imports them), and `research/artifacts/` +
  `research/datasets/` were already ignored on the same rationale.

### 1.2 FIXED — scratch output carrying the local username

`mypy_*.txt`, `ruff_*.txt`, `pytest_*.txt`, `*_now.txt`, `*_final.txt`,
`phase0_status.txt` and `server/api/_probe_*.py` embedded absolute user-profile
paths (`…\<user>\…`). All are now gitignored (kept on disk, never committed) and additionally
verified absent from the rewritten history before pushing.

### 1.3 Accepted — docker-compose development password

`POSTGRES_PASSWORD: thermowatch_dev` in `docker-compose.yml` is a **local dev
default** for a container bound to `localhost`. It is not a secret and is not
used by any hosted environment. Production must supply real credentials
(see the checklist). Ports 5432/8000/5173 are published for local development
only.


---

## 2. Dependencies

| Ecosystem | Command | Result |
|---|---|---|
| Python | `pip-audit -r requirements.lock.txt` | **PASS** — "No known vulnerabilities found" |
| Client (prod) | `npm audit --omit=dev` | **1 CRITICAL — deferred, see 2.2** |
| Ingest | `bun pm audit` unsupported by the pinned Bun build | **MANUAL REVIEW** — dependency set is `@types/bun` + the Bun standard library; no third-party runtime deps |

### 2.1 FIXED — the lockfile was unusable (two defects)

The audit could not even run because `requirements.lock.txt` was broken:

1. **Encoding:** UTF-16LE with a BOM. `pip install -r requirements.lock.txt`
   mis-parses a UTF-16 file (the null bytes corrupt the requirement names), so the
   pinned environment was not reproducible. Re-encoded to UTF-8 (no BOM).
2. **Corrupted package name:** the entry `pyteruct==9.1.1` — a mangled `pytest`
   (alphabetically the file lists `Pygments`, then it, then `pytest-asyncio`).
   Corrected to `pytest==9.1.1`, matching the installed `pytest 9.1.1`.

With both fixed the lockfile resolves cleanly and `pip-audit` reports zero
vulnerabilities.

### 2.2 DEFERRED — `maplibre-gl` sanitizer bypass (GHSA-jrc7-96c5-q579)

`maplibre-gl@5.24.0` is affected by *"XSS Sanitizer Bypass in `DOM.sanitize()`
via Live NamedNodeMap Removal Skip"*. The advisory covers `<= 6.4.0`; the only
fix is `maplibre-gl@6.11.1`, a **major** upgrade.

* **Reachable sink removed anyway.** The single HTML-injection sink in the client
  was `Map2DView.tsx`, which passed an interpolated template to
  `Popup.setHTML()` — the exact API that routes through the vulnerable
  `DOM.sanitize()`. It now builds DOM nodes and calls `Popup.setDOMContent()`,
  with all text set through `textContent`. No string is ever parsed as markup at
  that call site, so the bypass class is closed **independently of the library
  version**.
* **Verified there is no other sink.** `git grep` for
  `dangerouslySetInnerHTML|innerHTML|outerHTML` over `client/src` returns zero,
  and the deck.gl layers define no `getTooltip` HTML (grep for
  `getTooltip|Tooltip|html:` returns nothing).
* **Why deferred rather than bumped:** the 5→6 upgrade is a breaking release
  touching the map style typing (`worldStyle.ts`), `Map2DView` and
  `DeckGLLayers`, and it would land immediately before a frozen demo build. With
  the only reachable sink eliminated, the residual risk is "a future contributor
  reintroduces `setHTML`" — which the comment left at the call site warns against.
  **Scheduled action:** take `maplibre-gl@^6.11.1` as an isolated change with a
  full `tsc` + `vitest` + manual map check, outside the demo freeze.

---

## 3. Authorization

### 3.1 FIXED — unauthenticated state changes (FR-SEC-01)

Previously, `POST /v2/observations` (batch ingest) and
`POST /v2/incidents/{id}/reviews` (analyst disposition) accepted anonymous
callers, and reviews were attributed to a client-supplied `actor_id`
(default `"analyst-demo"`). On a shared host that allows anyone to inject
detections or forge a disposition in the audit trail.

New `app/core/security.py` exposes a `require_write_token` FastAPI dependency,
and `TW_WRITE_TOKEN` was added to settings:

* **`TW_WRITE_TOKEN` unset (default) → local/single-user mode.** The guard
  no-ops, so the demo and the test suite are unaffected.
* **`TW_WRITE_TOKEN` set → shared-deployment mode.** Both write endpoints require
  `Authorization: Bearer <token>`. The comparison uses `hmac.compare_digest`
  (constant-time), a missing/wrong/non-Bearer credential returns `401` with
  `WWW-Authenticate: Bearer`, and the error body never echoes the expected or the
  supplied value.

Covered by `tests/test_write_auth.py` (12 cases: local mode no-op, case-insensitive
scheme, whitespace tolerance, wrong token, wrong scheme, no secret echo, and an
assertion that both POST routes actually carry the dependency).

**Explicitly *not* claimed:** this is a shared *secret*, not identity. It does not
give per-analyst attribution, roles, revocation or session management, and
`actor_id` remains a self-declared field. Real auth is listed under *Accepted
limitations*.

### 3.2 Accepted — read endpoints and the WebSocket are public

`GET /v2/**`, the v1 endpoints and `WS /v2/stream` are unauthenticated by
design (a public situation display). The WS envelope was reviewed and carries
only `event_id, sequence, entity_type, entity_id, entity_version, event_type,
committed_at, schema_version` — identifiers and timestamps, **no observation
payloads, no credentials, no personal data** (`app/api/v2/stream.py`).

### 3.3 Verified — the LLM agent cannot exceed its tool allowlist

`client/src/features/agent/tools.ts` defines a five-tool allowlist
(`tw_query_events`, `tw_kpis`, `tw_run_model`, `tw_event_dossier`,
`tw_summarize_wire`) and `executeTool` switches over exactly those names, with an
`unknown tool` default. There is **no shell, exec, filesystem or arbitrary-URL
tool**, and every tool calls ThermoWatch's own API. Retrieved provider text
(news items) is summarised by a rule-based local function, never turned into a

---

## 4. Injection surfaces

| Surface | Result | Evidence |
|---|---|---|
| SQL — request-serving paths | **PASS** | `app/api/v2/{observations,incidents}.py` use ORM `select()` with bound parameters throughout: bbox floats are bound, `status_filter`/`activity`/`min_confidence` are validated (`ge`/`le`/`pattern`) then bound |
| SQL — f-string `text()` | **PASS** | `git grep -nE "text\(f" -- server/api/app` → zero hits |
| SQL — tooling | **ACCEPTED** | `app/tools/loadtest.py` interpolates internally generated integers into SQL. Internal, never request-served, values are not attacker-influenced. Documented here rather than changed |
| Pagination cursor tampering | **PASS** | `services/cursor.py` base64/JSON-decodes inside `except Exception` → raises `CursorError`; the API maps it to `400 Invalid cursor`. Cannot reach SQL |
| Path traversal — report export | **PASS** | the filename is derived from `incident_id: UUID` (a typed FastAPI path param, rejected by validation if not a UUID) and is used only inside `Content-Disposition`; no filesystem path is built from request data |
| Path traversal — research artefacts | **PASS** | `app/research/artifacts/` and `datasets/` are written only by offline experiment scripts; no request input reaches those paths |
| Template/HTML injection (client) | **PASS** | zero `dangerouslySetInnerHTML`/`innerHTML`/`outerHTML`; the one `setHTML` sink was replaced with DOM construction (§2.2). Provider text (news headlines, OSM names, rationale JSON) renders through React text nodes |
| Untrusted HTML in the report export | **PASS** | `/v2/incidents/{id}/report` returns `text/markdown` as a `Content-Disposition: attachment` download; `ReportExport.tsx` uses a plain download link and never injects the body into the DOM |

---

## 5. Input validation and limits

| Control | Result | Evidence |
|---|---|---|
| Batch size capped | **PASS** | `ObservationCreate.observations` — `min_length=1, max_length=5000` |
| Review note bounds | **PASS** | `note` `max_length=2000`; `review_rules.note_sufficient()` enforces the 10-character minimum for `escalated`/`dismissed`, and the server re-checks it (422) so the UI hint is never trusted |
| List pagination bounded | **PASS** | queue `limit` `le=200`; timeline `limit` `le=500`; observations `page_size` `le=500`, `page ge=1`; v1 events `window_hours le=720`, detections `days le=180`; news `le=500`, `window_hours le=168` |
| Geospatial inputs bounded | **PASS** | `lat ge=-90 le=90`, `lon ge=-180 le=180`; observation fields carry `ge/le` bounds in `schemas/observation.py`; scene radius `ge=200 le=3000` |
| No unbounded time-range scan | **PASS** | every time-window query carries an `le`-bounded window (above); the queue pages through a keyset cursor in bounded batches rather than scanning the table |
| Transition legality re-validated server-side | **PASS** | `review_rules.is_transition_valid()` is the single source of truth; an illegal action is rejected 422 and *nothing is recorded* |
| Optimistic concurrency | **PASS** | stale `expected_incident_version` → 409; reviews use `SELECT … FOR UPDATE` |
| Idempotency | **PASS** | observation ingest hashes `provider_observation_key` (sha256) and uses `ON CONFLICT DO NOTHING`; reviews replay on a repeated `idempotency_key` |

---

## 6. Error handling and information leakage

### 6.1 FIXED — `/health/ready` echoed database driver errors

`GET /health/ready` returned `{"database": str(exc)}`. asyncpg/SQLAlchemy
connection errors can include the DSN — which contains the password — to an
unauthenticated caller on a public probe route. The handler now logs the real
cause locally and always answers `{"status": "not_ready", "database":
"unreachable"}`.

### 6.2 FIXED — interactive docs were always exposed

`/docs`, `/redoc` and `/openapi.json` were unconditionally mounted. A new
`TW_DOCS_ENABLED` setting gates all three together (**default `1`**, so local
development is unchanged); shared deployments set `TW_DOCS_ENABLED=0` so the
write surface is not enumerable.

### 6.3 Verified

* No endpoint returns a traceback. `HTTPException` details were read
  individually: they describe *the client's* error and its own inputs
  (`invalid_transition`, `note_required`, `idempotency_key_reused`,
  `invalid_cursor`) — no internals.
* FastAPI's debug mode is not enabled anywhere; the app is constructed with
  `FastAPI(title=…, version=…, lifespan=…)` and no `debug=` argument.
* `/health/live` and `/health/ready` expose status only.


---

## 7. Transport, CORS and browser policy

| Check | Result | Evidence |
|---|---|---|
| No wildcard CORS | **PASS** | `git grep "allow_origins.*\*"` → zero hits. `main.py` uses the exact list from `TW_CORS_ORIGINS` (`settings.origins`, comma-split, blanks dropped) plus `TW_ORIGIN_REGEX` for Vercel rotation |
| Origin allow-list cannot silently widen | **PASS** | the regex is `https://[a-zA-Z0-9.-]+\.vercel\.app\|http://localhost(:\d+)?\|http://127\.0\.0\.1(:\d+)?` — anchored to `https://` for the hosted case, so a lookalike domain does not match |
| No mixed content | **PASS** | `git grep -nE "http://[a-z]" -- client/src client/index.html client/app.html` → only `xmlns` schema URIs (data-URI favicons) and `http://localhost` dev documentation |
| Source maps | **PASS** | `vite.config.ts` sets no `sourcemap` key; Vite's production default is `false`, so maps are not emitted into `dist/`. No CDN `<script>` is used in `index.html`/`app.html`, so no `integrity`/`crossorigin` is required |
| Bundle carries no secrets | **PASS** | after a production build, `git grep -nIE "sk-[A-Za-z0-9]{20,}\|AKIA[0-9A-Z]{16}\|api[_-]?key" -- client/dist` → zero hits. The client is built with no provider key inlined (only `VITE_API_URL`, a public base URL) |
| DuckDB / WASM sourcing | **PASS** | DuckDB is a bundled npm dependency resolved through the Vite build; no floating CDN import. GIBS imagery tiles and the OSM Overpass proxy are fetched at runtime as *data*, never loaded as executable script |
| BYO LLM key storage | **ACCEPTED — documented** | `features/agent/agentStore.ts` persists the user's own OpenAI key in `localStorage`. Any script executing on this origin can read it. This is inherent to a BYO-key browser POC. Mitigations now in place: **zero** raw-HTML sinks in the client (§2.2/§4) and no third-party script loaded into the app origin. Users are told to use a scoped, revocable key. A server-side proxy holding the key is the production answer |

---

## 8. Data-protection notes

* **No personal data** is stored or transmitted. The domain model holds satellite
  thermal detections (latitude/longitude/brightness/FRP), facility reference
  geometry, model assessments and analyst review rows. The only human-identifying
  field is the self-declared `actor_id` on a review (free text, ≤64 chars, seeded
  with the literal `analyst-demo`).
* **News/OSM content** is third-party open data rendered as plain text; headlines
  are not persisted beyond the in-memory TTL cache.
* **No PII leaves the deployment** except as query parameters to the upstream
  providers actually in use (FIRMS, Open-Meteo, GDELT/EONET/GDACS, Overpass),
  which receive coordinates and a bbox — never user identity.

---

## 9. Accepted limitations (POC scope — explicitly not fixed)

These are known, deliberate gaps. They are **not** oversights and must be closed
before any shared deployment.

1. **No real authentication or roles.** `TW_WRITE_TOKEN` is one shared secret
   (§3.1). There is no per-user identity, no revocation list, no session, no
   RBAC, and no protection for read endpoints. `actor_id` is self-declared.
2. **No rate limiting.** Nothing throttles `POST /v2/observations`, the review
   endpoint, or the provider-backed read paths (news/OSM/Sentinel-2/weather).
   A shared deployment needs a limiter (reverse proxy or app middleware).
3. **No TLS termination in-app.** Deploy behind a TLS-terminating proxy; uvicorn
   serves plain HTTP locally.
4. **No CSRF tokens.** Acceptable because the API is token/`Authorization`-based
   rather than cookie-authenticated; revisit if cookie sessions are introduced.
5. **Single-node state.** The WS `ConnectionManager` sequence counter and the
   in-memory caches (news TTL, weather, normal-state) are per-process. Redis (or
   Postgres `LISTEN/NOTIFY`) is required for multi-worker correctness.
6. **The dev database password is public** (§1.3).
7. **`maplibre-gl` 5.24.0 remains installed** with a critical advisory, mitigated
   at the call site (§2.2). Upgrade scheduled.
8. **No dependency scanning in CI.** `pip-audit`/`npm audit` were run manually
   here; wiring them into the workflow is the follow-up.
9. **Prompt injection is out of scope** for the BYO-key agent: the tools are safe
   (§3.3), but the *model output* is not sanitised — it is rendered as React text,
   so it cannot execute, and the recovery hint string is treated as untrusted
   display text.

tool call, so text cannot escalate into authorization (PRD §4.7/§6 posture).


---

## 10. Production environment checklist

Before exposing an instance to anyone but yourself:

- [ ] `TW_WRITE_TOKEN=<long random value>` — enables bearer auth on both write
      endpoints. Verify: an unauthenticated `POST /v2/observations` returns **401**.
- [ ] `TW_DOCS_ENABLED=0` — removes `/docs`, `/redoc`, `/openapi.json`.
- [ ] Replace the database credentials; set `TW_DATABASE_URL` to the real DSN and
      never keep the compose default. Keep the DB off the public internet.
- [ ] `TW_DB_REQUIRED=1` so the API fails fast instead of serving degraded.
- [ ] Terminate TLS in front of uvicorn; confirm the client's `VITE_API_URL` is
      **https** for an https page (mixed content fails silently otherwise).
- [ ] Narrow `TW_CORS_ORIGINS` to the real front-end origin(s); keep
      `TW_ORIGIN_REGEX` scoped to your Vercel project, not the whole `*.vercel.app`.
- [ ] Add rate limiting and request-size limits at the proxy.
- [ ] `FIRMS_API_KEY`, `TW_CDSE_CLIENT_ID`, `TW_CDSE_CLIENT_SECRET` supplied via
      the platform's secret store — never in the image, never in the repo.
- [ ] Keep local scratch files out of the build context; confirm `git status` is
      clean on deploy.
- [ ] Schedule the `maplibre-gl` major upgrade (§2.2) and re-enable dependency
      auditing in CI.

---

## 11. Gate results at freeze

| Gate | Command | Result |
|---|---|---|
| Server tests | `pytest -o addopts="" -q` (from `server/api`) | **159 passed, 3 skipped** |
| Write-auth unit tests | `pytest tests/test_write_auth.py -v` | **12 passed** |
| Python dependencies | `pip-audit -r requirements.lock.txt` | **No known vulnerabilities found** |
| Client types | `npx tsc --noEmit` | **exit 0** |
| Client tests | `npx vitest run` | **200 passed (33 files)** |
| Client build | `npm run build` | succeeds |
| Claim safety | `python scripts/claim_audit.py` | **PASS** |
| Client dependencies | `npm audit --omit=dev` | 1 critical, deferred (§2.2) |

**One transient note, recorded honestly:** the first full `pytest` run reported a
single failure in `tests/test_failure_injection.py::TestConcurrentReviewLock::
test_row_lock_serializes_stale_writers` (a real-Postgres row-lock race). It did
not reproduce: two subsequent full runs passed, and the test correctly *skips*
when the database is unreachable. It is timing-sensitive against a live database,
not deterministic, and unrelated to the changes in this review.

## 12. Summary

| Severity | Fixed here | Deferred (documented) |
|---|---|---|
| Critical | 1 — anonymous state-changing writes (ingest + reviews) | 1 — `maplibre-gl` advisory (call-site sink removed) |
| High | 1 — `/health/ready` DSN/password disclosure | — |
| Medium | 3 — local-path disclosure in report artefacts; unconditioned API docs; unusable lockfile | 1 — BYO key in `localStorage` |
| Low | 2 — scratch-file username hygiene; `.env.example` silently ignored | 4 — see *Accepted limitations* |
