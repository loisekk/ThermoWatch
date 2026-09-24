"""Residual pure-computation tests — no DB required."""
import numpy as np

from app.ml.normal_state import build_facility_normal_state
from app.ml.residuals import intensity_residual, spatial_residual, temporal_residual
from tests.test_normal_state import _facility_df


def _state():
    return build_facility_normal_state(_facility_df(), "F-001", "refinery")


class TestIntensityResidual:
    def test_normal_frp_small_z(self):
        st = _state()
        assert st.log_frp_median is not None
        r = intensity_residual(float(np.expm1(st.log_frp_median)), st)
        assert r.z is not None
        assert abs(r.z) < 0.5

    def test_spike_large_z(self):
        st = _state()
        assert st.log_frp_median is not None
        r = intensity_residual(float(np.expm1(st.log_frp_median)) * 6.0, st)
        assert r.z is not None 
        assert r.z > 3.5

    def test_no_state_returns_none(self):
        df = _facility_df(n=3, days=2)
        st = build_facility_normal_state(df, "F-001", "refinery")
        r = intensity_residual(50.0, st)
        assert r.z is None  # never silently zero


class TestSpatialResidual:
    def test_in_zone(self):
        st = _state()
        z = st.zones[0]
        r = spatial_residual(z.centroid_lat, z.centroid_lon, st)
        assert r.nearest_zone_km is not None
        assert r.nearest_zone_km < 0.5 
        assert not r.is_new_zone

    def test_new_zone(self):
        st = _state()
        # +0.1 deg lat ~ 11 km away from every zone
        r = spatial_residual(st.zones[0].centroid_lat + 0.1,
                             st.zones[0].centroid_lon, st)
        assert r.is_new_zone
        assert r.nearest_zone_km is not None
        assert r.nearest_zone_km > 1.5

    def test_no_zones_returns_flagged(self):
        df = _facility_df(n=3, days=2)
        st = build_facility_normal_state(df, "F-001", "refinery")
        r = spatial_residual(22.47, 70.07, st)
        assert r.nearest_zone_km is None
        assert not r.is_new_zone
        assert r.zones_known == 0


class TestTemporalResidual:
    def test_hour_surprise_bounds(self):
        st = _state()
        r = temporal_residual(12, None, st)
        assert r.hour_surprise is not None
        assert 0.0 <= r.hour_surprise <= 1.0
        assert r.interval_z is None  # no previous detection given

    def test_interval_z_with_gap(self):
        st = _state()
        r = temporal_residual(12, 5.0, st)
        # 5 days vs ~1-day median gap -> clearly positive z
        assert r.interval_z is not None
        assert r.interval_z > 0
