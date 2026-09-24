"""Ingest -> associate -> assess orchestration (V2 data flow).

NOTE: this is the v2 (DB-backed) orchestrator — the v1 in-memory pipeline
lives in app/services/pipeline.py and is untouched (both serve concurrently).

Bulkhead property: an assessment failure never blocks the committed
observation — it is logged and skipped; the next ingest pass re-runs it.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Observation
from app.services.assessment import assess_incident
from app.services.association import associate_observation

logger = structlog.get_logger(__name__)


async def process_observations(
    session: AsyncSession, observations: list[Observation]
) -> dict:
    """Run association + assessment for freshly ingested observations.

    Returns counts for the ingest response.
    """
    affected: set[str] = set()
    for obs in observations:
        touched = await associate_observation(session, obs)
        affected.update(touched)

    assessed = 0
    for iid in affected:
        try:
            if await assess_incident(session, iid):
                assessed += 1
        except Exception as exc:
            # Assessment failure must never block the committed observation.
            logger.warning(
                "pipeline.assessment_failed", incident_id=iid, error=str(exc)
            )

    logger.info(
        "pipeline.processed", observations=len(observations),
        incidents_touched=len(affected), assessments=assessed,
    )
    return {"incidents_touched": len(affected), "assessments": assessed}
