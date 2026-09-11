from typing import Literal

from pydantic import BaseModel, Field

FireClass = Literal["industrial", "persistent", "wildfire", "agricultural"]
Subtype = Literal["refinery", "steel", "gas_flare", "cement", "smelter", "chemical", "power_plant", "waste_incineration"] | None
Regime = Literal["transient", "persistent", "seasonal"]
RiskLevel = Literal["low", "moderate", "high", "critical"]

class DetectionIn(BaseModel):
    """Raw FIRMS-shaped detection published by the Bun ingest worker."""
    latitude: float
    longitude: float
    frp: float
    bright_ti4: float
    confidence: int = Field(ge=0, le=100)
    satellite: str
    daynight: Literal["D", "N"]
    acq_epoch_ms: int

class ClassificationOut(BaseModel):
    primary: FireClass
    subtype: Subtype = None
    scores: dict[str, float]
    confidence: int
    """Classification provenance: heuristic | thermowatch_model (Session 21)."""
    source: str | None = None
    """Raw model label before the 4-class projection, when ML served."""
    ml_raw_class: str | None = None
    model_provenance: str | None = None

class PersistenceOut(BaseModel):
    consecutive_days: int
    detections_30d: int
    regime: Regime

class RiskOut(BaseModel):
    score: int
    level: RiskLevel
    drivers: list[str]

class FireEventOut(BaseModel):
    id: str
    lat: float
    lon: float
    cell: str
    frp: float
    brightness_k: float
    confidence: int
    detected_at: int
    satellite: str
    day_night: Literal["D", "N"]
    classification: ClassificationOut
    persistence: PersistenceOut
    risk: RiskOut
    nearest_facility_id: str | None
    facility_distance_km: float | None

class PredictRequest(BaseModel):
    """Manual ML entry-point (user-supplied parameters)."""
    frp: float = Field(gt=0)
    brightness_k: float = 320
    persist_days: int = 0
    night_ratio: float = 0.3
    diurnal_variance: float = 0.4
    lat: float | None = None
    lon: float | None = None
    facility_subtype: Subtype = None
    forest_proxy: float = 0.2
    agri_window: float = 0.1
    cluster_density: float = 0.3
    detections_30d: float = 0
    frp_stability: float = 0.5
    include_spread: bool = False
    wind_speed_ms: float = 4.0
    wind_dir_deg: float = 270.0

class SpreadRing(BaseModel):
    hours: int
    radius_km: float
    polygon: list[list[float]]

class PredictResponse(BaseModel):
    model: str
    classification: ClassificationOut
    risk: RiskOut
    spread: list[SpreadRing] = []
    affected_facilities: list[str] = []
