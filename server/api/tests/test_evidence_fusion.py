"""Evidence fusion tests (E9) — weighted multi-source abnormality scoring."""
from typing import TypedDict

from app.ml.evidence_fusion import fuse_evidence


class FusionArgs(TypedDict):
    thermal_z: float | None
    optical_fire_ratio: float | None
    optical_available: bool
    weather_risk: float | None
    facility_proximity_km: float | None
    facility_type_match: bool | None


class TestFusionAbstention:
    def test_no_evidence_abstains(self):
        result = fuse_evidence(
            thermal_z=None, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert result.fused_score == 0.0
        assert result.is_abnormal is False
        assert "abstaining" in result.explanation

    def test_zero_confidence_only_abstains(self):
        # Thermal present as a source but weight/confidence collapse to 0
        # because no facility state backs it AND nothing else is available.
        result = fuse_evidence(
            thermal_z=None, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert result.fused_confidence == 0.0
        assert any(s.name == "thermal_residual" for s in result.sources)


class TestFusionScoring:
    def test_strong_thermal_residual_is_abnormal(self):
        result = fuse_evidence(
            thermal_z=4.5, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert result.is_abnormal is True
        assert result.fused_score > result.threshold
        assert result.dominant_source == "thermal_residual"
        thermal = next(s for s in result.sources if s.name == "thermal_residual")
        assert thermal.score == 0.9  # min(4.5/5, 1)

    def test_normal_evidence_stays_normal(self):
        result = fuse_evidence(
            thermal_z=0.3, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=1.0,
            facility_type_match=True)
        assert result.is_abnormal is False
        assert result.fused_score < 0.2

    def test_unavailable_optical_dropped_even_with_ratio(self):
        result = fuse_evidence(
            thermal_z=1.0, optical_fire_ratio=0.9, optical_available=False,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert not any(s.name == "optical_corroboration" for s in result.sources)

    def test_optical_can_be_dominant(self):
        result = fuse_evidence(
            thermal_z=0.0, optical_fire_ratio=0.10, optical_available=True,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert result.dominant_source == "optical_corroboration"
        optical = next(s for s in result.sources if s.name == "optical_corroboration")
        assert optical.score == 1.0  # saturates at 5% fire pixel ratio

    def test_far_from_facility_scores_higher_context(self):
        near = fuse_evidence(
            thermal_z=1.0, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=1.0,
            facility_type_match=True)
        far = fuse_evidence(
            thermal_z=1.0, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=10.0,
            facility_type_match=None)
        ctx_near = next(s for s in near.sources if s.name == "facility_context")
        ctx_far = next(s for s in far.sources if s.name == "facility_context")
        assert ctx_near.score < ctx_far.score

    def test_fused_confidence_bounded_by_available_weight(self):
        result = fuse_evidence(
            thermal_z=2.0, optical_fire_ratio=None, optical_available=False,
            weather_risk=None, facility_proximity_km=None,
            facility_type_match=None)
        assert 0.0 < result.fused_confidence <= 1.0

    def test_custom_threshold_respected(self):
        args: FusionArgs = {
            "thermal_z": 2.0,
            "optical_fire_ratio": None,
            "optical_available": False,
            "weather_risk": None,
            "facility_proximity_km": None,
            "facility_type_match": None,
        }
        default = fuse_evidence(**args)
        strict = fuse_evidence(custom_threshold=0.3, **args)
        assert default.threshold == 0.5
        assert strict.threshold == 0.3
        assert default.is_abnormal is False   # score 0.4 < 0.5
        assert strict.is_abnormal is True     # score 0.4 > 0.3

    def test_explanation_names_dominant_source(self):
        result = fuse_evidence(
            thermal_z=3.0, optical_fire_ratio=None, optical_available=False,
            weather_risk=0.8, facility_proximity_km=8.0,
            facility_type_match=None)
        assert result.dominant_source in result.explanation
        assert "Fused score" in result.explanation