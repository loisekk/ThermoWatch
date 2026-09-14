"""Scene context endpoints — live OSM surroundings for the incident scene.

GET /scene/context?lat&lon&radius_m&fresh  -> architectural context doc
(real footprints/trees/roads/water/land-use via the Overpass proxy). `fresh=1`
is rate-guarded (min 60 s/cell) so the client refresh button can't hammer OSM.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import scene_context

router = APIRouter(prefix="/scene", tags=["scene"])


@router.get("/context")
async def scene_context_route(lat: float = Query(..., ge=-90, le=90),
                              lon: float = Query(..., ge=-180, le=180),
                              radius_m: int = Query(scene_context.DEFAULT_RADIUS_M,
                                                    ge=200, le=3000),
                              fresh: bool = False):
    if fresh and not scene_context.can_refresh(lat, lon, radius_m):
        raise HTTPException(status_code=429,
                            detail="context was force-refreshed recently - retry shortly")
    doc = await scene_context.get_context(lat, lon, radius_m, fresh=fresh)
    if fresh and doc["source"] == "osm-overpass":
        scene_context.mark_refresh(lat, lon, radius_m)
    return doc