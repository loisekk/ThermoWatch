"""Session 20 (server): multimodal feature contract tests.

Run fully offline (TW_ENRICHMENT=off): no network in CI, services return None and
the engineer applies documented defaults. Async entry points are driven via
asyncio.run() so no pytest-asyncio dependency is required.
"""
from __future__ import annotations

import asyncio

import pytest

from app.ml import dataset_multimodal as ds
from app.ml.classifier import MultiModalClassifier
from app.ml.feature_engineering import FeatureEngineer
from app.ml.features import (
    FEATURE_REGISTRY,
    MULTIMODAL_FEATURE_ORDER,
    MULTIMODAL_VERSION,
    multimodal_feature_vector,
)
from app.services.landcover import LandCoverService
from app.services.population import PopulationService
from app.services.weather import WeatherService


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TW_ENRICHMENT", "off")


def _event(i: int = 0, frp: float = 150.0, satellite: str = "VIIRS-NOAA20", **over: object) -> dict:
    base: dict = {
        "id": f"test_{i:03d}",
        "lat": 22.8,
        "lon": 86.2,
        "frp": frp,
        "brightness_k": 340.0,
        "confidence": 85,
        "day_night": "D",
        "detected_at": 1_700_000_000_000 + i * 3_600_000,
        "satellite": satellite,
        "diurnal_variance": 0.4,
        "agri_window": 0.1,
        "cluster_density": 0.3,
        "persistence": {"consecutive_days": 6, "detections_30d": 12, "regime": "persistent"},
    }
    base.update(over)
    return base


def test_registry_covers_the_multimodal_order() -> None:
    assert MULTIMODAL_VERSION == "tw-multimodal-v2"
    assert set(MULTIMODAL_FEATURE_ORDER) == set(FEATURE_REGISTRY.keys())
    assert len(MULTIMODAL_FEATURE_ORDER) >= 45  # 46 registry entries + population_density
    sources = {m.source for m in FEATURE_REGISTRY.values()}
    assert {"FIRMS", "OSM", "Open-Meteo", "WorldPop"} <= sources
    versions = {str(m.version.value) for m in FEATURE_REGISTRY.values()}
    assert versions == {"v1", "v2", "v3", "v4"}


def test_feature_extraction_full_contract_offline() -> None:
    eng = FeatureEngineer(weather=WeatherService(), population=PopulationService(), landcover=LandCoverService())
    event = _event(0, frp=150.0)
    nearby = [_event(1, frp=120.0, satellite="VIIRS-SNPP"), _event(2, frp=90.0, satellite="MODIS")]
    history = nearby + [_event(3, frp=200.0), _event(40, frp=60.0, lat=22.9, lon=86.3)]

    features = asyncio.run(eng.extract_features(event, nearby, history))

    assert set(features.keys()) == set(MULTIMODAL_FEATURE_ORDER)
    assert features["frp"] == 150.0
    assert features["brightness_k"] == 340.0
    assert features["daynight_flag"] == 1.0
    assert features["cluster_size"] == 3          # 2 neighbours within 500 m + self
    assert features["detections_7d"] >= 2         # recent history within 1 km
    assert features["satellite_agreement"] >= 2   # three distinct platforms
    assert 0.0 <= features["frp_stability"] <= 1.0
    assert features["persist_days"] == 6
    assert features["facility_distance_km"] is not None and features["facility_distance_km"] < 25.0
    # enrichment off -> climatological defaults, never extremes
    assert features["temperature_2m"] == 20.0
    assert features["relative_humidity"] == 50.0
    assert features["population_density"] == 0.0
    # landcover proxy is deterministic and offline (Jamshedpur steel cluster -> builtup band)
    assert features["builtup_fraction"] > 0.0


def test_encoder_sentinels_and_order() -> None:
    row = multimodal_feature_vector({})
    assert len(row) == len(MULTIMODAL_FEATURE_ORDER)
    vec = dict(zip(MULTIMODAL_FEATURE_ORDER, row))
    assert vec["facility_distance_km"] == 25.0       # no-facility sentinel
    assert vec["time_since_last_detection_h"] == 999.0
    assert vec["temperature_2m"] == 20.0             # weather default
    # deterministic categorical encodings (hash() is salted per process - never used)
    assert multimodal_feature_vector({"satellite_enc": 7})[MULTIMODAL_FEATURE_ORDER.index("satellite_enc")] == 7.0


def test_classifier_roundtrip_small_synthetic() -> None:
    X, y, prov = ds.build_synthetic_multimodal(400, seed=11)
    assert len(X) == len(y) and len(X[0]) == len(MULTIMODAL_FEATURE_ORDER)
    assert prov["mode"] == "synthetic-multimodal"

    clf = MultiModalClassifier()
    metrics = clf.train(X, y, MULTIMODAL_FEATURE_ORDER, cv=3)
    assert metrics["n_features"] == len(MULTIMODAL_FEATURE_ORDER)
    assert metrics["n_classes"] == 10

    labels, conf = clf.predict(X[:8])
    assert len(labels) == 8 and len(conf) == 8
    assert all(c >= 0.0 for c in conf)
    proba = clf.predict_proba(X[:4])
    assert proba.shape == (4, 10)
    assert abs(proba.sum(axis=1).mean() - 1.0) < 1e-6
    # synthetic signatures are separable by construction - macro-F1 should be high
    import numpy as np
    pred = clf.predict_proba(X).argmax(axis=1)
    macro = float(np.mean([np.mean(pred[np.array(y) == c] == c) for c in range(10) if (np.array(y) == c).any()]))
    assert macro > 0.7


def test_services_return_none_offline() -> None:
    from datetime import datetime, timezone
    w = asyncio.run(WeatherService().get_weather(22.8, 86.2, datetime.now(timezone.utc)))
    p = asyncio.run(PopulationService().get_population(22.8, 86.2))
    assert w is None and p is None
    lc = asyncio.run(LandCoverService().get_landcover(22.8, 86.2))
    assert lc is not None and lc.dominant_class == "builtup"  # Jamshedpur: <= 2 km band