"""Ingestion -> feature engineering -> classification -> risk -> persistence.

Classification source (Session 21): when a user-supplied thermowatch_model.joblib
is present (app/ml/models/), every detection is classified ML-primarily and the
10-way posterior is projected to the 4-class UI via the proven inference facade;
the heuristic ensemble remains the fallback when the model is absent or fails.
"""
import logging

from app.data.facilities import FACILITIES
from app.services import event_store, heuristic
from app.services.geo import haversine_km

logger = logging.getLogger(__name__)


def _nearest(lat: float, lon: float) -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for f in FACILITIES:
        km = haversine_km(lat, lon, f["lat"], f["lon"])
        if best is None or km < best[1]:
            best = (f, km)
    return best


def build_features(raw: dict, facility: dict | None,
                   dist_km: float | None, persist_days: int) -> dict:
    return {
        "frp": raw["frp"], "brightness_k": raw["bright_ti4"], "night_ratio": 0.5 if raw["daynight"] == "N" else 0.15,
        "diurnal_variance": raw.get("diurnal_variance", 0.4), "persist_days": persist_days,
        "facility_distance_km": dist_km, "facility_hazard": facility["hazard"] if facility else None,
        "forest_proxy": raw.get("forest_proxy", 0.2), "agri_window": raw.get("agri_window", 0.1),
        "cluster_density": raw.get("cluster_density", 0.3),
    }


def ml_classify(feats: dict, raw: dict) -> dict | None:
    """ML-primary classification via the user-supplied model (heuristic fallback
    happens at the caller). Returns a ClassificationOut-shaped dict, or None when
    the model is absent, its vocabulary is unmappable, or inference fails."""
    try:
        from app.ml.model_loader import get_model
        model = get_model()
        if not model.ready:
            return None
        raw_feats: dict[str, float] = {
            **{k: (float(v) if isinstance(v, (int, float)) else v)
               for k, v in feats.items() if isinstance(v, (int, float))},
            "brightness_ti4": float(raw.get("bright_ti4", 0.0)),
            "confidence": float(raw.get("confidence", 0)),
            "scan": float(raw.get("scan", 0.375)),
            "track": float(raw.get("track", 0.375)),
            "daynight": 1.0 if raw.get("daynight") == "D" else 0.0,
        }
        X = model.feature_vector(raw_feats)
        probs = model.probability_map(X)
        labels, conf = model.predict(X)
        from app.ml.features import CLASSES
        from app.ml.inference import project_to_ui
        if any(name in CLASSES for name in probs):
            cls = project_to_ui(probs, feats)
        else:
            from app.api.v1.ml_inference import UI_4CLASS
            if not probs or not all(name in UI_4CLASS for name in probs):
                logger.warning("model vocabulary unmappable (%s) - heuristic fallback", list(probs)[:3])
                return None
            total = sum(probs.values()) or 1.0
            scores = {k: v / total for k, v in probs.items()}
            top = max(scores, key=lambda k: scores[k])
            cls = {"primary": top, "subtype": None, "scores": scores,
                   "confidence": round(min(0.97, max(0.55, conf[0])) * 100)}
        cls["source"] = "thermowatch_model"
        cls["ml_raw_class"] = str(labels[0])
        cls["model_provenance"] = model.provenance
        return cls
    except Exception as exc:  # noqa: BLE001 — a broken user model must never take the ingest path down; heuristic fallback serves
        logger.warning("ml_classify failed - heuristic fallback: %s", exc)
        return None


def enrich(raw: dict) -> dict:
    cell = event_store.cell_id(raw["latitude"], raw["longitude"])
    nearest = _nearest(raw["latitude"], raw["longitude"])
    facility, dist = nearest if nearest and nearest[1] <= 3.0 else (None, None)
    prior = event_store.persistence_for(cell, raw["acq_epoch_ms"])
    feats = build_features(raw, facility, dist, prior["consecutive_days"])
    cls = ml_classify(feats, raw)
    if cls is None:
        cls = heuristic.classify(feats)
        cls["source"] = "heuristic"
    cls["subtype"] = facility["subtype"] if facility and cls["primary"] in ("industrial", "persistent") else None
    risk = heuristic.score_risk(feats, cls["confidence"])
    event_store.record_cell(cell, raw["acq_epoch_ms"])
    persistence = event_store.persistence_for(cell, raw["acq_epoch_ms"])
    return {
        "lat": raw["latitude"], "lon": raw["longitude"], "cell": cell,
        "frp": raw["frp"], "brightness_k": raw["bright_ti4"], "confidence": raw["confidence"],
        "detected_at": raw["acq_epoch_ms"], "satellite": raw["satellite"], "day_night": raw["daynight"],
        "classification": cls, "persistence": persistence, "risk": risk,
        "nearest_facility_id": facility["id"] if facility else None,
        "facility_distance_km": round(dist, 2) if dist is not None else None,
    }

