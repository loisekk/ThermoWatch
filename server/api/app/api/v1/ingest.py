from fastapi import APIRouter, Header, HTTPException

from app.api.v1.live import manager
from app.core.config import settings
from app.schemas.fire import DetectionIn
from app.services import event_store, pipeline

router = APIRouter()

@router.post("/ingest/events", status_code=201)
async def ingest(batch: list[DetectionIn], x_ingest_token: str | None = Header(default=None)):
    """Endpoint consumed by the Bun FIRMS worker. Classifies + broadcasts.

    Abuse guard: when TW_INGEST_TOKEN is set, requests must carry the matching
    x-ingest-token header. Unset (local dev) = open, as documented.
    """
    if settings.ingest_token and x_ingest_token != settings.ingest_token:
        raise HTTPException(status_code=401, detail="invalid ingest token")
    out = []
    for raw in batch:
        event = event_store.append(pipeline.enrich(raw.model_dump()))
        out.append(event)
    await manager.announce(out)  # fire:new + fire:classified + derived signals
    return {"ingested": len(out)}
