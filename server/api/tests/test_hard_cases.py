"""Hard-case repairs: H4 detectability, H6/H7 rows, arm attribution.

Mechanism under test (plan Parts 6-8):
  * H4 displacement is a physically detectable 1.5-4 km move, not a sub-pixel
    shift no sensor could resolve;
  * H6/H7 exist as real tagged ROWS (natural / agricultural fire ~3 km from a
    facility) that keep their own land cover and never inherit the facility's
    type through the B1 ``near_*`` one-hots;
  * the detector reports WHICH arm fired, so a gate move can be attributed.
"""
import numpy as np
import pandas as pd
import pytest

from app.ml.normal_state import build_facility_normal_state
from app.research import e10_hard_cases as e10
from app.research.dataset import FACILITY_REGISTRY
from app.research.hard_cases import generate_hard_case_dataset
from tests.test_normal_state import _facility_df


@pytest.fixture(scope="module")
def hard_df() -> pd.DataFrame:
    """One 30-day hard-case dataset shared by the generator tests."""
    return generate_hard_case_dataset(seed=7, n_days=30)


def _km_per_deg_lon(lat: float) -> float:
    return 111.32 * np.cos(np.radians(lat))


class TestDisplacementDetectability:
    def test_h4_shifts_are_kilometres_not_subpixel(self, hard_df):
        """Every displaced row sits 1.5-4 km per axis from its facility —
        a move both VIIRS and MODIS can actually resolve.
        Taking into account initial subpixel jitter around facility centroid
        (-0.8 to +0.8 km), the distance from facility centroid is between 0.8 and 4.8 km."""
        fac = {f.facility_id: f for f in FACILITY_REGISTRY}
        displaced = hard_df[hard_df["hard_case_id"] == "H4_displacement"]
        assert len(displaced) > 0
        for fid, grp in displaced.groupby("facility_id"):
            f = fac[str(fid)]
            dlat = (grp["latitude"] - f.latitude).abs() * 111.32
            dlon = (grp["longitude"] - f.longitude).abs() * _km_per_deg_lon(f.latitude)
            assert (dlat >= 0.8).all() and (dlat <= 4.8).all()
            assert (dlon >= 0.8).all() and (dlon <= 4.8).all()


class TestH6H7Rows:
    def test_rows_exist_tagged_and_natural(self, hard_df):
        for tag, landcover in (("H6_natural_near_facility", "forest"),
                               ("H7_agri_near_facility", "agriculture")):
            rows = hard_df[hard_df["hard_case_id"] == tag]
            assert len(rows) == 27, f"{tag}: 3 facilities x 3 days x 3 rows"
            assert (rows["landcover"] == landcover).all()
            assert rows["is_natural_fire"].astype(bool).all()
            assert (rows["label_source_class"] == "natural_fire").all()
            assert (rows["label_normality"] == "normal").all()
            # The row itself never carries the facility's type
            assert rows["facility_type"].astype(str).eq("").all()

    def test_rows_are_about_three_km_from_their_facility(self, hard_df):
        fac = {f.facility_id: f for f in FACILITY_REGISTRY}
        rows = hard_df[hard_df["hard_case_id"].isin(
            ["H6_natural_near_facility", "H7_agri_near_facility"])]
        for fid, grp in rows.groupby("facility_id"):
            f = fac[str(fid)]
            dlat = (grp["latitude"] - f.latitude) * 111.32
            dlon = (grp["longitude"] - f.longitude) * _km_per_deg_lon(f.latitude)
            d = np.hypot(dlat, dlon)
            assert d.min() > 2.0, "must be outside the 2 km association radius"
            assert d.max() < 6.0, "must still be in the facility's influence area"

    def test_rows_land_after_the_e10_cutoff(self, hard_df):
        """H6/H7 must be SCORED, never trained on: placed after the 60%
        temporal cutoff the E10 harness uses."""
        history, _eval_all, cutoff = e10._split_history(hard_df)
        rows = hard_df[hard_df["hard_case_id"].isin(
            ["H6_natural_near_facility", "H7_agri_near_facility"])]
        assert (rows["observed_at"] >= cutoff).all()
        assert rows["observed_at"].min() > history["observed_at"].max()

    def test_h8_does_not_relabel_natural_rows(self, hard_df):
        h8 = hard_df[hard_df["hard_case_id"] == "H8_overlapping"]
        assert len(h8) > 0  # coverage scenario stays non-degenerate
        assert not h8["is_natural_fire"].astype(bool).any()

    def test_feature_audit_reports_no_facility_type_inheritance(self, hard_df):
        """The Part 7 mechanism, measured: a wildfire 3 km from a refinery must
        NOT get near_refinery=1, so the natural-fire rate is 1.0."""
        rows = hard_df[hard_df["hard_case_id"].isin(
            ["H6_natural_near_facility", "H7_agri_near_facility"])]
        audit = e10._natural_fire_feature_audit(rows)
        assert audit["n_rows"] == len(rows)
        assert audit["facility_type_inheritance_rate"] == 0.0
        assert audit["natural_fire_rate"] == 1.0
        assert audit["n_near_facility_within_2km"] == 0



class TestArmAttribution:
    """The detector must say WHICH arm fired (mechanism evidence)."""

    @pytest.fixture(scope="class")
    def state(self):
        return build_facility_normal_state(_facility_df(), "F-001", "refinery")

    def test_spike_attributes_to_intensity(self, state):
        spike = float(np.expm1(state.log_frp_median) * 6.0)
        flag, arm, z, _ = e10._rule_flag(
            spike, state.zones[0].centroid_lat, state.zones[0].centroid_lon, state,
            hour=12, scan_km=0.4, track_km=0.4,
            window=[state.log_frp_median] * 8,
        )
        assert flag and arm == "intensity"
        assert z is not None and abs(z) > 3.5

    def test_far_detection_attributes_to_spatial(self, state):
        flag, arm, _, _ = e10._rule_flag(
            float(np.expm1(state.log_frp_median)),
            state.zones[0].centroid_lat + 0.1, state.zones[0].centroid_lon, state,
            hour=12, scan_km=0.4, track_km=0.4,
            window=[state.log_frp_median] * 8,
        )
        assert flag and arm == "spatial_new_zone"

    def test_sustained_window_attributes_to_sustained_shift(self, state):
        """A normal-looking row whose LAST K observations drifted is the H5
        shape: intensity alone stays quiet, the sustained arm fires."""
        median = state.log_frp_median
        flag, arm, z, _ = e10._rule_flag(
            float(np.expm1(median)),
            state.zones[0].centroid_lat, state.zones[0].centroid_lon, state,
            hour=12, scan_km=0.4, track_km=0.4,
            window=[median + 0.9] * e10.SUSTAINED_WINDOW,
        )
        assert z is not None and abs(z) < 3.5  # intensity arm stays quiet
        assert flag and arm == "sustained_shift"

    def test_attribution_counts_sum_to_flags(self, state):
        rows = pd.DataFrame([{
            "hard_case_id": "t", "facility_id": "F-001",
            "observed_at": pd.Timestamp("2026-07-01 12:00", tz="UTC"),
            "label_normality": "normal",
            "frp": float(np.expm1(state.log_frp_median)),
            "latitude": state.zones[0].centroid_lat + 0.1,
            "longitude": state.zones[0].centroid_lon, "scan": 0.4, "track": 0.4,
        }])
        attr = e10._attribute_flags(rows, {"F-001": state})
        assert set(attr["caught_by_arm"]) == set(e10.DETECTOR_ARMS)
        assert attr["caught_by_arm"]["spatial_new_zone"] == 1
        assert sum(attr["caught_by_arm"].values()) == 1

    def test_rolling_windows_are_causal_and_position_keyed(self):
        """The window map is keyed by input position but built in time order,
        so records keep their caller's row order (final_gates pairs
        predictions to eval rows positionally)."""
        rows = pd.DataFrame([
            {"facility_id": "F-001", "frp": 10.0,
             "observed_at": pd.Timestamp("2026-07-03", tz="UTC")},
            {"facility_id": "F-001", "frp": 1.0,
             "observed_at": pd.Timestamp("2026-07-01", tz="UTC")},
            {"facility_id": "F-001", "frp": 5.0,
             "observed_at": pd.Timestamp("2026-07-02", tz="UTC")},
        ])
        windows = e10._rolling_windows(rows, {"F-001": [0.5] * 5})
        assert windows[0][-1] == pytest.approx(np.log1p(10.0))
        assert len(windows[0]) == e10.SUSTAINED_WINDOW
        assert windows[1][-1] == pytest.approx(np.log1p(1.0))
        assert windows[2][-1] == pytest.approx(np.log1p(5.0))
