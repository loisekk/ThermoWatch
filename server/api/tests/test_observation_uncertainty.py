"""Shared observation-uncertainty model: pixel physics used by BOTH sides.

These are the plan's Part 9 assertions plus the generator-side contract test
that pins the diagnosed failure mechanism: the pre-fix generator divided a
KILOMETRE scan value by 4 and added it as DEGREES, scattering a fixed source
across 4-22 km.
"""
import numpy as np
import pytest

from app.ml.observation_uncertainty import (
    KM_PER_DEG_LAT,
    combined_tolerance_km,
    jitter_position,
    jitter_sigma_km,
    km_to_deg_lat,
    km_to_deg_lon,
    observation_radius_km,
    pixel_half_extent_km,
)


def test_pixel_radius_orders_of_magnitude():
    # VIIRS ~0.4-1.1 km; MODIS ~0.7-1.7 km — never tens of km (the old bug)
    assert 0.1 < observation_radius_km(0.4, 0.4) < 0.7
    assert 0.5 < observation_radius_km(2.0, 2.0) < 1.8


def test_jitter_sigma_bounded_by_pixel():
    assert jitter_sigma_km(2.0) < 2.0 / 2  # sigma < half-extent, always
    assert jitter_sigma_km(0.4) == pytest.approx(0.2 / np.sqrt(12.0))


def test_combined_tolerance_monotonic():
    assert (combined_tolerance_km(1.0, 2.0, 2.0, 1.0)
            > combined_tolerance_km(1.0, 0.4, 0.4, 1.0))
    # Zone extent and margin add linearly; a missing pixel never collapses it.
    assert combined_tolerance_km(1.0, 0.4, 0.4, 1.5) == pytest.approx(
        1.0 + observation_radius_km(0.4, 0.4) + 1.5
    )


def test_half_extent_and_km_helpers():
    assert pixel_half_extent_km(2.0, 1.0) == (1.0, 0.5)
    assert km_to_deg_lat(KM_PER_DEG_LAT) == pytest.approx(1.0)
    # Longitude degrees shrink with latitude; cos-clamped near the poles.
    assert km_to_deg_lon(10.0, 0.0) == pytest.approx(km_to_deg_lat(10.0))
    assert km_to_deg_lon(10.0, 60.0) > km_to_deg_lon(10.0, 0.0)
    assert km_to_deg_lon(10.0, 89.9) < 0.5  # clamp keeps it finite and sane


def test_bad_pixel_values_fall_back_conservatively():
    """Missing/absurd scan-track must not produce a zero-radius gate."""
    assert observation_radius_km(float("nan"), 0.4) == pytest.approx(
        observation_radius_km(0.4, 0.4)
    )
    assert observation_radius_km(0.0, -1.0) == pytest.approx(
        observation_radius_km(0.4, 0.4)
    )


def test_jitter_position_stays_inside_footprint():
    """The sampled point is the source plus, at most, a few pixel half-extents."""
    rng = np.random.default_rng(0)
    lat, lon = 22.47, 70.07
    scan, track = 2.0, 2.0
    half_km = max(pixel_half_extent_km(scan, track))
    # 6 sigma (uniform-bounded; normal tail is generous) must still be small
    limit_deg = km_to_deg_lat(6 * jitter_sigma_km(scan)) + km_to_deg_lat(half_km)
    for _ in range(200):
        jlat, jlon = jitter_position(lat, lon, scan, track, rng)
        assert abs(jlat - lat) <= limit_deg
        assert abs(jlon - lon) <= km_to_deg_lon(half_km * 7, lat)


def test_generator_scatter_is_bounded_by_pixel_footprint():
    """The diagnosed mechanism, end to end: facility detections sit within the
    pixel footprint of their own facility — NOT kilometres away (pre-fix the
    jitter reached 22 km because km was used as degrees)."""
    from app.research.dataset import FACILITY_REGISTRY, generate_synthetic_dataset

    df = generate_synthetic_dataset(
        n_days=30, n_natural_fires=0, n_agri_burns=0, seed=3,
        inject_anomalies=False,
    )
    fac = {f.facility_id: f for f in FACILITY_REGISTRY}
    for fid, grp in df[df["facility_id"] != ""].groupby("facility_id"):
        f = fac[str(fid)]
        dlat_km = (grp["latitude"].to_numpy() - f.latitude) * KM_PER_DEG_LAT
        dlon_km = ((grp["longitude"].to_numpy() - f.longitude)
                   * KM_PER_DEG_LAT * np.cos(np.radians(f.latitude)))
        worst = float(np.max(np.hypot(dlat_km, dlon_km)))
        assert worst < 2.0, (
            f"{fid} detections scatter {worst:.1f} km from the source — "
            "generator is not using the shared pixel model"
        )
