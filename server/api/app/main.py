import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.live import manager
from app.api.v1.live import router as live_router
from app.api.v1.router import api_router
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
    manager.heartbeat_task = asyncio.create_task(manager.heartbeat_loop())
    try:
        yield
    finally:
        manager.heartbeat_task.cancel()

app = FastAPI(title="ThermoWatch API", version="0.2.0",
              description="SIH26162 — multi-class industrial fire classification & persistent thermal source intelligence",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.api_v1)
app.include_router(live_router, prefix=settings.api_v1)
