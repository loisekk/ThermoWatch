"""Initial schema: observations, incidents, assessments, reviews, context, jobs,
quarantine. Includes PostGIS extension + geography column + GiST spatial index.

Revision ID: 001_initial
Revises: None
"""
from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_observation_key", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("sensor", sa.String(32), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("scan", sa.Float, nullable=False),
        sa.Column("track", sa.Float, nullable=False),
        sa.Column("brightness_ti4", sa.Float, nullable=True),
        sa.Column("brightness_ti5", sa.Float, nullable=True),
        sa.Column("frp", sa.Float, nullable=True),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("day_night", sa.String(8), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB, server_default="{}"),
        sa.Column("ingest_status", sa.String(16), nullable=False, server_default="accepted"),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider", "provider_observation_key", name="uq_observation_provider_key"
        ),
    )
    op.create_index("ix_observation_observed_at", "observations", ["observed_at"])
    op.create_index(
        "ix_observation_location", "observations", ["location"], postgresql_using="gist"
    )
    op.create_index("ix_observation_ingest_status", "observations", ["ingest_status"])
    op.create_index(
        "ix_observation_provider_time", "observations", ["provider", "observed_at"]
    )

    op.create_table(
        "incident_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="needs_review"),
        sa.Column("centroid_latitude", sa.Float, nullable=False),
        sa.Column("centroid_longitude", sa.Float, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("association_rule_version", sa.String(64), nullable=False),
        sa.Column("association_parameters", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_incident_status_last_seen", "incident_candidates", ["status", "last_seen_at"]
    )
    op.create_index("ix_incident_first_seen", "incident_candidates", ["first_seen_at"])

    op.create_table(
        "incident_observations",
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("association_score", sa.Float, nullable=False),
        sa.Column("association_method", sa.String(64), nullable=False),
        sa.Column("rationale", postgresql.JSONB, server_default="{}"),
        sa.Column("associated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assessed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("assessment_version", sa.String(64), nullable=False),
        sa.Column("normal_state_version", sa.String(64), nullable=True),
        sa.Column("feature_schema_version", sa.String(64), nullable=False),
        sa.Column("model_config_version", sa.String(64), nullable=False),
        sa.Column("source_class_scores", postgresql.JSONB, nullable=False),
        sa.Column("activity_state", sa.String(32), nullable=False),
        sa.Column("residuals", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("abstain_reason", sa.Text, nullable=True),
        sa.Column("evidence_quality", postgresql.JSONB, server_default="{}"),
        sa.Column("explanation", postgresql.JSONB, server_default="{}"),
        sa.Column("dataset_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assessment_incident", "assessments", ["incident_id"])

    op.create_table(
        "review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expected_incident_version", sa.Integer, nullable=False),
        sa.Column("resulting_incident_version", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
    )
    op.create_index("ix_review_incident", "review_events", ["incident_id"])

    op.create_table(
        "context_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distance_m", sa.Float, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("provenance", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_context_provider_expiry", "context_records", ["provider", "expires_at"]
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("payload", postgresql.JSONB, server_default="{}"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "quarantined_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("error_reason", sa.Text, nullable=False),
        sa.Column("error_category", sa.String(64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_quarantine_category", "quarantined_records", ["error_category"])


def downgrade() -> None:
    op.drop_table("quarantined_records")
    op.drop_table("processing_jobs")
    op.drop_table("context_records")
    op.drop_table("review_events")
    op.drop_table("assessments")
    op.drop_table("incident_observations")
    op.drop_table("incident_candidates")
    op.drop_table("observations")
