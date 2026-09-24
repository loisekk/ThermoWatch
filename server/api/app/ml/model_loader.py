"""Universal loader for a user-supplied thermowatch_model.joblib.

Accepts any common bundle shape and normalises it to predict_proba + classes:
  - bare sklearn estimator (RandomForest / HistGB / XGB / ...)
  - sklearn Pipeline
  - dict bundle {"model": est | {"rf": est, "hgb": est}, "scaler", "feature_names", "classes"}
  - this repo's bundles {"version", "ensemble": ProbAverageEnsemble, ...}

Additive by design: the serving v1 facade (app.ml.inference) is untouched. The
API keeps serving v1 and exposes this model through /api/v1/ml/* once the file
is dropped into server/api/app/ml/models/.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.ml.features import CLASSES

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODELS_DIR / "thermowatch_model.joblib"
EVAL_PATH = MODELS_DIR / "eval_report.json"

# External models often use long-form names; map the common variants onto this
# repo's 10-way CLASSES vocabulary so the 4-class UI projection stays coherent.
NAME_ALIASES: dict[str, str] = {
    "steel_plant": "steel", "steel_mill": "steel",
    "cement_kiln": "cement", "cement_plant": "cement",
    "chemical_plant": "chemical", "refinery_fire": "refinery",
    "industrial_fire": "unknown_industrial", "industrial": "unknown_industrial",
    "crop_residue": "natural_fire", "crop_burning": "natural_fire",
    "forest_fire": "natural_fire", "wildfire": "natural_fire",
    "grassland_fire": "natural_fire", "vegetation_fire": "natural_fire",
    "persistent": "gas_flare",  # 4-class persistent -> closest industrial 10-way member
}


class LoadedModel:
    """Normalised predict/predict_proba interface over any joblib bundle."""

    def __init__(self) -> None:
        self.raw: Any = None
        self.model: Any = None
        self.scaler: Any = None
        self.feature_names: list[str] = []
        self.classes: list[str] = []
        self.is_ensemble: bool = False
        self.ready: bool = False
        self.provenance = "not-loaded"

    # ------------------------------------------------------------------ load
    def load(self, path: Path | None = None) -> LoadedModel:
        p = path or MODEL_PATH
        if not p.exists():
            self.ready = False
            self.provenance = f"missing ({p.name})"
            return self
        try:
            self.raw = joblib.load(p)
            self._detect_structure()
            self.ready = self.model is not None
            logger.info("model loaded: %s | features=%d classes=%s ensemble=%s",
                        self.provenance, len(self.feature_names), self.classes, self.is_ensemble)
        except Exception as exc:  # noqa: BLE001 — corrupt pickle / version skew -> stay heuristic (load fallback)
            self.ready = False
            self.provenance = f"load-failed ({type(exc).__name__})"
            logger.warning("model load failed: %s", exc)
        return self

    def _detect_structure(self) -> None:
        obj = self.raw

        if isinstance(obj, dict):
            self.scaler = obj.get("scaler")
            self.feature_names = [str(f) for f in (obj.get("feature_names") or obj.get("feature_order") or [])]
            self.classes = [str(c) for c in (obj.get("classes") or obj.get("class_names") or [])]

            candidate = obj.get("model")
            if candidate is None and "ensemble" in obj:
                candidate = obj["ensemble"]
            if isinstance(candidate, dict):
                # {"rf": est, "hgb": est} style ensemble dict
                ests = {k: v for k, v in candidate.items()
                        if v is not None and (hasattr(v, "predict_proba") or hasattr(v, "predict"))}
                if ests:
                    self.model = ests
                    self.is_ensemble = len(ests) > 1
                    self.provenance = f"ensemble({', '.join(ests)})"
                else:
                    self.model = None
                    self.provenance = "empty-dict"
                self._autodetect_meta()
                return
            if candidate is not None and (hasattr(candidate, "predict_proba") or hasattr(candidate, "predict")):
                self.model = candidate
                self.is_ensemble = False
                self.provenance = type(candidate).__name__
                self._autodetect_meta()
                return

            # top-level estimator keys fallback ({"rf": ..., "hgb": ...} at root)
            skip = {"scaler", "feature_names", "feature_order", "classes", "class_names",
                    "metadata", "version", "eval_report", "model", "ensemble"}
            ests = {k: v for k, v in obj.items()
                    if k not in skip and v is not None and (hasattr(v, "predict_proba") or hasattr(v, "predict"))}
            if ests:
                self.model = ests
                self.is_ensemble = len(ests) > 1
                self.provenance = f"dict({', '.join(ests)})"
            else:
                self.model = None
                self.provenance = "unrecognised-bundle"
            self._autodetect_meta()
            return

        if hasattr(obj, "steps"):  # sklearn Pipeline
            self.model = obj
            self.provenance = f"Pipeline({', '.join(name for name, _ in obj.steps)})"
            final = obj.steps[-1][1]
            if hasattr(final, "classes_"):
                self.classes = [str(c) for c in final.classes_]
            self._autodetect_meta()
            return

        if hasattr(obj, "predict_proba") or hasattr(obj, "predict"):
            self.model = obj
            self.provenance = type(obj).__name__
            self._autodetect_meta()
            return

        self.model = None
        self.provenance = f"unknown({type(obj).__name__})"

    def _first_estimator(self) -> Any:
        """Primary estimator of the loaded bundle (metadata autodetect source)."""
        if isinstance(self.model, dict):
            return next(iter(self.model.values()), None)
        if hasattr(self.model, "steps"):  # sklearn Pipeline
            return self.model.steps[-1][1]
        return self.model

    def _autodetect_meta(self) -> None:
        est = self._first_estimator()
        if not self.classes and est is not None and hasattr(est, "classes_"):
            self.classes = [str(c) for c in est.classes_]
        # numeric labels -> this repo's 10-way vocabulary when the arity matches
        if self.classes and all(c.isdigit() for c in self.classes) and len(self.classes) == len(CLASSES):
            self.classes = list(CLASSES)
        if not self.feature_names and est is not None:
            if hasattr(est, "feature_names_in_"):
                self.feature_names = [str(f) for f in est.feature_names_in_]
            elif hasattr(est, "n_features_in_"):
                self.feature_names = [f"f{i}" for i in range(int(est.n_features_in_))]

    # ------------------------------------------------------------------ infer
    def _scaled(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        return self.scaler.transform(X) if self.scaler is not None else X

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.ready:
            raise RuntimeError("model not loaded")
        Xs = self._scaled(X)
        if self.is_ensemble and isinstance(self.model, dict):
            probas = [est.predict_proba(Xs) for est in self.model.values() if hasattr(est, "predict_proba")]
            if probas:
                return np.mean(probas, axis=0)
            est = next(iter(self.model.values()))
            return np.asarray(est.predict(Xs))
        if hasattr(self.model, "predict_proba"):
            return np.asarray(self.model.predict_proba(Xs))
        preds = np.asarray(self.model.predict(Xs))
        n_cls = len(self.classes) or int(preds.max()) + 1
        proba = np.zeros((len(preds), n_cls))
        for i, p in enumerate(preds):
            idx = self.classes.index(p) if isinstance(p, str) and p in self.classes else int(p)
            proba[i, min(max(idx, 0), n_cls - 1)] = 1.0
        return proba

    def predict(self, X: np.ndarray) -> tuple[list[str], list[float]]:
        proba = self.predict_proba(X)
        idx = proba.argmax(axis=1)
        labels = [self.classes[i] if i < len(self.classes) else str(i) for i in idx]
        return labels, [float(c) for c in proba.max(axis=1)]

    def probability_map(self, X: np.ndarray) -> dict[str, float]:
        """{class name -> probability} with external names mapped to this repo's
        10-way CLASSES vocabulary (aggregated when several map to one target)."""
        proba = self.predict_proba(X)[0]
        out: dict[str, float] = {}
        for i, p in enumerate(proba):
            name = self.classes[i] if i < len(self.classes) else str(i)
            name = NAME_ALIASES.get(name.lower(), name)
            out[name] = out.get(name, 0.0) + float(p)
        return out

    def feature_vector(self, raw: dict[str, float]) -> np.ndarray:
        if self.feature_names:
            row = [float(raw.get(f, 0.0)) for f in self.feature_names]
        else:
            row = [float(v) for v in raw.values()]
        return np.array([row], dtype=float)

    def describe(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "provenance": self.provenance,
            "n_features": len(self.feature_names),
            "feature_names": self.feature_names,
            "classes": self.classes,
            "is_ensemble": self.is_ensemble,
            "has_scaler": self.scaler is not None,
            "model_path": str(MODEL_PATH),
        }


loaded_model = LoadedModel()


def get_model() -> LoadedModel:
    """Lazy singleton; reloads when the file appears after boot."""
    if not loaded_model.ready:
        loaded_model.load()
    return loaded_model


def reload_model() -> LoadedModel:
    loaded_model.load()
    return loaded_model