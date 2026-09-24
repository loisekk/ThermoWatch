"""tw-multimodal-v2 classifier: RF + HistGB probability-averaged ensemble over the
46-feature multimodal contract.

Additive by design: the serving v1 bundle (model_bundle.joblib) and inference.py
are untouched; this classifier writes model_multimodal.joblib alongside it so the
API can adopt v2 behind an explicit flag after the eval report is reviewed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

from app.ml.ensemble import ProbAverageEnsemble, build_members
from app.ml.features import MULTIMODAL_VERSION

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent / "models"
DEFAULT_BUNDLE = MODELS_DIR / "model_multimodal.joblib"


class MultiModalClassifier:
    VERSION = MULTIMODAL_VERSION

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_BUNDLE
        self.ensemble: ProbAverageEnsemble | None = None
        self.scaler = StandardScaler()
        self.feature_names: list[str] = []
        self.classes: list[str] = []

    # ------------------------------------------------------------------ train
    def train(self, X: np.ndarray, y: np.ndarray, feature_names: list[str], cv: int = 5) -> dict:
        """Fit the ensemble on the multimodal matrix; returns headline metrics."""
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)
        self.feature_names = list(feature_names)
        self.ensemble = ProbAverageEnsemble(build_members(len(set(y.tolist()))))
        logger.info("training tw-multimodal-v2: n=%d d=%d", len(y), X.shape[1])
        self.ensemble.fit(X, y)

        labels = [int(c) for c in self.ensemble.classes_]
        self.classes = [str(c) for c in labels]
        cv_scores = cross_val_score(self.ensemble.members[0], X, y, cv=cv, scoring="f1_macro") if cv > 1 else []
        rf = self.ensemble.members[0]
        importance = sorted(zip(self.feature_names, rf.feature_importances_), key=lambda kv: kv[1], reverse=True)

        metrics = {
            "model": self.VERSION,
            "n_samples": len(y),
            "n_features": int(X.shape[1]),
            "n_classes": len(labels),
            "cv_f1_macro_mean": round(float(np.mean(cv_scores)), 4) if len(cv_scores) else None,
            "cv_f1_macro_std": round(float(np.std(cv_scores)), 4) if len(cv_scores) else None,
            "feature_importance_top10": [(n, round(float(v), 4)) for n, v in importance[:10]],
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()
        return metrics

    # ------------------------------------------------------------------ infer
    def _ensure_loaded(self) -> ProbAverageEnsemble:
        if self.ensemble is None:
            self.load()
        assert self.ensemble is not None
        return self.ensemble

    def predict_proba(self, X) -> np.ndarray:
        ens = self._ensure_loaded()
        return ens.predict_proba(np.asarray(X, dtype=float))

    def predict(self, X) -> tuple[list[str], list[float]]:
        ens = self._ensure_loaded()
        proba = ens.predict_proba(np.asarray(X, dtype=float))
        idx = proba.argmax(axis=1)
        labels = [self.class_name(int(i)) for i in idx]
        conf = proba.max(axis=1)
        return labels, [float(c) for c in conf]

    def class_name(self, index: int) -> str:
        if self.classes:
            return self.classes[index] if isinstance(self.classes[index], str) else str(self.classes[index])
        from app.ml.features import CLASSES
        return CLASSES[index]

    # ------------------------------------------------------------------ io
    def save(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "version": self.VERSION,
            "ensemble": self.ensemble,
            "scaler": self.scaler,
            "feature_names": self.feature_names,
            "classes": self.classes,
        }, self.model_path)
        logger.info("model saved -> %s", self.model_path)

    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(f"multimodal bundle not found at {self.model_path}")
        data = joblib.load(self.model_path)
        self.ensemble = data["ensemble"]
        self.scaler = data["scaler"]
        self.feature_names = data["feature_names"]
        self.classes = data["classes"]
        logger.info("model loaded <- %s (%s)", self.model_path, data.get("version"))


classifier = MultiModalClassifier()