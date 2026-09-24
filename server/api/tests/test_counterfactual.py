"""Counterfactual normality tests (E8) — expected vs observed FRP."""
import numpy as np
import pandas as pd

from app.ml.counterfactual import counterfactual_normality
from app.ml.normal_state import build_facility_normal_state


def _state_df(n: int = 96, days: int = 30, seed: int = 7,
              hours: list[int] | None = None) -> pd.DataFrame:
    """Facility history. Hours round-robin by default so the hour histogram
    is exactly flat (Laplace-smoothed -> 1/24 per hour) and the hour
    adjustment cancels for a median-FRP observation."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-06-01", tz="UTC")
    rows = []
    for i in range(n):
        hour = hours[i % len(hours)] if hours is not None else i % 24
        day = start + pd.Timedelta(days=i * days // max(n, 1))
        rows.append({
            "latitude": 22.47 + rng.normal(0, 0.002),
            "longitude": 70.07 + rng.normal(0, 0.002),
            "frp": float(np.exp(rng.normal(3.4, 0.4))),
            "observed_at": day + pd.Timedelta(hours=int(hour),
                                               minutes=int(rng.integers(0, 60))),
        })
    return pd.DataFrame(rows)


def _sufficient_state(**kw) -> "object":
    state = build_facility_normal_state(_state_df(**kw), "F-001", "refinery")
    assert state.sufficient
    return state


class TestGuards:
    def test_none_state_returns_zero_confidence(self):
        cf = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                      state=None)
        assert cf.expected_frp is None
        assert cf.residual_z is None
        assert cf.confidence == 0.0
        assert "Insufficient" in cf.explanation

    def test_insufficient_state_returns_zero_confidence(self):
        state = build_facility_normal_state(_state_df(n=5, days=3),
                                            "F-001", "refinery")
        assert not state.sufficient
        cf = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                      state=state)
        assert cf.expected_frp is None
        assert cf.confidence == 0.0


class TestNormalFrp:
    def test_normal_frp_low_residual(self):
        """Median FRP at a normal hour -> near-zero residual (flat histogram
        fixture: round-robin hours cancel the hour adjustment)."""
        state = _sufficient_state()
        median_frp = float(np.expm1(state.log_frp_median))
        cf = counterfactual_normality(observed_frp=median_frp,
                                      observed_hour=13, state=state)
        assert cf.expected_frp is not None
        assert abs(cf.residual_z) < 0.5
        assert abs(cf.residual_frp) < 0.1 * median_frp + 1.0
        assert abs(cf.hour_adjustment) < 0.01  # flat hour histogram
        assert cf.confidence > 0.0

    def test_extreme_frp_high_residual(self):
        state = _sufficient_state()
        extreme_frp = float(np.expm1(state.log_frp_median + 6.0))
        cf = counterfactual_normality(observed_frp=extreme_frp,
                                      observed_hour=13, state=state)
        assert cf.residual_z is not None and cf.residual_z > 5.0
        assert cf.residual_frp > 0


class TestHourAndWeatherEffects:
    def test_unusual_hour_shifts_expectation(self):
        # Facility only active hours 0-5: hour 14 is off-peak -> negative adj
        state = _sufficient_state(hours=[0, 1, 2, 3, 4, 5])
        cf_off = counterfactual_normality(observed_frp=30.0, observed_hour=14,
                                          state=state)
        cf_on = counterfactual_normality(observed_frp=30.0, observed_hour=2,
                                         state=state)
        assert cf_off.hour_adjustment is not None
        assert cf_off.hour_adjustment < -0.1
        assert cf_on.hour_adjustment > 0.1
        assert cf_off.expected_frp < cf_on.expected_frp

    def test_hot_weather_raises_expectation(self):
        state = _sufficient_state()
        base = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                        state=state)
        hot = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                       state=state, temperature_c=40.0)
        assert hot.weather_adjustment is not None
        assert hot.weather_adjustment > 0
        assert hot.expected_frp > base.expected_frp
        assert -0.3 <= hot.weather_adjustment <= 0.3

    def test_wind_lowers_expectation(self):
        state = _sufficient_state()
        windy = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                         state=state, wind_speed_kmh=30.0)
        assert windy.weather_adjustment is not None
        assert windy.weather_adjustment < 0

    def test_confidence_bounded(self):
        state = _sufficient_state()
        cf = counterfactual_normality(observed_frp=30.0, observed_hour=12,
                                      state=state, temperature_c=25.0)
        assert 0.0 <= cf.confidence <= 1.0
        # With weather available confidence >= the no-weather case
        no_weather = counterfactual_normality(observed_frp=30.0,
                                              observed_hour=12, state=state)
        assert cf.confidence >= no_weather.confidence