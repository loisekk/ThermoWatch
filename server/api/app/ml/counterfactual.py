"""Counterfactual normality scoring: 'Would this FRP be expected at this
facility, at this hour, under this weather?'

Combines facility normal state with environmental context to produce
an expected-value prediction and a residual that's interpretable.

Core formulation from the V2 research plan section 9.1.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.ml.normal_state import FacilityNormalState
from app.ml.residuals import MAD_TO_SIGMA


@dataclass(frozen=True)
class CounterfactualResult:
    """Expected vs observed thermal behavior."""
    expected_frp: float | None       # what we'd predict under normal conditions
    observed_frp: float
    residual_frp: float | None       # observed - expected
    residual_z: float | None         # standardized residual (MAD-scaled)
    hour_adjustment: float | None    # how much hour-of-day shifted expectation
    weather_adjustment: float | None # how much weather shifted expectation
    confidence: float                # 0-1, based on state sufficiency + context availability
    explanation: str


def counterfactual_normality(
    observed_frp: float,
    observed_hour: int,
    state: FacilityNormalState | None,
    temperature_c: float | None = None,
    wind_speed_kmh: float | None = None,
) -> CounterfactualResult:
    """Predict expected FRP given facility history, hour, and weather.

    Model: expected_log_frp = state_median + hour_effect + weather_effect

    Hour effect: facilities with diurnal patterns show lower FRP during
    their "off-peak" hours. We model this as a multiplicative factor
    derived from the hour histogram.

    Weather effect: high temperature + wind can increase apparent thermal
    signature; precipitation suppresses it. Modeled as a small additive
    adjustment in log space.
    """
    if state is None or not state.sufficient or state.log_frp_median is None:
        return CounterfactualResult(
            expected_frp=None, observed_frp=observed_frp,
            residual_frp=None, residual_z=None,
            hour_adjustment=None, weather_adjustment=None,
            confidence=0.0,
            explanation="Insufficient facility history for counterfactual prediction",
        )

    log_frp = float(np.log1p(max(observed_frp, 0.0)))

    # --- Hour adjustment ---
    # If this hour is unusual for the facility, expected FRP differs from median.
    # We use the hour histogram as a proxy for activity level.
    hour_prob = state.hour_probability(observed_hour)
    # Normalize: uniform probability = 1/24, higher = more active at this hour
    activity_factor = hour_prob * 24.0  # >1 = more active than average, <1 = less
    # Cap the adjustment to ±0.5 in log space
    hour_adj = float(np.clip(np.log(max(activity_factor, 0.1)), -0.5, 0.5))

    # --- Weather adjustment ---
    weather_adj = 0.0
    if temperature_c is not None:
        # High ambient temp slightly increases thermal signature
        temp_deviation = (temperature_c - 25.0) / 30.0  # normalized around 25°C
        weather_adj += 0.1 * temp_deviation
    if wind_speed_kmh is not None:
        # Wind can disperse or concentrate heat plumes (small effect)
        wind_factor = min(wind_speed_kmh / 30.0, 1.0)
        weather_adj -= 0.05 * wind_factor
    weather_adj = float(np.clip(weather_adj, -0.3, 0.3))

    # --- Expected value ---
    expected_log_frp = state.log_frp_median + hour_adj + weather_adj
    expected_frp = float(np.expm1(expected_log_frp))

    # --- Residual ---
    residual_log = log_frp - expected_log_frp
    residual_frp = observed_frp - expected_frp
    mad = state.log_frp_mad
    residual_z = (
        residual_log / (MAD_TO_SIGMA * mad)
        if mad is not None and mad > 0
        else None
    )

    # --- Confidence ---
    # Higher with more observations, longer history, and weather availability
    obs_conf = min(state.n_observations / 100.0, 1.0)
    days_conf = min(state.n_days / 60.0, 1.0)
    weather_conf = 1.0 if temperature_c is not None else 0.7
    confidence = round(0.4 * obs_conf + 0.3 * days_conf + 0.3 * weather_conf, 3)

    # --- Explanation ---
    parts = []
    if abs(hour_adj) > 0.1:
        parts.append(f"hour effect {'+' if hour_adj > 0 else ''}{hour_adj:.2f} in log space")
    if abs(weather_adj) > 0.05:
        parts.append(f"weather effect {'+' if weather_adj > 0 else ''}{weather_adj:.2f}")
    if not parts:
        parts.append("expected matches facility median")
    explanation = (
        f"Expected FRP {expected_frp:.1f} MW (observed {observed_frp:.1f} MW). "
        f"Residual z={f'{residual_z:.2f}' if residual_z is not None else 'unavailable'}. "
        + "; ".join(parts) + "."
    )

    return CounterfactualResult(
        expected_frp=round(expected_frp, 2),
        observed_frp=round(observed_frp, 2),
        residual_frp=round(residual_frp, 2),
        residual_z=round(residual_z, 3) if residual_z is not None else None,
        hour_adjustment=round(hour_adj, 3),
        weather_adjustment=round(weather_adj, 3),
        confidence=confidence,
        explanation=explanation,
    )