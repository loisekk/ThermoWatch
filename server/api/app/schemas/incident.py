"""Incident candidate, assessment and review schemas (Phase 0 v2 API)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActivityState(StrEnum):
    """Temporal activity classification of an incident."""

    ACUTE = "acute"
    RECURRING = "recurring"
    PERSISTENT = "persistent"
    CHANGING = "changing"
    INSUFFICIENT_HISTORY = "insufficient_history"
    UNKNOWN = "unknown"


class AnalystDisposition(StrEnum):
    """Analyst review states."""

    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    ESCALATED = "escalated"
    DISMISSED = "dismissed"


class AssessmentStatus(StrEnum):
    """Overall model assessment output."""

    NORMAL = "normal"
    ABNORMAL = "abnormal"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SourceClassScores(BaseModel):
    """Probability distribution over source classes (10-way, mirrors CLASSES)."""

    refinery: float = Field(0.0, ge=0, le=1)
    steel: float = Field(0.0, ge=0, le=1)
    gas_flare: float = Field(0.0, ge=0, le=1)
    cement: float = Field(0.0, ge=0, le=1)
    smelter: float = Field(0.0, ge=0, le=1)
    waste_incineration: float = Field(0.0, ge=0, le=1)
    power_plant: float = Field(0.0, ge=0, le=1)
    chemical: float = Field(0.0, ge=0, le=1)
    unknown_industrial: float = Field(0.0, ge=0, le=1)
    natural_fire: float = Field(0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_probability_sum(self) -> SourceClassScores:
        """Soft-validate: scores should approximately sum to 1.0."""
        total = sum(
            [
                self.refinery, self.steel, self.gas_flare, self.cement,
                self.smelter, self.waste_incineration, self.power_plant,
                self.chemical, self.unknown_industrial, self.natural_fire,
            ]
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Class scores sum to {total:.3f}, expected ~1.0")
        return self


class ResidualScores(BaseModel):
    """Deviation from the facility-expected thermal state."""

    intensity_residual: float | None = Field(
        None, description="FRP deviation from expected (MAD units)"
    )
    spatial_novelty: float | None = Field(
        None, description="Distance from normal thermal zones (km)"
    )
    temporal_novelty: float | None = None
    topology_change: float | None = None


class EvidenceQuality(BaseModel):
    """Indicators of data completeness and reliability."""

    observation_count: int = Field(0, ge=0)
    temporal_coverage_days: float = Field(0.0, ge=0)
    facility_history_days: float | None = None
    weather_context_available: bool = False
    optical_corroboration_available: bool = False
    osm_context_available: bool = False
    missing_data_flags: list[str] = Field(default_factory=list)


class Assessment(BaseModel):
    """Versioned model assessment of an incident candidate (API shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    assessment_version: str
    normal_state_version: str | None = None
    assessed_at: datetime
    source_class_scores: dict[str, float]
    activity_state: ActivityState
    residuals: dict[str, Any] | None = None
    status: AssessmentStatus
    confidence: float | None = Field(None, ge=0, le=1)
    abstain_reason: str | None = None
    evidence_quality: dict[str, Any] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)
    feature_schema_version: str
    model_config_version: str
    dataset_version: str | None = None


class ReviewCreate(BaseModel):
    """Request schema for POST /v2/incidents/{id}/reviews.

    Optimistic concurrency: `expected_incident_version` must match the current
    incident version or the request is rejected with 409 Conflict.
    """

    actor_id: str = Field(..., min_length=1, max_length=64)
    action: AnalystDisposition
    note: str | None = Field(None, max_length=2000)
    expected_incident_version: int = Field(..., ge=1)
    idempotency_key: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def validate_note_policy(self) -> ReviewCreate:
        """Require a substantive note for ESCALATED and DISMISSED actions."""
        if self.action in (AnalystDisposition.ESCALATED, AnalystDisposition.DISMISSED):
            if not self.note or len(self.note.strip()) < 10:
                raise ValueError(
                    f"Note is required (min 10 chars) for {self.action.value}"
                )
        return self


class ReviewResponse(BaseModel):
    """Review event as returned by the API (append-only record)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    actor_id: str
    action: AnalystDisposition
    note: str | None = None
    occurred_at: datetime
    expected_incident_version: int
    resulting_incident_version: int


class IncidentResponse(BaseModel):
    """Incident candidate summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    status: AnalystDisposition
    centroid_latitude: float
    centroid_longitude: float
    first_seen_at: datetime
    last_seen_at: datetime
    association_rule_version: str
    association_parameters: dict[str, Any] = Field(default_factory=dict)
    observation_count: int = 0


class IncidentDetailResponse(IncidentResponse):
    """Incident with latest assessment + review trail."""

    current_assessment: Assessment | None = None
    review_events: list[ReviewResponse] = Field(default_factory=list)
    observation_ids: list[UUID] = Field(default_factory=list)


class IncidentListResponse(BaseModel):
    incidents: list[IncidentResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
