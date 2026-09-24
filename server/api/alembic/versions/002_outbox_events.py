"""Migration 002: transactional outbox + incident observation_count.

Revision ID: 002_outbox
Revises: 001_initial
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "002_outbox"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_type",
            sa.String(64),
            nullable=False,
            comment="incident.created | incident.updated | assessment.created",
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_version", sa.Integer, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1"),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index: the publisher scans only unpublished rows
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_events",
        ["committed_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    # Association bookkeeping: denormalized count used by the running-centroid
    # update (weighted by observation count).
    op.add_column(
        "incident_candidates",
        sa.Column(
            "observation_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("incident_candidates", "observation_count")
    op.drop_table("outbox_events")
