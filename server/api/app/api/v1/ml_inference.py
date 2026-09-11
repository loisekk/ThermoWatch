"""ML inference API for the user-supplied thermowatch_model.joblib.

Endpoints (all additive; the serving v1 /model/card and /predict are untouched):
  POST /ml/predict         {features:{...}} | {event_id:"TW-00042"} -> prediction
  POST /ml/predict/batch   {samples:[{...}, ...]}
  GET  /ml/model-card      loader describe + eval_report.json when present
  GET  /ml/features        expected feature names + classes
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ml.model_loader import EVAL_PATH, MODEL_PATH, get_model
from app.services import event_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml", tags=["ml"])

UI_4CLASS = {"industrial", "persistent", "wildfire", "agricultural"}


class PredictRequest(BaseModel):
    """Feature dict (custom / hypothetical) OR event_id (stored detection)."""
    features: dict[str, float] | None = None
    event_id: str | None = None


class PredictResponse(BaseModel):
    predicted_class: str
    confidence: float
    probabilities: dict[str, float]
    ui_primary: str | None = None          # 4-class projection when derivable
    ui_scores: dict[str, float] | None = None
    feature_count: int
    model_provenance: str
    source: str = "thermowatch_model"


class BatchPredictRequest(BaseModel):
    samples: list[dict[str, float]] = Field(min_length=1)


def _event_features(event: dict) -> dict[str, float]:
    """Best-effort feature map from a stored FireEventOut-shaped dict."""
    persist = event.get("persistence") or {}
    return {
        "frp": float(event.get("frp", 0.0)),
        "brightness_ti4": float(event.get("brightness_k", 0.0)),
        "brightness_k": float(event.get("brightness_k", 0.0)),
        "confidence": float(event.get("confidence", 0)),
        "scan": float(event.get("scan", 0.375)),
        "track": float(event.get("track", 0.375)),
        "daynight": 1.0 if event.get("day_night", "N") == "D" else 0.0,
        "persist_days": float(persist.get("consecutive_days", 0)),
        "detections_30d": float(persist.get("detections_30d", 0)),
        "facility_distance_km": float(event.get("facility_distance_km") or 999.0),
        # spatial/environmental context defaults (documented; enrichment upgrade path)
        "forest_proxy": 0.2, "agri_window": 0.1, "cluster_density": 0.3,
        "temperature_2m": 20.0, "relative_humidity": 50.0,
        "wind_speed": 0.0, "wind_direction": 0.0, "precipitation": 0.0,
        "population_density": 0.0,
    }


def _project_4class(probs: dict[str, float], feats: dict[str, Any]) -> tuple[str | None, dict[str, float] | None]:
    """Reuse the proven 10-way -> 4-class projection when the vocabulary matches;
    otherwise pass 4-class-shaped labels through directly."""
    from app.ml.features import CLASSES
    from app.ml.inference import project_to_ui

    if any(name in CLASSES for name in probs):
        ui = project_to_ui(probs, feats)
        return str(ui["primary"]), {k: float(v) for k, v in ui["scores"].items()}
    if probs and all(name in UI_4CLASS for name in probs):
        total = sum(probs.values()) or 1.0
        scores = {k: v / total for k, v in probs.items()}
        return max(scores, key=lambda k: scores[k]), scores
    return None, None


def _predict_one(features: dict[str, float]) -> PredictResponse:
    model = get_model()
    if not model.ready:
        raise HTTPException(503, "model not loaded - place thermowatch_model.joblib in server/api/app/ml/models/")
    X = model.feature_vector(features)
    labels, conf = model.predict(X)
    proba = model.predict_proba(X)[0]
    prob_dict = {c: round(float(p), 4) for c, p in zip(model.classes, proba)}
    ui_primary, ui_scores = _project_4class(model.probability_map(X), features)
    return PredictResponse(
        predicted_class=str(labels[0]),
        confidence=round(float(conf[0]), 4),
        probabilities=prob_dict,
        ui_primary=ui_primary,
        ui_scores=ui_scores,
        feature_count=len(model.feature_names),
        model_provenance=model.provenance,
    )


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    if (req.features is None) == (req.event_id is None):
        raise HTTPException(422, "provide exactly one of: features, event_id")
    if req.event_id is not None:
        event = event_store.get(req.event_id)
        if event is None:
            raise HTTPException(404, f"event {req.event_id} not found")
        return _predict_one(_event_features(event))
    assert req.features is not None
    return _predict_one(req.features)


@router.post("/predict/batch", response_model=list[PredictResponse])
def predict_batch(req: BatchPredictRequest) -> list[PredictResponse]:
    return [_predict_one(sample) for sample in req.samples]


@router.get("/model-card")
def model_card() -> dict:
    model = get_model()
    card = model.describe()
    if EVAL_PATH.exists():
        try:
            card["eval_report"] = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            card["eval_report"] = None
    return card


@router.get("/features")
def list_features() -> dict:
    model = get_model()
    if not model.ready:
        raise HTTPException(503, "model not loaded")
    return {"feature_names": model.feature_names, "n_features": len(model.feature_names),
            "classes": model.classes}


@router.post("/reload")
def reload() -> dict:
    """Re-scan for a dropped model file without restarting the API."""
    from app.ml.model_loader import reload_model
    m = reload_model()
    return {"ready": m.ready, "provenance": m.provenance}


@router.get("/pipeline-status")
def pipeline_status() -> dict:
    """Whether the live ingest path classifies via the ML model or heuristic."""
    model = get_model()
    return {
        "ml_ready": model.ready,
        "ingest_source": "thermowatch_model" if model.ready else "heuristic",
        "model_provenance": model.provenance,
        "serving_v1_facade": True,
        "model_path": str(MODEL_PATH),
        "note": "v1 bundle (model_bundle.joblib) still serves /model/card; this loader "
                "exposes the user-supplied thermowatch_model.joblib via /ml/*",
    }