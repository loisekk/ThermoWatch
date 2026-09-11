from fastapi import APIRouter

from app.data.facilities import FACILITIES
from app.ml import inference
from app.schemas.fire import PredictRequest, PredictResponse
from app.services import heuristic
from app.services.geo import haversine_km

router = APIRouter()

DEFAULT_FACILITY_DISTANCE_KM = 0.5  # "at the facility" when no coordinates are supplied


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    facility = next((f for f in FACILITIES if f["subtype"] == req.facility_subtype), None)
    if facility and req.lat is not None and req.lon is not None:
        dist_km: float | None = haversine_km(req.lat, req.lon, facility["lat"], facility["lon"])
    elif facility:
        dist_km = DEFAULT_FACILITY_DISTANCE_KM
    else:
        dist_km = None
    feats = {"frp": req.frp, "brightness_k": req.brightness_k, "night_ratio": req.night_ratio,
             "diurnal_variance": req.diurnal_variance, "persist_days": req.persist_days,
             "facility_distance_km": dist_km,
             "facility_hazard": facility["hazard"] if facility else None,
             "forest_proxy": req.forest_proxy, "agri_window": req.agri_window,
             "cluster_density": req.cluster_density,
             "detections_30d": req.detections_30d, "frp_stability": req.frp_stability}
    cls, model_name = inference.predict(feats)
    if facility and cls["primary"] in ("industrial", "persistent"):
        cls["subtype"] = facility["subtype"]
    risk = heuristic.score_risk(feats, cls["confidence"])
    rings, affected = [], []
    if req.include_spread and req.lat is not None and req.lon is not None:
        rings = heuristic.spread_rings(req.lat, req.lon, req.frp, cls["primary"], req.wind_speed_ms, req.wind_dir_deg)
        outer = rings[-1]["radius_km"] * 1.8
        affected = [f["name"] for f in FACILITIES
                    if haversine_km(req.lat, req.lon, f["lat"], f["lon"]) <= outer]
    return PredictResponse(model=model_name, classification=cls, risk=risk, spread=rings, affected_facilities=affected)

