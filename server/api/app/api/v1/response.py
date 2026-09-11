from fastapi import APIRouter
from pydantic import BaseModel

from app.services.response import recommend_response

router = APIRouter()


class RecommendRequest(BaseModel):
    lat: float
    lon: float
    fire_class: str
    hazard: str | None = None
    wind_dir_deg: float = 270.0


@router.post("/response/recommend")
def recommend(req: RecommendRequest):
    return recommend_response(req.lat, req.lon, req.fire_class, req.hazard, req.wind_dir_deg)