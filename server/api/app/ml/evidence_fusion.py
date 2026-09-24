"""Multi-source evidence fusion for abnormality assessment.

Combines:
- Thermal residuals (from facility normal state)
- Optical corroboration (Sentinel-2 fire pixels)
- Weather context (fire-risk score)
- Facility context (proximity, type match)

Each source has a weight and a confidence. Sources can be missing (weight=0).
The fused score is interpretable: we report which source contributed most.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class EvidenceSource:
    """One piece of evidence with its weight and confidence."""
    name: str
    score: float            # 0=normal, 1=abnormal/confirming
    weight: float           # relative importance
    confidence: float       # 0-1, how reliable this source is
    detail: str = ""


@dataclass(frozen=True)
class FusionResult:
    """Combined abnormality assessment from all evidence."""
    fused_score: float          # 0=normal, 1=abnormal
    fused_confidence: float     # 0-1
    threshold: float            # abnormal if fused_score > threshold
    is_abnormal: bool
    dominant_source: str        # which evidence contributed most
    sources: list[EvidenceSource]
    explanation: str


def fuse_evidence(
    thermal_z: float | None,
    optical_fire_ratio: float | None,
    optical_available: bool,
    weather_risk: float | None,
    facility_proximity_km: float | None,
    facility_type_match: bool | None,
    custom_threshold: float | None = None,
) -> FusionResult:
    """Combine all evidence sources into a single abnormality score.

    Each source contributes: weight x confidence x score.
    Missing sources are excluded (weight redistributed to available ones).
    """
    sources: list[EvidenceSource] = []
    w_thermal = settings.fusion_thermal_weight
    w_optical = settings.fusion_optical_weight
    w_weather = settings.fusion_weather_weight
    w_context = settings.fusion_context_weight

    # --- Thermal residual evidence ---
    if thermal_z is not None:
        # Map |z| to [0, 1]: 0 at z=0, 1 at |z|>=5
        thermal_score = min(abs(thermal_z) / 5.0, 1.0)
        thermal_conf = 0.9  # residuals are fairly reliable when available
        sources.append(EvidenceSource(
            name="thermal_residual", score=round(thermal_score, 4),
            weight=w_thermal, confidence=thermal_conf,
            detail=f"intensity z={thermal_z:.2f}"))
    elif thermal_z is None:
        # Missing thermal is itself a signal of low evidence
        sources.append(EvidenceSource(
            name="thermal_residual", score=0.0, weight=0.0, confidence=0.0,
            detail="no facility normal state available"))

    # --- Optical evidence ---
    if optical_available and optical_fire_ratio is not None:
        # Fire pixel ratio: 0 = no fire, >0.01 = significant fire signature
        optical_score = min(optical_fire_ratio / 0.05, 1.0)  # saturate at 5%
        optical_conf = 0.8
        sources.append(EvidenceSource(
            name="optical_corroboration", score=round(optical_score, 4),
            weight=w_optical, confidence=optical_conf,
            detail=f"fire_pixel_ratio={optical_fire_ratio:.4f}"))

    # --- Weather evidence ---
    if weather_risk is not None:
        # High fire-risk weather supports abnormal interpretation
        weather_conf = 0.6  # weather is context, not direct evidence
        sources.append(EvidenceSource(
            name="weather_context", score=round(weather_risk, 4),
            weight=w_weather, confidence=weather_conf,
            detail=f"fire_risk={weather_risk:.3f}"))

    # --- Facility context evidence ---
    if facility_proximity_km is not None:
        # Very close to a known facility + type match = likely persistent source
        # Far from any facility = more likely wildfire (abnormal here)
        if facility_proximity_km < 2.0 and facility_type_match:
            context_score = 0.1  # close to expected facility = probably normal
        elif facility_proximity_km < 5.0:
            context_score = 0.3
        else:
            context_score = 0.7  # far from any facility = unusual
        context_conf = 0.5
        sources.append(EvidenceSource(
            name="facility_context", score=round(context_score, 4),
            weight=w_context, confidence=context_conf,
            detail=f"distance={facility_proximity_km:.1f}km, type_match={facility_type_match}"))

    # --- Fusion ---
    if not sources:
        return FusionResult(
            fused_score=0.0, fused_confidence=0.0, threshold=0.5,
            is_abnormal=False, dominant_source="none", sources=[],
            explanation="No evidence available — abstaining")

    # Weighted average with confidence weighting:
    # contribution = weight * confidence * score; missing sources drop out
    # of the denominator entirely (weight redistributed to available ones).
    total_weight = sum(s.weight * s.confidence for s in sources)
    if total_weight == 0:
        # Candidate sources exist but none carries usable confidence
        # (e.g. no facility normal state and nothing else available).
        return FusionResult(
            fused_score=0.0, fused_confidence=0.0, threshold=0.5,
            is_abnormal=False, dominant_source="none", sources=sources,
            explanation="No evidence with usable confidence — abstaining "
                        "(all sources missing or zero-confidence)")

    weighted_sum = sum(s.weight * s.confidence * s.score for s in sources)
    fused_score = weighted_sum / total_weight
    fused_confidence = total_weight / (w_thermal + w_optical + w_weather + w_context)

    # Dominant source: highest contribution
    contributions = {s.name: s.weight * s.confidence * s.score for s in sources}
    dominant = max(contributions, key=lambda name: contributions[name]) if contributions else "none"

    threshold = custom_threshold or 0.5
    is_abnormal = fused_score > threshold

    # Explanation
    parts = []
    for s in sorted(sources, key=lambda x: -x.weight * x.confidence):
        if s.confidence > 0:
            parts.append(f"{s.name}={s.score:.2f} (w={s.weight:.2f}, c={s.confidence:.1f})")
    explanation = (
        f"Fused score {fused_score:.3f} (threshold {threshold}). "
        f"Dominant: {dominant}. " + "; ".join(parts[:3])
    )

    return FusionResult(
        fused_score=round(fused_score, 4),
        fused_confidence=round(fused_confidence, 3),
        threshold=threshold,
        is_abnormal=is_abnormal,
        dominant_source=dominant,
        sources=sources,
        explanation=explanation,
    )