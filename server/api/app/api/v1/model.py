from fastapi import APIRouter, HTTPException

from app.ml import inference
from app.ml.features import CLASSES, FEATURE_ORDER

router = APIRouter()

UI_PROJECTION = ("UI 4-class view (industrial/persistent/wildfire/agricultural) is a projection of the "
                 "10-way posterior: industrial family split by the STA persistence prior (>=5 detection-days), "
                 "natural family split by the seasonal residue-burn prior.")

CLAIM_SAFETY = [
    "near-real-time only — FIRMS latency is 3-6 h, never claimed real-time",
    "labels are OSM-tag / synthetic proxies, not on-site verified",
    "macro-F1 reported per class; bare accuracy never quoted",
]


@router.get("/model/card")
def card():
    return {
        "served_by": inference.model_provenance()["served_by"],
        "provenance": inference.model_provenance(),
        "eval": inference.eval_report(),
        "features": FEATURE_ORDER,
        "classes": CLASSES,
        "ui_projection": UI_PROJECTION,
        "claim_safety": CLAIM_SAFETY,
    }


@router.get("/model/confusion")
def confusion():
    rep = inference.eval_report()
    if not rep or "confusion_matrix" not in rep:
        raise HTTPException(404, "no trained bundle / eval report yet — run: python -m app.ml.train")
    return rep["confusion_matrix"]
