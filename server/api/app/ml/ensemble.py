"""Probability-averaged ensemble members.

Lives in its own module (not train.py) so the trained bundle pickles the class
as `app.ml.ensemble.ProbAverageEnsemble` — `python -m app.ml.train` executes
train.py as `__main__`, which would make the pickle unresolvable at inference.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier


class ProbAverageEnsemble:
    """Probability-averaged ensemble (RF + HistGB [+ XGBoost when installed])."""

    def __init__(self, members: list) -> None:
        self.members = members

    def fit(self, X, y):
        for m in self.members:
            m.fit(X, y)
        return self

    def predict_proba(self, X):
        return np.mean([m.predict_proba(X) for m in self.members], axis=0)

    @property
    def classes_(self):
        return self.members[0].classes_


def build_members(n_classes: int) -> list:
    members: list = [
        RandomForestClassifier(n_estimators=300, max_depth=None, class_weight="balanced_subsample", n_jobs=-1, random_state=7),
        HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31, random_state=7),
    ]
    try:
        from xgboost import XGBClassifier
        members.append(XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.08,
                                     objective="multi:softprob", num_class=n_classes,
                                     eval_metric="mlogloss", n_jobs=-1))
    except ImportError:
        pass
    return members
