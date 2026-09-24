"""Idempotent observation ingestion (Phase 0).

Key properties:
- Per-row validation: a malformed FIRMS row is quarantined with the reason, never
  allowed to block the rest of the batch.
- Stable identity: compute_observation_key hashes provider identity fields, so
  replaying the same FIRMS data produces the same key.
- ON CONFLICT DO NOTHING on (provider, provider_observation_key) makes replay a
  no-op: duplicates counted, nothing double-inserted.
- raw_payload stores the original provider row verbatim (immutable evidence).
"""
from __future__ import annotations

import structlog
from geoalchemy2 import WKTElement
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Observation, QuarantinedRecord
from app.schemas.observation import (
    FIRMSObservationRaw,
    IngestResult,
    ObservationNormalized,
    normalize_observation,
)

logger = structlog.get_logger(__name__)


def validate_row(row: dict) -> tuple[FIRMSObservationRaw | None, str | None]:
    """Validate one raw provider row. Returns (model, None) or (None, reason)."""
    try:
        return FIRMSObservationRaw.model_validate(row), None
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:5]
        )
        return None, reasons


def _row_dict(row: dict) -> dict:
    """Best-effort JSON-safe snapshot of a quarantined row."""
    try:
        import json

        return json.loads(json.dumps(row, default=str))
    except Exception:
        return {"raw": str(row)}


async def ingest_observations_batch(
    session: AsyncSession,
    rows: list[dict],
    batch_id: str | None = None,
) -> IngestResult:
    """Idempotently ingest a batch of raw FIRMS row dicts.

    Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING for atomic idempotency.
    Replaying the same batch produces duplicates=N, accepted=0.
    """
    result = IngestResult(
        batch_id=batch_id,
        accepted=0,
        duplicates=0,
        quarantined=0,
        incidents_touched=0,
        assessments=0,
    )

    for row in rows:
        raw, error = validate_row(row)
        if raw is None:
            # Quarantine malformed rows — never block the batch
            result.quarantined += 1
            result.errors.append({"error": error, "row": _row_dict(row)})
            session.add(
                QuarantinedRecord(
                    provider="firms",
                    error_reason=error or "unknown",
                    error_category="validation_error",
                    raw_payload=_row_dict(row),
                )
            )
            continue

        try:
            normalized: ObservationNormalized = normalize_observation(raw)
        except Exception as exc:  # normalization is total; belt-and-braces quarantine
            result.quarantined += 1
            result.errors.append({"error": str(exc), "row": _row_dict(row)})
            session.add(
                QuarantinedRecord(
                    provider="firms",
                    error_reason=str(exc),
                    error_category=type(exc).__name__,
                    raw_payload=_row_dict(row),
                )
            )
            continue

        stmt = (
            pg_insert(Observation)
            .values(
                provider=normalized.provider,
                provider_observation_key=normalized.provider_observation_key,
                observed_at=normalized.observed_at,
                latitude=normalized.latitude,
                longitude=normalized.longitude,
                location=WKTElement(
                    f"POINT({normalized.longitude} {normalized.latitude})", srid=4326
                ),
                sensor=normalized.sensor.value,
                platform=normalized.platform.value,
                scan=normalized.scan,
                track=normalized.track,
                brightness_ti4=normalized.brightness_ti4,
                brightness_ti5=normalized.brightness_ti5,
                frp=normalized.frp,
                confidence=normalized.confidence.value,
                day_night=normalized.day_night.value,
                ingest_status="accepted",
                quality_flags=normalized.quality_flags,
                raw_payload=normalized.raw_payload,
            )
            .on_conflict_do_nothing(
                index_elements=["provider", "provider_observation_key"]
            )
            .returning(Observation)
        )
        inserted = await session.execute(stmt)
        inserted_row = inserted.scalars().first()
        if inserted_row is not None:
            result.accepted += 1
            result.accepted_rows.append(inserted_row)  # consumed by pipeline_v2
        else:
            result.duplicates += 1

    logger.info(
        "ingest.batch_completed",
        accepted=result.accepted,
        duplicates=result.duplicates,
        quarantined=result.quarantined,
        batch_id=batch_id,
    )
    return result


async def count_observations(session: AsyncSession) -> int:
    """Total persisted observations (used by tests and diagnostics)."""
    from sqlalchemy import func

    return int(await session.scalar(select(func.count()).select_from(Observation)) or 0)
