"""V2 API router aggregating all endpoint modules."""
from fastapi import APIRouter

from app.api.v2 import incidents, observations, stream

api_v2_router = APIRouter()

api_v2_router.include_router(
    observations.router, prefix="/observations", tags=["observations"]
)
api_v2_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
# WS stream — prefix joins the path so the route is /v2/stream.
api_v2_router.include_router(stream.router, prefix="/stream", tags=["stream"])

