"""SQLAlchemy 2.0 declarative models (Phase 0) with PostGIS geography.

Design invariants carried over from the V2 architecture doc:
- `Observation.raw_payload immutable evidence â€” never modified after acceptance.
- Unique (provider, provider_observation_key) => idempotent ingest replay.
- `ReviewEvent` rows are append-only and never mutated or deleted (audit trail).
- `Assessment` rows are versioned and never overwritten (provenance).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.types import Integer


class Base(DeclarativeBase):
    """Declarative base for all ThermoWatch v2 tables."""


class TimestampMixin:
    """created_at / updated_at with server-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )



        
class Observation(Base, TimestampMixin):
    """Immutable satellite thermal observation (raw payload preserved).

    Idempotency: unique (provider, provider_observation_key) â€” replaying the same
    FIRMS batch is a no-op thanks to ON CONFLICT DO NOTHING.
    """

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_observation_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Stable hash of provider identity fields",
    )

    # Temporal
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Spatial â€” Geography for accurate great-circle distance (ST_DWithin, metres)
    location = mapped_column(
        Geography(geometry_type="POINT", srid=4326),
        nullable=False,
        comment="PostGIS geography type",
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Sensor metadata
    sensor: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    scan: Mapped[float] = mapped_column(Float, nullable=False)
    track: Mapped[float] = mapped_column(Float, nullable=False)

    # Thermal properties
    brightness_ti4: Mapped[float | None] = mapped_column(Float, nullable=True)
    brightness_ti5: Mapped[float | None] = mapped_column(Float, nullable=True)
    frp: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Quality
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    day_night: Mapped[str] = mapped_column(String(8), nullable=False)
    quality_flags: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Processing state
    ingest_status: Mapped[str] = mapped_column(
        String(16), default="accepted", nullable=False, index=True
    )

    # Raw evidence (immutable after acceptance)
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="Original provider payload — never modified"
    )

    # Relationships
    incident_links: Mapped[list[IncidentObservation]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_observation_key", name="uq_observation_provider_key"
        ),
        Index("ix_observation_location", "location", postgresql_using="gist"),
        Index("ix_observation_provider_time", "provider", "observed_at"),
    )


class IncidentCandidate(Base, TimestampMixin):
    """Spatial-temporal grouping of related observations.

    `version` enables optimistic concurrency for review actions (409 on stale).
    """

    __tablename__ = "incident_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="Optimistic concurrency version"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="needs_review", nullable=False, index=True
    )

    # Spatial summary
    centroid_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Temporal summary
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Association metadata (versioned)
    association_rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    association_parameters: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    # Denormalized count of linked observations — the running-centroid update
    # is weighted by this count (migration 002).
    observation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )

    # Relationships
    observations: Mapped[list[IncidentObservation]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="incident", order_by="Assessment.assessed_at.desc()"
    )
    review_events: Mapped[list[ReviewEvent]] = relationship(
        back_populates="incident", order_by="ReviewEvent.occurred_at.desc()"
    )

    __table_args__ = (
        Index("ix_incident_status_last_seen", "status", "last_seen_at"),
        Index("ix_incident_first_seen", "first_seen_at"),
    )


class IncidentObservation(Base):
    """Association between observations and incident candidates.

    Stores the rationale for each link decision (distance, time delta, evidence).
    """

    __tablename__ = "incident_observations"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("observations.id", ondelete="CASCADE"),
        primary_key=True,
    )

    association_score: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Confidence in this association (0-1)"
    )
    association_method: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Algorithm version that made this link"
    )
    rationale: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        comment="Stored rationale: distance, time delta, evidence",
    )
    associated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    incident: Mapped[IncidentCandidate] = relationship(back_populates="observations")
    observation: Mapped[Observation] = relationship(back_populates="incident_links")


class Assessment(Base, TimestampMixin):
    """Versioned model assessment — never overwritten, always appended."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Versioning
    assessment_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normal_state_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_config_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # Outputs
    source_class_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    activity_state: Mapped[str] = mapped_column(String(32), nullable=False)
    residuals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    abstain_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Explainability
    evidence_quality: Mapped[dict] = mapped_column(JSONB, default=dict)
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    incident: Mapped[IncidentCandidate] = relationship(back_populates="assessments")


class OutboxEvent(Base):
    """Durable notification record. Written in the SAME transaction as the
    state change it describes (transactional outbox pattern). The publisher
    drains unpublished rows after commit; consumers dedupe by id.
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(16), default="1", nullable=False, server_default="1"
    )
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "committed_at",
            unique=False,
            postgresql_where=sa_text("published_at IS NULL"),
        ),
    )


class ReviewEvent(Base):
    """Append-only analyst review event — the audit trail. Never updated/deleted."""

    __tablename__ = "review_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Concurrency + idempotency
    expected_incident_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_incident_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )

    # Relationships
    incident: Mapped[IncidentCandidate] = relationship(back_populates="review_events")


class ContextRecord(Base, TimestampMixin):
    """Cached external context (OSM, weather, news) with TTL."""

    __tablename__ = "context_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="osm | weather | news | optical"
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="Provider, query, response metadata"
    )

    __table_args__ = (Index("ix_context_provider_expiry", "provider", "expires_at"),)


class ProcessingJob(Base, TimestampMixin):
    """Idempotent processing job tracking for workers."""

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class QuarantinedRecord(Base, TimestampMixin):
    """Malformed observations that failed validation, with the reason."""

    __tablename__ = "quarantined_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    error_reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

