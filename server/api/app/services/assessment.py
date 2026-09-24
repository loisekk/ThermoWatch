"""Versioned assessment pipeline: source characterization + temporal activity
as SEPARATE outputs, plus residuals vs facility normal state, uncertainty and
explicit abstention. Every assessment row is append-only.

Assessment version = hash(schema + heuristic + rule versions + params) —
content-independent, so identical configs produce identical versions and
historical rows stay comparable.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Assessment,
    IncidentCandidate,
    IncidentObservation,
    Observation,
)
from app.ml.counterfactual import counterfactual_normality
from app.ml.evidence_fusion import FusionResult, fuse_evidence
from app.ml.normal_state import FacilityNormalState, build_facility_normal_state
from app.ml.residuals import (
    IntensityResidual,
    SpatialResidual,
    TemporalResidual,
    intensity_residual,
    spatial_residual,
    temporal_residual,
)
from app.ml.signatures import THERMAL_PROFILES, nearest_facility
from app.services.outbox import emit
from app.services.sentinel2 import OpticalCorroboration, check_optical_corroboration
from app.services.weather import (
    WeatherContext,
    get_weather_context,
    weather_fire_risk_score,
)

logger = logging.getLogger(__name__)

ASSESSMENT_SCHEMA_VERSION = "asmt-v1.0.0"
HEURISTIC_VERSION = "heuristic-v1.0.0"
ACTIVITY_RULE_VERSION = "activity-v0.1.0"
FEATURE_SCHEMA_VERSION = "fs-v1.0.0"

SOURCE_CLASSES = [
    "refinery", "steel", "gas_flare", "cement", "smelter",
    "waste_incineration", "power_plant", "chemical",
    "unknown_industrial", "natural_fire",
]

# Simple TTL cache for facility states (single-process POC).
_state_cache: dict[str, tuple[FacilityNormalState, float]] = {}


def assessment_version() -> str:
    """Content-independent version hash of the assessment configuration."""
    payload = {
        "schema": ASSESSMENT_SCHEMA_VERSION,
        "heuristic": HEURISTIC_VERSION,
        "activity": ACTIVITY_RULE_VERSION,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "abnormal_z": settings.abnormal_z,
        "new_zone_km": settings.abnormal_new_zone_km,
        "interval_z": settings.abnormal_interval_z,
        "abstain_min_obs": settings.abstain_min_obs,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------
# Source-classification heuristic (deterministic, versioned)
# ---------------------------------------------------------------------
def classify_source(
    median_log_frp: float, night_ratio: float, nearby_type: str | None
) -> dict[str, float]:
    """Gaussian log-likelihood of the incident's thermal signature under each
    class profile, plus a prior boost for a nearby facility's type."""
    scores: dict[str, float] = {}
    for cls, prof in THERMAL_PROFILES.items():
        z = (median_log_frp - prof["mu"]) / prof["sigma"]
        loglik = -0.5 * z * z - np.log(prof["sigma"])
        prior = 0.6 if (nearby_type and cls == nearby_type) else 0.0
        scores[cls] = float(loglik + prior)
    # softmax
    m = max(scores.values())
    exp = {k: float(np.exp(v - m)) for k, v in scores.items()}
    total = sum(exp.values())
    return {k: v / total for k, v in exp.items()}


# ---------------------------------------------------------------------
# Temporal activity classifier (rule-based, versioned)
# ---------------------------------------------------------------------
def classify_activity(
    observed_at_list: list[datetime], frp_list: list[float]
) -> tuple[str, str]:
    """Returns (ActivityState, rationale). Thresholds are part of the version."""
    n = len(observed_at_list)
    if n == 0:
        return "unknown", "no observations"
    times = sorted(observed_at_list)
    span_days = (times[-1] - times[0]).days
    dates = {t.date() for t in times}
    distinct_days = len(dates)

    if n < settings.abstain_min_obs or distinct_days < 2:
        return "insufficient_history", f"n={n}, distinct_days={distinct_days}"

    if span_days <= 3:
        return "acute", f"span={span_days}d <= 3d"

    day_seq = sorted(dates)
    gaps = np.diff(np.array([d.toordinal() for d in day_seq], dtype=float))
    if distinct_days >= 4 and gaps.mean() >= 1 and gaps.std() < 0.5 * gaps.mean():
        return "recurring", f"periodic gaps: mean={gaps.mean():.1f} std={gaps.std():.1f}"

    dpd = n / distinct_days
    if span_days >= 14 and dpd >= 0.5:
        return "persistent", f"span={span_days}d, {dpd:.1f} obs/active-day"

    # CHANGING: monotonic FRP trend over the incident
    if n >= 4:
        x = np.arange(n, dtype=float)
        y = np.log1p(np.clip(np.array(frp_list, dtype=float), 0, None))
        slope = float(np.polyfit(x, y, 1)[0]) if y.std() > 0 else 0.0
        if abs(slope) > 0.05:
            return "changing", f"frp log-slope={slope:.3f}/obs"

    if span_days >= 14:
        return "persistent", f"default: span={span_days}d dpd={dpd:.1f}"
    return "recurring", f"default: span={span_days}d dpd={dpd:.1f}"


# ---------------------------------------------------------------------
# Facility state (DB-backed, cached)
# ---------------------------------------------------------------------
async def get_facility_state(
    session: AsyncSession,
    facility_id: str,
    lat: float,
    lon: float,
    facility_type: str = "",
) -> FacilityNormalState | None:
    """Build (or fetch cached) the facility's normal state from history."""
    now = time.monotonic()
    cached = _state_cache.get(facility_id)
    if cached and (now - cached[1]) < settings.state_cache_ttl_s:
        return cached[0]

    floor = datetime.now(timezone.utc) - timedelta(days=settings.state_lookback_days)
    rows = (await session.execute(
        select(Observation)
        .where(
            Observation.observed_at >= floor,
            Observation.latitude.between(lat - 0.05, lat + 0.05),
            Observation.longitude.between(lon - 0.05, lon + 0.05),
        )
        .order_by(Observation.observed_at)
    )).scalars().all()

    if not rows:
        return None

    df = pd.DataFrame([{
        "latitude": r.latitude, "longitude": r.longitude,
        "frp": r.frp or 0.0, "observed_at": r.observed_at,
    } for r in rows])

    state = build_facility_normal_state(
        df, facility_id, facility_type,
        min_obs=settings.state_min_obs,
        min_days=settings.state_min_days,
        zone_eps_km=settings.state_zone_eps_km,
        zone_min_samples=settings.state_zone_min_samples,
    )
    _state_cache[facility_id] = (state, now)
    return state


# ---------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------
async def assess_incident(session: AsyncSession, incident_id) -> Assessment | None:
    """Build a versioned assessment for one incident (append-only)."""
    incident = await session.get(IncidentCandidate, incident_id)
    if not incident:
        return None

    links = (await session.execute(
        select(Observation)
        .join(IncidentObservation, IncidentObservation.observation_id == Observation.id)
        .where(IncidentObservation.incident_id == incident_id)
        .order_by(Observation.observed_at)
    )).scalars().all()

    if not links:
        return None

    frps = [float(o.frp or 0.0) for o in links]
    hours = [o.observed_at.hour for o in links]
    times = [o.observed_at for o in links]
    median_log_frp = float(np.median(np.log1p(np.clip(frps, 0, None))))
    night_ratio = float(np.mean([(h < 6 or h >= 18) for h in hours]))

    # --- Context: nearest facility (proximity recorded, never proof) ---
    fac, dist_km = nearest_facility(
        incident.centroid_latitude, incident.centroid_longitude
    )
    nearby_type = fac.facility_type if fac else None

    # --- Normal state ---
    state = None
    if fac:
        state = await get_facility_state(
            session, fac.facility_id, fac.latitude, fac.longitude,
            fac.facility_type,
        )

    # --- Source scores ---
    class_scores = classify_source(median_log_frp, night_ratio, nearby_type)
    top_class = max(class_scores, key=lambda cls: class_scores[cls])
    top_conf = class_scores[top_class]

    # --- Activity ---
    activity, act_rationale = classify_activity(times, frps)

    # --- Residuals (incident-level: median observation vs state) ---
    med_idx = int(np.argsort(frps)[len(frps) // 2])
    med_obs = links[med_idx]
    res_int: IntensityResidual | None = None
    res_spa: SpatialResidual | None = None
    res_tmp: TemporalResidual | None = None
    if state:
        res_int = intensity_residual(med_obs.frp or 0.0, state)
        res_spa = spatial_residual(
            med_obs.latitude, med_obs.longitude, state,
            settings.abnormal_new_zone_km,
        )
        res_tmp = temporal_residual(med_obs.observed_at.hour, None, state)

    # --- External evidence (optical + weather): best-effort, optional ---
    optical, weather = await _gather_external_evidence(incident, med_obs)

    # --- Counterfactual normality (E8): expected vs observed FRP ---
    cf = counterfactual_normality(
        observed_frp=med_obs.frp or 0.0,
        observed_hour=med_obs.observed_at.hour,
        state=state,
        temperature_c=weather.temperature_c if weather.available else None,
        wind_speed_kmh=weather.wind_speed_kmh if weather.available else None,
    )

    # --- Evidence fusion (E9): weighted multi-source abnormality score ---
    fusion = _apply_fusion(
        thermal_z=res_int.z if res_int else None,
        optical=optical,
        weather=weather,
        facility_dist_km=dist_km,
        facility_type_match=(fac.facility_type == top_class) if fac else None,
    )

    # --- Final status: abstention gates first (cold-start contract — state
    # before obs-count so the actionable reason surfaces), then fused
    # evidence decides abnormal vs normal; spatial novelty stays an
    # independent trigger; low top-class confidence -> needs_review. ---
    if state is None or not state.sufficient:
        reason = state.insufficient_reason if state is not None else "no facility"
        status = "insufficient_evidence"
        abstain_reason = f"facility normal state unavailable ({reason})"
        status_rationale = "abstain: no normal state to compare against"
    elif len(links) < settings.abstain_min_obs:
        status = "insufficient_evidence"
        abstain_reason = (
            f"only {len(links)} observation(s) linked "
            f"(need >={settings.abstain_min_obs})"
        )
        status_rationale = "abstain: too few observations"
    elif fusion.is_abnormal:
        status = "abnormal"
        abstain_reason = None
        status_rationale = (
            f"fused evidence {fusion.fused_score} > {fusion.threshold} "
            f"(dominant: {fusion.dominant_source})"
        )
    elif res_spa is not None and res_spa.is_new_zone:
        status = "abnormal"
        abstain_reason = None
        status_rationale = (
            f"detection {res_spa.nearest_zone_km:.2f} km from every known zone "
            f"> {settings.abnormal_new_zone_km} km"
        )
    elif top_conf < 0.4:
        status = "needs_review"
        abstain_reason = None
        status_rationale = (
            f"residuals normal but top-class confidence low ({top_conf:.2f})"
        )
    else:
        status = "normal"
        abstain_reason = None
        status_rationale = "fused evidence within normal envelope"

    # --- Evidence quality ---
    evidence = {
        "observation_count": len(links),
        "temporal_coverage_days": (times[-1] - times[0]).days,
        "facility_history_days": state.n_days if state else None,
        "facility_state_available": bool(state and state.sufficient),
        "nearest_facility": (
            {"id": fac.facility_id, "name": fac.name,
             "distance_km": round(dist_km, 3)} if fac else None
        ),
        "weather_context_available": weather.available,
        "optical_corroboration_available": optical.available,
        "optical_corroborates": optical.corroborates if optical.available else None,
        "weather_fire_risk": (
            weather_fire_risk_score(weather) if weather.available else None
        ),
        "missing_data_flags": (
            [] if state and state.sufficient else ["facility_normal_state"]
        ),
    }

    explanation = {
        "source_heuristic": {
            "median_log_frp": round(median_log_frp, 3),
            "night_ratio": round(night_ratio, 3),
            "nearby_facility_type": nearby_type,
            "note": "heuristic estimate - not verified truth",
        },
        "activity_rule": act_rationale,
        "status_rule": status_rationale,
        "residuals": {
            "intensity_z": (
                round(res_int.z, 3) if res_int and res_int.z is not None else None
            ),
            "frp_ratio": (
                round(res_int.frp_ratio, 3)
                if res_int and res_int.frp_ratio else None
            ),
            "nearest_zone_km": (
                round(res_spa.nearest_zone_km, 3)
                if res_spa and res_spa.nearest_zone_km is not None else None
            ),
            "is_new_zone": res_spa.is_new_zone if res_spa else None,
            "hour_surprise": (
                round(res_tmp.hour_surprise, 3)
                if res_tmp and res_tmp.hour_surprise is not None else None
            ),
        },
        "counterfactual": {
            "expected_frp": cf.expected_frp,
            "observed_frp": cf.observed_frp,
            "residual_z": cf.residual_z,
            "confidence": cf.confidence,
            "detail": cf.explanation,
        },
        "evidence_fusion": {
            "fused_score": fusion.fused_score,
            "fused_confidence": fusion.fused_confidence,
            "dominant_source": fusion.dominant_source,
            "detail": fusion.explanation,
            "sources": [
                {"name": s.name, "score": s.score, "weight": s.weight,
                 "confidence": s.confidence}
                for s in fusion.sources
            ],
        },
        "association_rule_version": incident.association_rule_version,
    }

    row = Assessment(
        incident_id=incident.id,
        assessment_version=assessment_version(),
        normal_state_version=state.version if state else None,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        model_config_version=HEURISTIC_VERSION,
        source_class_scores=class_scores,
        activity_state=activity,
        residuals=explanation["residuals"],
        status=status,
        confidence=(
            round(top_conf, 4) if status != "insufficient_evidence" else None
        ),
        abstain_reason=abstain_reason,
        evidence_quality=evidence,
        explanation=explanation,
    )
    session.add(row)
    incident.version += 1
    await emit(
        session, "assessment.created", "assessment", incident.id, incident.version,
        {"incident_id": str(incident.id), "status": status,
         "top_class": top_class},
    )
    return row


def _determine_status(
    n_obs: int,
    state: FacilityNormalState | None,
    res_int: IntensityResidual | None,
    res_spa: SpatialResidual | None,
    top_conf: float,
) -> tuple[str, str | None, str]:
    """Return (status, abstain_reason, rationale) with explicit abstention."""
    # Cold-start gate first: with no facility normal state, the obs-count
    # is not the actionable reason (test contract: "normal state unavailable").
    if state is None or not state.sufficient:
        reason = state.insufficient_reason if state is not None else "no facility"
        return (
            "insufficient_evidence",
            f"facility normal state unavailable ({reason})",
            "abstain: no normal state to compare against",
        )
    if n_obs < settings.abstain_min_obs:
        return (
            "insufficient_evidence",
            f"only {n_obs} observation(s) linked "
            f"(need >={settings.abstain_min_obs})",
            "abstain: too few observations",
        )
    if (
        res_int is not None
        and res_int.z is not None
        and abs(res_int.z) > settings.abnormal_z
    ):
        return (
            "abnormal", None,
            f"intensity |z|={abs(res_int.z):.2f} > {settings.abnormal_z}",
        )
    if res_spa is not None and res_spa.is_new_zone:
        return (
            "abnormal", None,
            f"detection {res_spa.nearest_zone_km:.2f} km from every known zone "
            f"> {settings.abnormal_new_zone_km} km",
        )
    if top_conf < 0.4:
        return (
            "needs_review", None,
            f"residuals normal but top-class confidence low ({top_conf:.2f})",
        )
    return "normal", None, "all residuals within normal envelope"


# ---------------------------------------------------------------------
# External evidence gathering + fusion helpers (Phase 6)
# ---------------------------------------------------------------------
async def _gather_external_evidence(
    incident: IncidentCandidate, obs: Observation,
) -> tuple[OpticalCorroboration, WeatherContext]:
    """Best-effort optical + weather context for one observation.

    Offline-safe contract: never raises — each source degrades to
    available=False so the assessment proceeds with whatever evidence
    exists (fusion drops missing sources by weight).

    Phase 7 kill switch: with settings.external_evidence_enabled False
    (TW_EXTERNAL_EVIDENCE_ENABLED=0) no outbound provider call is made at
    all and both sources report disabled_by_config — checked before any
    attribute access so (None, None) inputs stay safe.
    """
    if not settings.external_evidence_enabled:
        return (
            OpticalCorroboration(available=False, error="disabled_by_config"),
            WeatherContext(available=False, error="disabled_by_config"),
        )
    lat = obs.latitude if obs.latitude is not None else incident.centroid_latitude
    lon = obs.longitude if obs.longitude is not None else incident.centroid_longitude
    observed_at = obs.observed_at or datetime.now(timezone.utc)

    try:
        optical = await check_optical_corroboration(lat, lon, observed_at)
    except Exception as exc:  # noqa: BLE001 — external source must not block assessment
        optical = OpticalCorroboration(available=False, error=str(exc))

    try:
        weather = await get_weather_context(lat, lon, observed_at)
    except Exception as exc:  # noqa: BLE001 — external source must not block assessment
        weather = WeatherContext(available=False, error=str(exc))

    return optical, weather


def _apply_fusion(
    thermal_z: float | None,
    optical: OpticalCorroboration,
    weather: WeatherContext,
    facility_dist_km: float | None,
    facility_type_match: bool | None,
) -> FusionResult:
    """Map assessment context onto the weighted multi-source fusion model."""
    optical_ratio = optical.fire_pixel_ratio if optical.available else None
    weather_risk = weather_fire_risk_score(weather) if weather.available else None
    return fuse_evidence(
        thermal_z=thermal_z,
        optical_fire_ratio=optical_ratio,
        optical_available=optical.available,
        weather_risk=weather_risk,
        facility_proximity_km=facility_dist_km,
        facility_type_match=facility_type_match,
    )
