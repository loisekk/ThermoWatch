import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.live import manager
from app.api.v1.live import router as live_router
from app.api.v1.router import api_router
from app.api.v2.router import api_v2_router
from app.core.config import settings
from app.services import event_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    event_store.seed_if_empty()
    try:
        from app.ml.model_loader import get_model
        m = get_model()
        if m.ready:
            logger.info("user model ready: %s | %d features | classes=%s",
                        m.provenance, len(m.feature_names), m.classes)
        else:
            logger.info("user model not present (%s) - heuristic/v1 serving", m.provenance)
    except Exception as exc:  # noqa: BLE001 — boot must never be blocked by a corrupt user pickle; heuristic/v1 keeps serving
        logging.getLogger(__name__).warning("model warm-load skipped: %s", exc)
    # Phase 0: durable storage probe. Never blocks boot — the V1 in-memory
    # pipeline keeps serving without Postgres and /health/ready reports degraded.
    try:
        from app.db.base import check_database
        if await check_database():
            logger.info("database connected (PostGIS)")
        else:
            level = logging.ERROR if settings.db_required else logging.WARNING
            logger.log(level, "database unreachable - v2 persistence degraded%s",
                       "" if settings.db_required else " (v1 in-memory pipeline unaffected)")
    except Exception as exc:  # noqa: BLE001 — optional dependency, never fatal
        logging.getLogger(__name__).warning("database probe skipped: %s", exc)
    manager.heartbeat_task = asyncio.create_task(manager.heartbeat_loop())
    # Phase 2: transactional-outbox drain (WS broadcast of committed events).
    # DB-down is tolerated: rows stay unpublished and are retried next tick.
    outbox_task: asyncio.Task | None = None
    try:
        from app.db.base import async_session_factory
        from app.services.outbox import publish_pending

        async def _outbox_loop() -> None:
            while True:
                try:
                    async with async_session_factory() as s:
                        await publish_pending(s)
                except Exception:  # noqa: BLE001 — retried on the next tick
                    await asyncio.sleep(2)
                    continue
                await asyncio.sleep(2)

        outbox_task = asyncio.create_task(_outbox_loop())
    except Exception as exc:  # noqa: BLE001 — optional wiring, never fatal
        logger.warning("outbox drain not started: %s", exc)
    try:
        yield
    finally:
        manager.heartbeat_task.cancel()
        if outbox_task is not None:
            outbox_task.cancel()
        try:
            from app.db.base import engine as _engine
            await _engine.dispose()
        except Exception:  # noqa: BLE001 — shutdown hygiene only
            pass

app = FastAPI(title="ThermoWatch API", version="0.2.0",
              description="SIH26162 — multi-class industrial fire classification & persistent thermal source intelligence",
              lifespan=lifespan,
              # Interactive docs are opt-out: TW_DOCS_ENABLED=0 removes /docs,
              # /redoc and /openapi.json together, so a shared deployment does
              # not hand out a full map of its write surface.
              docs_url="/docs" if settings.docs_enabled else None,
              redoc_url="/redoc" if settings.docs_enabled else None,
              openapi_url="/openapi.json" if settings.docs_enabled else None)
# Regex origin allow-list (Vercel prod + every preview/deployment URL + localhost).
app.add_middleware(CORSMiddleware,
                   allow_origins=settings.origins,          # keep the exact list too (harmless)
                   allow_origin_regex=settings.origin_regex,  # the gate that never breaks on URL rotation
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.api_v1)
app.include_router(live_router, prefix=settings.api_v1)
# Phase 0: durable-storage backed v2 API (observations, incidents)
app.include_router(api_v2_router, prefix=settings.api_v2)


@app.get("/health/live", tags=["health"])
async def health_live() -> dict:
    """Liveness probe — no external dependencies checked."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"], response_model=None)
async def health_ready() -> dict[str, str] | JSONResponse:
    """Readiness probe — checks database connectivity (503 when unreachable)."""
    try:
        from app.db.base import check_database
        if await check_database():
            return {"status": "ready", "database": "connected"}
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unreachable"},
        )
    except Exception as exc:  # noqa: BLE001
        # The real cause is logged locally and NEVER returned: asyncpg/SQLAlchemy
        # driver errors can echo the DSN (and therefore the password) back to an
        # unauthenticated caller.
        logger.warning("health/ready database probe failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unreachable"},
        )
