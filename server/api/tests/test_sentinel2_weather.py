"""Sentinel-2 optical parse + Open-Meteo weather parse tests (Phase 6).

Pure parse/score functions — no network, no DB.
"""
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services.sentinel2 import (
    CDSEAuthClient,
    _bbox_around,
    _parse_statistics_response,
    check_optical_corroboration,
)
from app.services.weather import WeatherContext, _parse_weather, weather_fire_risk_score


# ---------------------------------------------------------------------
# Open-Meteo weather parsing
# ---------------------------------------------------------------------
def _open_meteo_payload() -> dict:
    return {
        "hourly": {
            "time": ["2026-09-01T10:00", "2026-09-01T11:00",
                     "2026-09-01T12:00"],
            "temperature_2m": [31.0, 33.5, 35.0],
            "relative_humidity_2m": [40.0, 38.0, 36.0],
            "wind_speed_10m": [12.0, 15.0, 18.0],
            "wind_direction_10m": [270.0, 275.0, 280.0],
            "precipitation": [0.0, 0.0, 0.2],
            "cloud_cover": [10.0, 20.0, 30.0],
        }
    }


class TestParseWeather:
    def test_picks_exact_matching_hour(self):
        observed = datetime(2026, 9, 1, 11, 30, tzinfo=timezone.utc)
        wx = _parse_weather(_open_meteo_payload(), observed)
        assert wx.available is True
        assert wx.temperature_c == 33.5
        assert wx.humidity_pct == 38.0
        assert wx.wind_speed_kmh == 15.0
        assert wx.wind_direction_deg == 275.0
        assert wx.precipitation_mm == 0.0
        assert wx.cloud_cover_pct == 20.0

    def test_falls_back_to_previous_hour_for_out_of_range(self):
        # 23:00 is past the last listed hour (12:00) -> idx stays 0,
        # the documented "earliest hour as fallback" branch.
        observed = datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)
        wx = _parse_weather(_open_meteo_payload(), observed)
        assert wx.available is True
        assert wx.temperature_c == 31.0  # earliest hour (documented fallback)

    def test_empty_hourly_unavailable(self):
        wx = _parse_weather({"hourly": {"time": []}},
                            datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc))
        assert wx.available is False
        assert wx.error and "No hourly data" in wx.error

    def test_missing_hourly_key_unavailable(self):
        wx = _parse_weather({}, datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc))
        assert wx.available is False

    def test_bad_types_report_parse_error(self):
        wx = _parse_weather({"hourly": {"time": 123}},
                            datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc))
        assert wx.available is False
        assert wx.error and wx.error.startswith("Parse error")

    def test_missing_value_fields_become_none(self):
        payload = {"hourly": {"time": ["2026-09-01T11:00"],
                              "temperature_2m": [22.0]}}
        wx = _parse_weather(payload, datetime(2026, 9, 1, 11, 0,
                                              tzinfo=timezone.utc))
        assert wx.available is True
        assert wx.temperature_c == 22.0
        assert wx.humidity_pct is None


class TestFireRiskScore:
    def _wx(self, **kw) -> WeatherContext:
        base = dict(available=True, temperature_c=20.0, humidity_pct=50.0,
                    wind_speed_kmh=10.0, precipitation_mm=0.0)
        base.update(kw)
        return WeatherContext(**base)

    def test_unavailable_returns_none(self):
        assert weather_fire_risk_score(WeatherContext(available=False)) is None

    def test_score_bounds(self):
        score = weather_fire_risk_score(self._wx(
            temperature_c=45.0, humidity_pct=2.0, wind_speed_kmh=60.0))
        assert 0.0 <= score <= 1.0

    def test_hot_dry_windy_riskier_than_cool_wet_calm(self):
        extreme = weather_fire_risk_score(self._wx(
            temperature_c=42.0, humidity_pct=5.0, wind_speed_kmh=45.0,
            precipitation_mm=0.0))
        benign = weather_fire_risk_score(self._wx(
            temperature_c=10.0, humidity_pct=95.0, wind_speed_kmh=2.0,
            precipitation_mm=8.0))
        assert extreme > benign
        assert extreme > 0.7
        assert benign < 0.3



# ---------------------------------------------------------------------
# Sentinel-2 Statistics API parsing
# ---------------------------------------------------------------------
def _stats_payload(fire_sum: float = 50.0, fire_count: int = 1000,
                   data_mask_count: int = 1000) -> dict:
    return {
        "data": [{
            "from": "2026-09-01T10:00:00Z",
            "outputs": {
                "fire_stats": {"bands": {
                    "fire_pixel": {"stats": {
                        "validCount": fire_count, "sum": fire_sum}},
                    "swir_ratio": {"stats": {"mean": 1.42}},
                    "ndvi": {"stats": {"mean": 0.31}},
                }},
                "dataMask": {"stats": {"validCount": data_mask_count}},
            },
        }]
    }


class TestParseStatistics:
    def test_fire_pixels_parse_and_corroborate(self):
        opt = _parse_statistics_response(_stats_payload(fire_sum=50.0))
        assert opt.available is True
        assert opt.n_pixels == 1000
        assert opt.n_fire_pixels == 50
        assert opt.fire_pixel_ratio == 0.05
        assert opt.corroborates is True
        assert opt.scene_date is not None
        assert opt.mean_swir_ratio == 1.42

    def test_no_fire_pixels_does_not_corroborate(self):
        opt = _parse_statistics_response(_stats_payload(fire_sum=0.0))
        assert opt.available is True
        assert opt.n_fire_pixels == 0
        assert opt.corroborates is False

    def test_heavy_cloud_blocks_corroboration(self):
        # 900 of 1000 pixels masked out -> cloud 90% > s2_max_cloud_pct (40)
        opt = _parse_statistics_response(_stats_payload(
            fire_sum=50.0, fire_count=1000, data_mask_count=100))
        assert opt.available is True
        assert opt.n_fire_pixels > 0
        assert opt.corroborates is False
        assert opt.cloud_cover_pct == 90.0

    def test_empty_data_unavailable(self):
        opt = _parse_statistics_response({"data": []})
        assert opt.available is False
        assert opt.error and "No data" in opt.error

    def test_no_valid_scenes_unavailable(self):
        opt = _parse_statistics_response(
            {"data": [{"from": "2026-09-01T10:00:00Z", "outputs": {}}]})
        assert opt.available is False
        assert opt.error and "No valid scenes" in opt.error

    def test_bad_stats_report_parse_error(self):
        payload = _stats_payload()
        payload["data"][0]["outputs"]["fire_stats"]["bands"]["fire_pixel"] = \
            {"stats": {"validCount": "not-a-number", "sum": 1.0}}
        opt = _parse_statistics_response(payload)
        assert opt.available is False
        assert opt.error and opt.error.startswith("Parse error")


class TestOpticalHelpers:
    def test_bbox_is_well_formed_and_grows_with_radius(self):
        small = _bbox_around(22.47, 70.07, 500.0)
        large = _bbox_around(22.47, 70.07, 2000.0)
        assert len(small) == 4
        west, south, east, north = small
        assert west < east and south < north
        assert abs((west + east) / 2 - 70.07) < 1e-9
        assert abs((south + north) / 2 - 22.47) < 1e-9
        assert (large[2] - large[0]) > (east - west)

    @pytest.mark.asyncio
    async def test_token_none_without_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "cdse_client_id", None)
        monkeypatch.setattr(settings, "cdse_client_secret", None)
        token = await CDSEAuthClient().get_token()
        assert token is None

    @pytest.mark.asyncio
    async def test_corroboration_unavailable_without_credentials(self,
                                                                 monkeypatch):
        """Contract: no credentials -> available=False, never raises."""
        monkeypatch.setattr(settings, "cdse_client_id", "")
        monkeypatch.setattr(settings, "cdse_client_secret", "")
        opt = await check_optical_corroboration(
            22.47, 70.07, datetime(2026, 9, 1, tzinfo=timezone.utc))
        assert opt.available is False
        assert opt.error is not None