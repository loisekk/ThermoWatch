"""Inference facade with honest provenance: trained bundle → ST-GNN → heuristic ensemble."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.ml import stgnn
from app.ml.features import CLASSES, FEATURE_ORDER, INDUSTRIAL_LABELS, feature_vector
from app.services import heuristic

MODELS_DIR = Path(__file__).resolve().parent / "models"
BUNDLE = MODELS_DIR / "model_bundle.joblib"
REPORT = MODELS_DIR / "eval_report.json"
HEURISTIC_NAME = "heuristic-ensemble-v0"


@lru_cache(maxsize=1)
def _bundle():
    """Cached at boot; restart the API (or call reload_models()) after retraining."""
    if not BUNDLE.exists():
        return None
    import joblib
    return joblib.load(BUNDLE)


def reload_models() -> None:
    _bundle.cache_clear()


def eval_report() -> dict | None:
    if not REPORT.exists():
        return None
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # unreadable file / malformed JSON (JSONDecodeError ⊂ ValueError)
        return None


def project_to_ui(probs: dict[str, float], features: dict) -> dict:
    """Documented projection: 10-way posterior → UI 4-class scores + subtype.
    industrial/persistent split uses the STA persistence prior (>=5 d);
    wildfire/agricultural split uses the seasonal residue-burn prior."""
    p_ind = sum(probs.get(c, 0.0) for c in INDUSTRIAL_LABELS)
    p_nat = probs.get("natural_fire", 0.0)
    pd_ = features.get("persist_days", 0) or 0
    w_p = min(0.9, 0.3 + 0.06 * pd_) if pd_ >= 5 else 0.1 * pd_
    w_a = min(1.0, max(0.0, features.get("agri_window", 0.1)))
    raw = {
        "industrial": p_ind * (1 - w_p),
        "persistent": p_ind * w_p,
        "wildfire": p_nat * (1 - w_a),
        "agricultural": p_nat * w_a,
    }
    total = sum(raw.values()) or 1.0
    scores = {k: v / total for k, v in raw.items()}
    label = max(probs, key=lambda k: probs[k])
    subtype = label if label in INDUSTRIAL_LABELS and label != "unknown_industrial" else None
    return {
        "primary": max(scores, key=lambda k: scores[k]),
        "subtype": subtype,
        "scores": scores,
        "confidence": round(min(0.97, max(0.55, max(probs.values()))) * 100),
        "model_scores": probs,
    }


def predict(features: dict) -> tuple[dict, str]:
    bundle = _bundle()
    if bundle is not None:
        arr = bundle["ensemble"].predict_proba([feature_vector(features)])[0]
        names = bundle["classes"]
        return project_to_ui({names[i]: float(arr[i]) for i in range(len(names))}, features), bundle["version"]

    if stgnn.AVAILABLE and (MODELS_DIR / "stgnn_v0.pt").exists():
        import torch  # type: ignore
        model = stgnn.FireSTGNN(in_dim=len(FEATURE_ORDER))
        model.load_state_dict(torch.load(MODELS_DIR / "stgnn_v0.pt", map_location="cpu", weights_only=True))
        model.eval()
        x = torch.tensor([[feature_vector(features)]], dtype=torch.float)
        edge = torch.tensor([[0], [0]], dtype=torch.long)
        with torch.no_grad():
            arr = model(x, edge)[0]
        return project_to_ui({CLASSES[i]: float(arr[i]) for i in range(len(CLASSES))}, features), stgnn.MODEL_NAME

    cls = heuristic.classify(features)
    return {**cls, "model_scores": {}}, HEURISTIC_NAME


def model_provenance() -> dict:
    bundle = _bundle()
    rep = eval_report()
    served = bundle["version"] if bundle else (stgnn.MODEL_NAME if stgnn.AVAILABLE and (MODELS_DIR / "stgnn_v0.pt").exists() else HEURISTIC_NAME)
    return {
        "served_by": served,
        "bundle_present": bundle is not None,
        "stgnn_available": stgnn.AVAILABLE,
        "eval": None if rep is None else {
            "macro_f1": rep["metrics"]["macro_f1"],
            "weighted_f1": rep["metrics"]["weighted_f1"],
            "n_test": rep["split"]["test"],
            "trained_at": rep["trained_at"],
            "dataset_source": rep["dataset"]["source"],
            "inference_ms_p50": rep["inference_ms_p50"],
        },
        "feature_order": FEATURE_ORDER,
        "classes": CLASSES,
    }


