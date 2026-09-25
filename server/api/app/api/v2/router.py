"""V2 API router aggregating all endpoint modules."""
from fastapi import APIRouter

from app.api.v2 import incidents, observations, stream

api_v2_router = APIRouter()

api_v2_router.include_router(
    observations.router, prefix="/observations", tags=["observations"]
)
api_v2_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
# WS stream — stream.router already declares "/stream" as its full route path;
# adding a prefix here would join to "/stream/stream" (the client, docs and the
# original intent all say the endpoint is /v2/stream).
api_v2_router.include_router(stream.router, tags=["stream"])

