"""Observation endpoints (v2): idempotent batch ingest + filtered listing."""
from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_write_token
from app.db.base import get_session
from app.db.models import Observation
from app.schemas.observation import (
    ConfidenceLevel,
    IngestResult,
    ObservationCreate,
    ObservationListResponse,
    ObservationResponse,
    SatellitePlatform,
    SensorType,
)
from app.services.ingest import ingest_observations_batch

router = APIRouter()
logger = structlog.get_logger(__name__)

_CONFIDENCE_ORDER = {"unknown": -1, "low": 0, "nominal": 1, "high": 2}


def _to_response(obs: Observation) -> ObservationResponse:
    """Map an ORM row to the response schema (enums coerce defensively)."""
    try:
        sensor = SensorType(obs.sensor)
    except ValueError:
        sensor = SensorType.VIIRS
    try:
        confidence = ConfidenceLevel(obs.confidence)
    except ValueError:
        confidence = ConfidenceLevel.UNKNOWN
    day_night = "night" if obs.day_night == "night" else "day"
    scan, track = obs.scan, obs.track
    pixel_area = round(scan * track * 111.32 * 111.32, 4) if scan and track else None
    return ObservationResponse(
        id=obs.id,
        provider=obs.provider,
        provider_observation_key=obs.provider_observation_key,
        observed_at=obs.observed_at,
        ingested_at=obs.created_at,
        latitude=obs.latitude,
        longitude=obs.longitude,
        sensor=sensor,
        platform=cast("SatellitePlatform", obs.platform),
        frp=obs.frp,
        brightness_ti4=obs.brightness_ti4,
        brightness_ti5=obs.brightness_ti5,
        confidence=confidence,
        day_night=day_night,  # type: ignore[arg-type]
        ingest_status=obs.ingest_status,  # type: ignore[arg-type]
        quality_flags=obs.quality_flags or {},
        pixel_area_km2=pixel_area,
        is_night=obs.day_night == "night",
    )


@router.post("", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_observations(
    payload: ObservationCreate,
    process: bool = Query(True, description="Run association + assessment pipeline"),
    _auth: None = Depends(require_write_token),
    session: AsyncSession = Depends(get_session),
) -> IngestResult:
    """Batch ingest observations — idempotent, safe to retry.

    Replaying the same batch will not create duplicates; malformed rows are
    quarantined with the validation reason. With ``process=true`` (default),
    accepted rows flow through association + assessment (Phase 2).

    Write authorization: requires ``Authorization: Bearer <TW_WRITE_TOKEN>``
    when that setting is configured; open in local mode (see docs/SECURITY.md).
    """
    result = await ingest_observations_batch(
        session, payload.observations, payload.source_batch_id
    )

    # Phase 2 pipeline: only the actually-INSERTED rows are processed
    # (duplicates were already processed on first arrival — idempotent replay).
    if process and result.accepted_rows:
        from app.services.pipeline_v2 import process_observations

        pipeline_result = await process_observations(
            session, list(result.accepted_rows)
        )
        result.incidents_touched = int(pipeline_result["incidents_touched"])
        result.assessments = int(pipeline_result["assessments"])

    return result


@router.get("", response_model=ObservationListResponse)
async def list_observations(
    session: AsyncSession = Depends(get_session),
    start_time: datetime | None = Query(None, description="ISO 8601 start time"),
    end_time: datetime | None = Query(None, description="ISO 8601 end time"),
    sensor: str | None = Query(None, description="Filter by sensor type"),
    min_confidence: str | None = Query(None, description="Minimum confidence level"),
    bbox: str | None = Query(
        None,
        description="Bounding box: minLon,minLat,maxLon,maxLat",
        pattern=r"^-?\d+\.?\d*,-?\d+\.?\d*,-?\d+\.?\d*,-?\d+\.?\d*$",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> ObservationListResponse:
    """List observations with time/sensor/confidence/bbox filters + pagination."""
    stmt = select(Observation)

    if start_time:
        stmt = stmt.where(Observation.observed_at >= start_time)
    if end_time:
        stmt = stmt.where(Observation.observed_at <= end_time)
    if sensor:
        stmt = stmt.where(Observation.sensor == sensor.lower())

    if min_confidence:
        min_level = _CONFIDENCE_ORDER.get(min_confidence.lower(), 0)
        if min_level >= 0:
            allowed = [
                c for c, lvl in _CONFIDENCE_ORDER.items() if lvl >= min_level
            ]
            stmt = stmt.where(Observation.confidence.in_(allowed))

    if bbox:
        from geoalchemy2 import Geometry

        try:
            min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid bbox format: {bbox}")
        # Geography column must be cast to geometry for ST_Within/ST_MakeEnvelope
        stmt = stmt.where(
            func.ST_Within(
                Observation.location.cast(Geometry),
                func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await session.scalar(count_stmt) or 0

    stmt = stmt.order_by(Observation.observed_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    observations = result.scalars().all()

    return ObservationListResponse(
        observations=[_to_response(o) for o in observations],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


@router.get("/{observation_id}", response_model=ObservationResponse)
async def get_observation(
    observation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ObservationResponse:
    """Get a single observation by ID."""
    obs = await session.get(Observation, observation_id)
    if not obs:
        raise HTTPException(
            status_code=404, detail=f"Observation {observation_id} not found"
        )
    return _to_response(obs)
