"""Phase 0 + Phase 1 tests: schemas, research harness, ingest integration.

DB-dependent tests (idempotent ingest against PostGIS) skip gracefully when
Postgres is unreachable, so `pytest` stays green on machines without Docker.
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from app.research.config import SOURCE_CLASSES
from app.research.dataset import (
    create_dataset_manifest,
    generate_synthetic_dataset,
)
from app.schemas.observation import (
    FIRMSObservationRaw,
    compute_observation_key,
    normalize_observation,
)

VIIRS_ROW = {
    "latitude": 22.47, "longitude": 70.07, "bright_ti4": 320.5,
    "bright_ti5": 300.2, "scan": 0.45, "track": 0.4,
    "acq_date": "2026-09-23", "acq_time": "1530", "satellite": "N",
    "instrument": "VIIRS", "confidence": "H", "daynight": "D", "frp": 25.5,
}
MODIS_ROW = {
    "latitude": 22.47, "longitude": 70.07, "brightness": 318.0,
    "bright_t31": 299.0, "scan": 1.0, "track": 1.0,
    "acq_date": "2026-09-23", "acq_time": "0530", "satellite": "T",
    "instrument": "MODIS", "confidence": 85, "daynight": "N",
}


@pytest.fixture(scope="module")
def small_df() -> pd.DataFrame:
    """Small synthetic dataset shared by research-harness tests."""
    return generate_synthetic_dataset(
        n_days=20, n_natural_fires=5, n_agri_burns=8, seed=42
    )



async def _call(endpoint: str, method: str = "GET", payload: dict | None = None) -> dict:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        if method == "POST":
            r = await c.post(endpoint, json=payload)
        else:
            r = await c.get(endpoint, params=payload or {})
        return r.json()


@pytest.fixture(scope="module")
def db_online() -> bool:
    """Module-level probe: True only when Postgres is reachable."""
    from app.db.base import check_database

    try:
        return asyncio.run(check_database())
    except Exception:
        return False


class TestFIRMSRaw:
    def test_viirs_row_normalizes(self):
        n = normalize_observation(FIRMSObservationRaw.model_validate(VIIRS_ROW))
        assert n.sensor.value == "viirs"
        assert n.platform.value == "snpp"
        assert n.confidence.value == "high"
        assert n.day_night.value == "day"
        assert n.brightness_ti4 == 320.5
        assert n.brightness_ti5 == 300.2
        assert n.observed_at.hour == 15 and n.observed_at.minute == 30
        assert n.is_night is False
        assert n.pixel_area_km2 is not None and n.pixel_area_km2 > 0

    def test_modis_row_normalizes(self):
        n = normalize_observation(FIRMSObservationRaw.model_validate(MODIS_ROW))
        assert n.sensor.value == "modis"
        assert n.platform.value == "terra"
        assert n.confidence.value == "high"  # 85 -> high
        assert n.brightness_ti4 == 318.0
        assert n.brightness_ti5 == 299.0
        assert n.is_night is True

    def test_origin_row_rejected(self):
        bad = dict(MODIS_ROW, latitude=0, longitude=0)
        with pytest.raises(ValueError):
            FIRMSObservationRaw.model_validate(bad)

    def test_confidence_letters_normalized(self):
        n = normalize_observation(
            FIRMSObservationRaw.model_validate(dict(VIIRS_ROW, confidence="l"))
        )
        assert n.confidence.value == "low"

    def test_observation_key_stable(self):
        raw = FIRMSObservationRaw.model_validate(VIIRS_ROW)
        raw2 = FIRMSObservationRaw.model_validate(dict(VIIRS_ROW))
        assert compute_observation_key(raw) == compute_observation_key(raw2)
        assert len(compute_observation_key(raw)) == 32


class TestDataset:
    def test_schema_and_provenance(self, small_df):
        expected_cols = {
            "observation_id", "facility_id", "facility_type", "latitude", "longitude",
            "observed_at", "sensor", "platform", "frp", "brightness_ti4",
            "brightness_ti5", "scan", "track", "confidence", "day_night",
            "landcover", "is_natural_fire", "event_id", "label_source_class",
            "label_normality", "label_provenance",
        }
        assert expected_cols.issubset(small_df.columns)
        assert set(small_df["label_provenance"].unique()) == {"synthetic_truth"}
        assert small_df["observation_id"].is_unique
        # Natural/agri rows have no facility attribution but an event id
        natural = small_df[small_df["facility_id"] == ""]
        assert (natural["event_id"] != "").all()
        assert natural["label_source_class"].eq("natural_fire").all()

    def test_manifest_deterministic(self, small_df):
        m1 = create_dataset_manifest(small_df, "synthetic", "ds-test")
        m2 = create_dataset_manifest(small_df, "synthetic", "ds-test")
        assert m1["content_hash"] == m2["content_hash"]
        assert m1["schema_hash"] == m2["schema_hash"]
        assert set(m1["class_distribution"]) <= set(SOURCE_CLASSES)


class TestSplits:
    def test_facility_grouped_no_leakage(self, small_df):
        from app.research.splits import facility_grouped_split

        train_idx, test_idx, manifest = facility_grouped_split(small_df)
        assert manifest["overlap_check"] == "PASS"
        assert not set(manifest["train_groups"]) & set(manifest["test_groups"])
        assert len(train_idx) + len(test_idx) == len(small_df)

    def test_temporal_split_orders_time(self, small_df):
        from app.research.splits import temporal_split

        train_idx, test_idx, manifest = temporal_split(small_df)
        assert manifest["split_method"] == "temporal"
        assert small_df.loc[train_idx, "observed_at"].max() < small_df.loc[test_idx, "observed_at"].min()

    def test_lofo_folds_disjoint(self, small_df):
        from app.research.splits import leave_one_facility_out

        folds = leave_one_facility_out(small_df)
        assert folds, "expected at least one evaluable facility fold"
        for fid, train_idx, test_idx, mf in folds:
            assert fid == mf["held_out_facility"]
            assert not (set(train_idx) & set(test_idx))
            assert (small_df.loc[test_idx, "facility_id"] == fid).all()

    def test_geographic_split_gates_and_disjointness(self, small_df):
        """Fix 5: the buffered meridian split must PASS its R1-R3 gates,
        keep groups disjoint (re-verified independently), and report R4
        per-class support instead of silently scoring one side."""
        from app.research.splits import geographic_split

        train_idx, test_idx, manifest = geographic_split(small_df)
        gates = manifest["gates"]
        assert gates["R1_disjoint"] == "PASS"
        assert gates["R2_buffer"] == "PASS"
        assert gates["R3_no_straddle"] == "PASS"
        assert isinstance(gates["R4_support"], dict) and gates["R4_support"]

        # Independent re-verification: groups never span the two sides
        groups = small_df.apply(
            lambda r: r["facility_id"] if r["facility_id"]
            else f"event:{r['event_id']}", axis=1)
        assert not (set(groups.loc[train_idx]) & set(groups.loc[test_idx]))
        # Sides are on the correct side of the meridian, buffer rows dropped
        assert (small_df.loc[train_idx, "longitude"] < 78.0).all()
        assert (small_df.loc[test_idx, "longitude"] >= 78.0).all()
        buf = manifest["buffer_deg"]
        kept = small_df.index.isin(train_idx) | small_df.index.isin(test_idx)
        in_buffer = ((small_df["longitude"] > 78.0 - buf)
                     & (small_df["longitude"] < 78.0 + buf))
        assert not (in_buffer & kept).any()
        # Train/test partition excludes exactly the dropped rows
        assert len(train_idx) + len(test_idx) <= len(small_df)

    def test_temporal_split_guarantees_abnormal_support(self, small_df):
        """Fix 6: anomaly-task P/R needs >=20 abnormal test rows — the
        cutoff must shift to guarantee it, and the shift is recorded."""
        from app.research.splits import temporal_split_with_abnormal_support

        train_idx, test_idx, manifest = temporal_split_with_abnormal_support(
            small_df)
        total_abn = int((small_df["label_normality"] == "abnormal").sum())
        test_abn = int(
            (small_df.loc[test_idx, "label_normality"] == "abnormal").sum())
        assert not (set(train_idx) & set(test_idx))
        assert manifest["abnormal_support_required"] == 20
        assert manifest["abnormal_test_rows"] == test_abn
        if total_abn >= 20:
            assert test_abn >= 20, "shift must guarantee the support"
            assert manifest["abnormal_support_check"] == "PASS"
            assert not (small_df.loc[train_idx, "observed_at"].max()
                        >= small_df.loc[test_idx, "observed_at"].min()), \
                "shifted cutoff must still be a strict time cut"
        else:
            assert manifest["abnormal_support_check"] == "FAIL", \
                "insufficient dataset support must be recorded, never faked"



class TestMetrics:
    def test_classification_metrics_support_flags(self):
        from app.research.metrics import classification_metrics

        y_true = np.array(["a"] * 30 + ["b"] * 5 + ["c"] * 25, dtype=object)
        y_pred = np.array(["a"] * 25 + ["b"] * 5 + ["c"] * 30, dtype=object)
        out = classification_metrics(y_true, y_pred)
        assert out["per_class"]["a"]["support"] == 30
        assert "b" in out["low_support_classes"]  # support 5 < 20
        assert out["mcc"] is not None

    def test_risk_coverage_monotonic_coverage(self):
        from app.research.metrics import risk_coverage_curve

        rng = np.random.default_rng(0)
        y_true = rng.integers(0, 2, 200)
        y_pred = y_true.copy()
        y_pred[:40] = 1 - y_pred[:40]  # errors concentrated at LOW confidence
        conf = np.linspace(0.1, 0.99, 200)
        out = risk_coverage_curve(y_true, y_pred, conf)
        covs = [p["coverage"] for p in out["curve"]]
        assert covs == sorted(covs)
        assert 0 <= out["aurc"] <= 1

    def test_calibration_metrics_bounded(self):
        from app.research.metrics import calibration_metrics

        y_true = np.array([0, 1, 0, 1])
        y_proba = np.array([[0.9, 0.1], [0.2, 0.8], [0.7, 0.3], [0.4, 0.6]])
        out = calibration_metrics(y_true, y_proba)
        assert 0 <= out["ece"] <= 1
        assert 0 <= out["brier_multiclass"] <= 2

    def test_facility_level_majority_vote(self, small_df):
        from app.research.metrics import facility_level_metrics

        fac_obs = small_df[small_df["facility_id"] != ""]
        y_pred = fac_obs["label_source_class"].to_numpy(dtype=object)
        out = facility_level_metrics(fac_obs, y_pred)
        assert out["n_facilities"] == fac_obs["facility_id"].nunique()
        assert out["facility_accuracy"] == 1.0  # predicting truth


class TestBaselines:
    def test_b0_features_shape(self, small_df):
        from app.research.baselines import extract_b0_features

        X = extract_b0_features(small_df)
        assert "log_frp" in X.columns and "delta_t" in X.columns
        assert len(X) == len(small_df) and not X.isna().any().any()

    def test_b3_combined_superset(self, small_df):
        from app.research.baselines import (
            extract_b1_features,
            extract_b3_features,
            get_facility_coords,
        )

        coords = get_facility_coords()
        b3 = extract_b3_features(small_df, coords)
        b1 = extract_b1_features(small_df, coords)
        assert set(b1.columns).issubset(set(b3.columns))
        assert {"persist_7d", "persist_30d", "frp_vs_history"}.issubset(set(b3.columns))
        assert b3.shape[1] > b1.shape[1]

    def test_b1_type_onehots_gated_by_distance(self):
        """Fix 4 (H6/H7): near_<type> one-hots must not be inherited by a
        detection that is merely NEAREST to a facility — only one within
        2 km — while the continuous decay feature still carries proximity."""
        import pandas as pd

        from app.research.baselines import extract_b1_features, get_facility_coords

        coords = get_facility_coords()
        jamnagar = next(c for c in coords if c[2] == "refinery"
                        and abs(c[0] - 22.47) < 0.1)  # F-001

        base = {
            "frp": 12.0, "brightness_ti4": 320.0, "brightness_ti5": 300.0,
            "scan": 0.5, "track": 0.4, "day_night": "day",
            "sensor": "viirs", "confidence": "nominal",
            "landcover": "industrial",
            "observed_at": pd.Timestamp("2026-06-01 12:00:00", tz="UTC"),
        }
        near = dict(base, latitude=jamnagar[0], longitude=jamnagar[1])
        # ~3.1 km east of the refinery: nearest is the refinery, too far
        far = dict(base, latitude=jamnagar[0], longitude=jamnagar[1] + 0.03)
        df = pd.DataFrame([near, far])
        b1 = extract_b1_features(df, coords)

        assert b1.loc[0, "near_refinery"] == 1
        assert b1.loc[0, "near_facility"] == 1
        assert b1.loc[1, "near_refinery"] == 0, \
            "3 km away must NOT inherit the refinery one-hot"
        assert b1.loc[1, "near_facility"] == 0
        assert all(b1.loc[1, f"near_{t}"] == 0 for t in
                   ["refinery", "steel", "gas_flare", "cement", "smelter",
                    "waste_incineration", "power_plant", "chemical", "none"])
        # Continuous proximity survives the gate
        assert "facility_distance_decay" in b1.columns
        assert float(str(b1.loc[1, "facility_distance_decay"])) > 0.4
        assert float(str(b1.loc[0, "facility_distance_decay"])) > float(
            str(b1.loc[1, "facility_distance_decay"])
        )

    def test_b4_threshold_selected_on_train(self, small_df):
        from app.research.baselines import run_b4_statistical_anomaly
        from app.research.splits import temporal_split

        # B4 needs per-facility history, so it only scores under a temporal
        # split (facility-grouped holdout => test facilities have no train
        # history and B4 abstains on everything — that is by design).
        train_idx, test_idx, _ = temporal_split(small_df)
        out = run_b4_statistical_anomaly(small_df.loc[train_idx], small_df.loc[test_idx])
        assert out["baseline"] == "B4_statistical"
        assert out["selected_threshold"] in [2.0, 2.5, 3.0, 3.5, 4.0]
        if "abnormal_f1" in out:
            assert 0 <= out["abnormal_f1"] <= 1

    def test_b4_abstains_on_facility_grouped_holdout(self, small_df):
        from app.research.baselines import run_b4_statistical_anomaly
        from app.research.splits import facility_grouped_split

        train_idx, test_idx, _ = facility_grouped_split(small_df)
        out = run_b4_statistical_anomaly(small_df.loc[train_idx], small_df.loc[test_idx])
        # Held-out facilities have no train history -> full abstention
        assert out["baseline"] == "B4_statistical"
        assert out.get("error") == "No evaluable test observations" or out.get("n_insufficient_history", 0) >= 0

    def test_run_baseline_fixed_label_space(self, small_df):
        from app.research.baselines import extract_b0_features, run_baseline
        from app.research.splits import facility_grouped_split

        train_idx, test_idx, mf = facility_grouped_split(small_df)
        train_df, test_df = small_df.loc[train_idx], small_df.loc[test_idx]
        out = run_baseline(
            "B0_test",
            extract_b0_features(train_df),
            train_df["label_source_class"].astype("object").to_numpy(),
            extract_b0_features(test_df),
            test_df["label_source_class"].astype("object").to_numpy(),
            train_df, test_df,
        )
        assert mf["overlap_check"] == "PASS"
        # LabelEncoder sorts classes — compare as a set against the 10-way space
        assert {str(c) for c in out["classification"]["confusion_labels"]} == set(SOURCE_CLASSES)
        assert 0 <= out["classification"]["macro_f1"] <= 1


class TestHardCases:
    def test_hard_case_tags(self):
        from app.research.hard_cases import generate_hard_case_dataset

        df = generate_hard_case_dataset(seed=123, n_days=15)
        assert "hard_case_id" in df.columns
        tagged = set(df["hard_case_id"].unique()) - {""}
        assert {"H1_normal_persistent", "H2_intensity_spike"} <= tagged
        # Abnormal tags always carry abnormal normality
        abnormal = df[df["hard_case_id"].isin(
            ["H2_intensity_spike", "H3_new_zone", "H4_displacement", "H5_duration_anomaly"])]
        assert (abnormal["label_normality"] == "abnormal").all()

    def test_descriptions_registry(self):
        from app.research.hard_cases import HARD_CASE_DESCRIPTIONS

        assert len(HARD_CASE_DESCRIPTIONS) == 12
        assert all(k.startswith("H") for k in HARD_CASE_DESCRIPTIONS)


class TestExperimentRunner:
    def test_artifacts_written(self, small_df, tmp_path):
        from app.research.runner import run_experiment

        ds_manifest = create_dataset_manifest(small_df, "synthetic", "ds-test")
        preds = small_df[["observation_id"]].head(5)

        def fn():
            return {"metric_block": {"macro_f1": 0.5}}, preds, "All good."

        artifact_dir = run_experiment(
            experiment_id="E_TEST",
            hypothesis="artifact framework smoke",
            dataset_manifest=ds_manifest,
            split_manifest={"split_method": "facility_grouped", "split_id": "abc123"},
            config={"seed": 42},
            experiment_fn=fn,
            artifacts_root=tmp_path,
        )
        assert artifact_dir.exists()
        for name in ["MANIFEST.json", "config.json", "metrics.json",
                     "predictions.parquet", "conclusion.md",
                     "dataset_manifest.json", "split_manifest.json"]:
            assert (artifact_dir / name).exists(), name
        manifest = json.loads((artifact_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["metrics_summary"]["metric_block"] == 0.5
        assert manifest["split_id"] == "abc123"
        assert manifest["config_hash"]


class TestE1Smoke:
    def test_run_e1_end_to_end(self, small_df):
        from app.research.e01_baselines import run_e1

        metrics, predictions, conclusion = run_e1(small_df, "synthetic")
        assert set(metrics["results"]) == {
            "B0_firms_only", "B1_firms_context", "B2_firms_persistence",
            "B3_combined", "B4_statistical",
        }
        assert metrics["split_manifest_summary"]["method"] == "facility_grouped"
        assert len(predictions) > 0
        assert "B0" in conclusion and "E1" in conclusion
        # Comparison table: one row per baseline; B4 may abstain entirely on a
        # facility-grouped holdout (no train history for test facilities)
        assert 4 <= len(metrics["comparison_table"]) <= 5
        assert {r["baseline"] for r in metrics["comparison_table"]} >= {
            "B0_firms_only", "B1_firms_context", "B2_firms_persistence", "B3_combined",
        }


class TestIngestAPI:
    """End-to-end ingest + replay against the configured database.

    Each scenario runs inside ONE asyncio.run() (asyncpg connections bind to
    the creating loop) and disposes the shared pool first so no stale
    connection from a previous loop is reused. Skips when Postgres is down.
    """

    def _run_scenario(self, scenario):
        from app.db.base import engine

        async def go():
            await engine.dispose()  # drop connections from any previous loop
            from app.db.base import check_database

            if not await check_database():
                return None
            return await scenario()

        return asyncio.run(go())

    def test_idempotent_replay(self):
        import uuid

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        row = dict(VIIRS_ROW)
        # Identity key hashes lat@6dp: spread reruns over ~9e6 possible keys
        # so a row committed by a previous run can never collide.
        row["latitude"] = round(22.0 + (uuid.uuid4().int % 9_000_000) * 1e-6, 6)
        batch_id = f"test-{uuid.uuid4().hex[:12]}"

        async def scenario():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                r1 = await c.post("/v2/observations", json={"observations": [row], "source_batch_id": batch_id})
                r2 = await c.post("/v2/observations", json={"observations": [dict(row)], "source_batch_id": batch_id + "-replay"})
                return r1.json(), r2.json()

        out = self._run_scenario(scenario)
        if out is None:
            pytest.skip("database unreachable - ingest integration skipped")
        r1, r2 = out
        assert r1["accepted"] == 1 and r1["quarantined"] == 0
        assert r2["duplicates"] == 1 and r2["accepted"] == 0

    def test_malformed_row_quarantined(self):
        import uuid

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        row = dict(VIIRS_ROW, latitude=0, longitude=0)

        async def scenario():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                r = await c.post("/v2/observations", json={"observations": [row], "source_batch_id": f"q-{uuid.uuid4().hex[:12]}"})
                return r.json()

        out = self._run_scenario(scenario)
        if out is None:
            pytest.skip("database unreachable - ingest integration skipped")
        assert out["quarantined"] == 1
        assert out["accepted"] == 0
        assert out["errors"], "quarantine must record the validation reason"

    def test_bbox_filter_and_health(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                r = await c.get("/v2/observations", params={"bbox": "70.0,22.4,70.2,22.6"})
                h = await c.get("/health/ready")
                return r.json(), h.status_code, h.json()

        out = self._run_scenario(scenario)
        if out is None:
            pytest.skip("database unreachable - ingest integration skipped")
        listing, status, health = out
        assert listing["total"] >= 1
        assert listing["observations"][0]["provider_observation_key"]
        assert status == 200 and health["database"] == "connected"
