"""Residual pure-computation tests — no DB required."""
import numpy as np
import pytest

from app.ml.normal_state import build_facility_normal_state
from app.ml.residuals import (
    MAD_TO_SIGMA,
    intensity_residual,
    spatial_residual,
    sustained_shift_residual,
    temporal_residual,
)
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
        r = spatial_residual(
            z.centroid_lat, z.centroid_lon, st,
            obs_scan_km=0.4, obs_track_km=0.4,
        )
        assert r.nearest_zone_km is not None
        assert r.nearest_zone_km < 0.5 
        assert not r.is_new_zone

    def test_new_zone(self):
        st = _state()
        # +0.1 deg lat ~ 11 km away from every zone
        r = spatial_residual(st.zones[0].centroid_lat + 0.1,
                             st.zones[0].centroid_lon, st,
                             obs_scan_km=0.4, obs_track_km=0.4)
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

    def test_pixel_tolerance_decides_the_same_offset(self):
        """The SAME 2.8 km offset is a new zone for a VIIRS-class pixel and
        explained by an MODIS-class pixel — the gate is pixel-aware (plan 4.1)."""
        st = _state()
        z = st.zones[0]
        dlon = 2.8 / (111.32 * np.cos(np.radians(z.centroid_lat)))
        viirs = spatial_residual(z.centroid_lat, z.centroid_lon + dlon, st,
                                 obs_scan_km=0.4, obs_track_km=0.4)
        modis = spatial_residual(z.centroid_lat, z.centroid_lon + dlon, st,
                                 obs_scan_km=2.0, obs_track_km=2.0)
        assert viirs.is_new_zone
        assert not modis.is_new_zone

    def test_missing_pixel_uses_conservative_default(self):
        """A caller with no scan/track still gets the VIIRS-class default —
        never a zero-tolerance gate."""
        st = _state()
        z = st.zones[0]
        no_pixel = spatial_residual(z.centroid_lat, z.centroid_lon, st)
        viirs = spatial_residual(z.centroid_lat, z.centroid_lon, st,
                                 obs_scan_km=0.4, obs_track_km=0.4)
        assert no_pixel.is_new_zone == viirs.is_new_zone


class TestSustainedShiftResidual:
    def test_sustained_catches_slow_drift_not_noise(self):
        state = _state()  # median ~3.4 log-space
        drift = [3.4 + 0.9] * 8        # +~2.5x sustained (H5 shape)
        noise = [3.4 + v for v in (0.5, -0.4, 0.3, -0.5, 0.4, -0.3)]
        drift_residual = sustained_shift_residual(drift, state, is_night=False)
        noise_residual = sustained_shift_residual(noise, state, is_night=False)
        assert drift_residual.z is not None and drift_residual.z > 3.0
        assert noise_residual.z is not None
        assert abs(noise_residual.z) < 3.0

    def test_short_window_returns_none_not_normal(self):
        """Below min_window the arm abstains — None must never read as normal."""
        state = _state()
        r = sustained_shift_residual([9.0, 9.0, 9.0], state, is_night=False)
        assert r.z is None
        assert r.n_window == 3

    def test_drift_is_caught_before_ten_rows(self):
        """H5 fires mid-block, not only at the end: a window with 6 of 8 rows
        elevated already separates from the baseline."""
        state = _state()
        window = [3.42] * 2 + [4.3] * 6
        r = sustained_shift_residual(window, state, is_night=False)
        assert r.z is not None and r.z > 3.0

    def test_scale_of_z_matches_sample_size_correction(self):
        """z uses se = MAD_TO_SIGMA*mad/sqrt(K) — checked against the closed form."""
        state = _state()
        base = state.log_frp_median_day or state.log_frp_median
        assert base is not None
        short = sustained_shift_residual([base] * 5, state, is_night=False)
        long = sustained_shift_residual([base + 0.3] * 8, state, is_night=False)
        assert short.z is None or abs(short.z) < 1.0
        assert long.z is not None
        mad = state.log_frp_mad_day or state.log_frp_mad
        assert mad is not None
        expected = 0.3 / (MAD_TO_SIGMA * mad / np.sqrt(8))
        assert long.z == pytest.approx(expected, abs=1e-2)

    def test_insufficient_state_returns_none(self):
        df = _facility_df(n=3, days=2)
        st = build_facility_normal_state(df, "F-001", "refinery")
        r = sustained_shift_residual([9.0] * 8, st, is_night=False)
        assert r.z is None


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


# =====================================================================
# Zone-relative gating (Fix 1): the gate absorbs the zone's own extent.
# =====================================================================
def _wide_zone_state(n=60, base_lat=22.47, base_lon=70.07):
    """Facility history spread ~9 km east-west in a dense line so DBSCAN
    (eps=2 km) chains it into ONE zone with a multi-kilometre radius."""
    import pandas as pd

    from app.ml.normal_state import build_facility_normal_state

    rng = np.random.default_rng(5)
    dates = pd.date_range("2026-06-01", periods=n, freq="D", tz="UTC")
    lons = base_lon + np.linspace(0.0, 0.085, n)  # ~8.7 km span at lat 22
    rows = [{
        "latitude": base_lat + rng.normal(0, 0.001),
        "longitude": float(lon) + rng.normal(0, 0.001),
        "frp": float(np.exp(rng.normal(3.4, 0.3))),
        "observed_at": dates[i],
    } for i, lon in enumerate(lons)]
    return build_facility_normal_state(pd.DataFrame(rows), "F-wide", "refinery")


class TestZoneRelativeGating:
    def test_wide_zone_radius_is_multikilometre(self):
        st = _wide_zone_state()
        assert st.sufficient
        assert len(st.zones) == 1, "dense line must chain into one zone"
        assert st.zones[0].radius_km > 3.0, "zone must absorb its own extent"

    def test_detection_inside_zone_radius_is_not_new_zone(self):
        """A point ~4 km from the centroid but INSIDE the zone's measured
        radius is IN the zone — the old raw-distance gate fired here."""
        st = _wide_zone_state()
        z = st.zones[0]
        r = spatial_residual(z.centroid_lat, z.centroid_lon + 0.04, st)
        assert r.nearest_zone_km is not None
        assert r.nearest_zone_km > 1.5, "raw distance exceeds the flat gate"
        assert not r.is_new_zone, "zone-relative gate must absorb it"

    def test_detection_far_beyond_radius_is_new_zone(self):
        st = _wide_zone_state()
        z = st.zones[0]
        r = spatial_residual(z.centroid_lat, z.centroid_lon + 0.25, st)
        assert r.nearest_zone_km is not None
        assert r.is_new_zone, "truly past the zone extent must still fire"

    def test_noise_history_disarms_spatial_arm(self):
        """>50% unclustered history = jitter artifacts: zones are emptied and
        the spatial residual cannot fire (intensity/temporal stay valid)."""
        import pandas as pd

        from app.ml.normal_state import build_facility_normal_state

        rng = np.random.default_rng(9)
        dates = pd.date_range("2026-06-01", periods=60, freq="D", tz="UTC")
        rows = [{
            "latitude": 22.47 + rng.normal(0, 1.0),   # ~110 km scatter
            "longitude": 70.07 + rng.normal(0, 1.0),
            "frp": float(np.exp(rng.normal(3.4, 0.3))),
            "observed_at": dates[i],
        } for i in range(60)]
        st = build_facility_normal_state(pd.DataFrame(rows), "F-noise",
                                         "refinery")
        assert st.sufficient
        assert st.noise_share > 0.5
        assert st.zones == []
        r = spatial_residual(22.47, 70.07, st)
        assert not r.is_new_zone
        assert r.zones_known == 0


# =====================================================================
# Day/night split intensity (Fix 2): bimodal FRP needs two medians.
# =====================================================================
def _bimodal_state():
    import pandas as pd

    from app.ml.normal_state import build_facility_normal_state

    rng = np.random.default_rng(11)
    dates = pd.date_range("2026-06-01", periods=40, freq="D", tz="UTC")
    rows = []
    for d in dates:
        # Day mode: log-FRP ~ 3.0; night mode (night_boost): ~ 5.0
        rows.append({
            "latitude": 22.47 + rng.normal(0, 0.002),
            "longitude": 70.07 + rng.normal(0, 0.002),
            "frp": float(np.exp(rng.normal(3.0, 0.05))),
            "observed_at": d + pd.Timedelta(hours=int(rng.integers(10, 16))),
        })
        rows.append({
            "latitude": 22.47 + rng.normal(0, 0.002),
            "longitude": 70.07 + rng.normal(0, 0.002),
            "frp": float(np.exp(rng.normal(5.0, 0.05))),
            "observed_at": d + pd.Timedelta(hours=int(rng.integers(19, 23))),
        })
    return build_facility_normal_state(pd.DataFrame(rows), "F-bim", "refinery")


class TestDayNightIntensity:
    def test_split_stats_populated_and_separated(self):
        st = _bimodal_state()
        assert st.log_frp_median_day is not None
        assert st.log_frp_median_night is not None
        assert st.log_frp_mad_day is not None and st.log_frp_mad_night is not None
        # Night mode is strictly hotter in log space
        assert st.log_frp_median_night > st.log_frp_median_day + 1.0

    def test_normal_night_row_not_flagged_by_split_stats(self):
        st = _bimodal_state()
        assert st.log_frp_median_night is not None
        normal_night = float(np.expm1(st.log_frp_median_night))
        r = intensity_residual(normal_night, st, hour=20)
        assert r.z is not None and abs(r.z) < 0.5

    def test_night_spike_caught_by_split_stats(self):
        """A +1.0 log-unit night spike is obvious against the tight night MAD
        and muted against the bimodal global stats — the pre-fix blind spot."""
        st = _bimodal_state()
        assert st.log_frp_median_night is not None
        spike = float(np.expm1(st.log_frp_median_night + 1.0))
        r_split = intensity_residual(spike, st, hour=20)
        r_global = intensity_residual(spike, st)  # hour=None -> global stats
        assert r_split.z is not None and r_split.z > 3.5
        assert r_global.z is not None and r_global.z < r_split.z

    def test_day_hour_uses_day_stats(self):
        st = _bimodal_state()
        assert st.log_frp_median_day is not None
        normal_day = float(np.expm1(st.log_frp_median_day))
        r = intensity_residual(normal_day, st, hour=12)
        assert r.z is not None and abs(r.z) < 0.5
        # The same value scored against GLOBAL stats sits at the midpoint
        # between modes — a materially different (wrong) z.
        r_global = intensity_residual(normal_day, st)
        assert r.z is not None and r_global.z is not None
        assert abs(r_global.z) > abs(r.z) + 0.3

    def test_missing_split_stats_fall_back_to_global(self):
        """Cleared night stats -> global stats still score the row."""
        st = _state()
        st.log_frp_median_night = None
        st.log_frp_mad_night = None
        r = intensity_residual(50.0, st, hour=20)
        g = intensity_residual(50.0, st)
        assert r.z is not None and g.z is not None
        assert r.z == g.z
