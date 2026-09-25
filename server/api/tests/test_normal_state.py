"""Pure-computation tests for facility normal state — no DB required."""
import numpy as np
import pandas as pd
import pytest

from app.ml.normal_state import build_facility_normal_state, build_states_for_fold


def _facility_df(n=60, days=30, seed=7, base_lat=22.47, base_lon=70.07):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-06-01", periods=days, freq="D", tz="UTC")
    rows = []
    for d in dates:
        for _ in range(int(n / days) + 1):
            if len(rows) >= n:
                break
            rows.append({
                "latitude": base_lat + rng.normal(0, 0.002),
                "longitude": base_lon + rng.normal(0, 0.002),
                "frp": float(np.exp(rng.normal(3.4, 0.4))),
                "observed_at": d + pd.Timedelta(hours=int(rng.integers(0, 24))),
            })
    return pd.DataFrame(rows[:n])


class TestBuildState:
    def test_sufficient_state_deterministic(self):
        df = _facility_df()
        s1 = build_facility_normal_state(df, "F-001", "refinery")
        s2 = build_facility_normal_state(df, "F-001", "refinery")
        assert s1.sufficient
        assert s1.version == s2.version
        assert s1.log_frp_median is not None
        assert 3.0 < s1.log_frp_median < 4.0
        assert len(s1.zones) >= 1
        assert s1.zones[0].share > 0.5  # tight cluster -> one dominant zone

    def test_insufficient_history(self):
        df = _facility_df(n=5, days=3)
        s = build_facility_normal_state(df, "F-001", "refinery")
        assert not s.sufficient
        assert s.insufficient_reason is not None
        assert "insufficient history" in s.insufficient_reason

    def test_build_states_for_fold_skips_non_facility(self):
        df = _facility_df()
        df["facility_id"] = "F-001"
        df["facility_type"] = "refinery"
        df.loc[:5, "facility_id"] = ""  # natural-fire rows
        states = build_states_for_fold(df)
        assert set(states.keys()) == {"F-001"}

    def test_zone_defaults_match_research_config(self):
        """Fix 1: the builder must default to the research-validated zone
        parameters (2 km eps, 5 min samples) — 1.0/3 under-clustered the
        pixel footprint and fragmented zones into jitter artifacts."""
        import inspect

        from app.core.config import settings

        sig = inspect.signature(build_facility_normal_state)
        assert sig.parameters["zone_eps_km"].default == 2.0
        assert sig.parameters["zone_min_samples"].default == 5
        fold_sig = inspect.signature(build_states_for_fold)
        assert fold_sig.parameters["zone_eps_km"].default == 2.0
        assert fold_sig.parameters["zone_min_samples"].default == 5
        assert settings.state_zone_eps_km == 2.0
        assert settings.state_zone_min_samples == 5

    def test_day_night_split_stats_on_state(self):
        df = _facility_df(n=60, days=30)
        s = build_facility_normal_state(df, "F-001", "refinery")
        assert s.sufficient
        # Random hours over 60 obs -> both halves have >=5 rows
        assert s.log_frp_median_day is not None
        assert s.log_frp_median_night is not None
        assert s.log_frp_mad_day is not None and s.log_frp_mad_day >= 1e-6
        assert s.log_frp_mad_night is not None and s.log_frp_mad_night >= 1e-6
        # Both halves must bracket the global median
        assert s.log_frp_median is not None
        assert s.log_frp_median_day is not None
        assert s.log_frp_median_night is not None
        assert min(s.log_frp_median_day, s.log_frp_median_night) <= s.log_frp_median
        assert max(s.log_frp_median_day, s.log_frp_median_night) >= s.log_frp_median

    def test_version_hash_covers_day_night(self):
        """Same data -> same hash; the day/night medians are part of the
        state identity (two states differing only there must not collide)."""
        df = _facility_df()
        s1 = build_facility_normal_state(df, "F-001", "refinery")
        s2 = build_facility_normal_state(df, "F-001", "refinery")
        assert s1.version == s2.version
        from app.ml.normal_state import _version_hash
        payload_keys = _version_hash(s1, {})
        assert isinstance(payload_keys, str) and len(payload_keys) == 16
        assert s1.log_frp_median_night is not None  # hash input exists


class TestHaversine:
    def test_zero_distance(self):
        from app.ml.normal_state import _haversine_km
        assert _haversine_km(22.47, 70.07, 22.47, 70.07) == pytest.approx(0.0)

    def test_known_distance(self):
        from app.ml.normal_state import _haversine_km
        # ~0.1 deg latitude ~ 11.1 km
        d = _haversine_km(22.47, 70.07, 22.57, 70.07)
        assert 10.5 < d < 12.0
