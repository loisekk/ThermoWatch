"""Incident association engine — spatial-temporal grouping with stored rationale.

Every link/create decision stores: rule version, parameters, candidates
considered, distance/time deltas, score, and decision. Original observations
are never mutated. Incident version bumps on every modification.

Association never uses facility proximity as evidence of source identity
(V2 doc, Addendum A) — proximity is recorded in the rationale, not the score.
"""
from __future__ import annotations

import math
from datetime import timedelta

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import IncidentCandidate, IncidentObservation, Observation
from app.services.outbox import emit

logger = structlog.get_logger(__name__)


async def associate_observation(
    session: AsyncSession, observation: Observation
) -> list[str]:
    """Associate one observation into an incident (link or create-new).

    Returns the IDs of incidents touched (1 element; the caller batches
    assessments over the union).
    """
    max_km = settings.assoc_max_distance_km
    max_h = settings.assoc_max_time_hours
    threshold = settings.assoc_link_threshold

    # --- Candidate gate: time window + bbox on centroid floats ---
    time_floor = observation.observed_at - timedelta(hours=max_h)
    time_ceil = observation.observed_at + timedelta(hours=max_h)
    dlat = max_km / 111.32
    dlon = max_km / (
        111.32 * max(math.cos(math.radians(observation.latitude)), 0.01)
    )

    candidates = (await session.execute(
        select(IncidentCandidate).where(
            and_(
                IncidentCandidate.last_seen_at >= time_floor,
                IncidentCandidate.last_seen_at <= time_ceil,
                IncidentCandidate.centroid_latitude.between(
                    observation.latitude - dlat, observation.latitude + dlat
                ),
                IncidentCandidate.centroid_longitude.between(
                    observation.longitude - dlon, observation.longitude + dlon
                ),
            )
        )
    )).scalars().all()

    # --- Score candidates ---
    scored: list[tuple[IncidentCandidate, float, float, float]] = []
    for inc in candidates:
        dist_km = _haversine_km(
            observation.latitude, observation.longitude,
            inc.centroid_latitude, inc.centroid_longitude,
        )
        hours = abs(
            (observation.observed_at - inc.last_seen_at).total_seconds()
        ) / 3600.0
        if dist_km > max_km or hours > max_h:
            continue
        d_score = 1.0 - (dist_km / max_km)
        t_score = 1.0 - (hours / max_h)
        score = d_score * t_score
        scored.append((inc, dist_km, hours, score))

    scored.sort(key=lambda x: -x[3])

    common = {
        "rule_version": settings.assoc_rule_version,
        "parameters": {
            "max_distance_km": max_km, "max_time_hours": max_h,
            "link_threshold": threshold,
        },
        "candidates_considered": len(candidates),
        "observation_id": str(observation.id),
        "sensor": observation.sensor,
    }

    if scored and scored[0][3] >= threshold:
        inc, dist_km, hours, score = scored[0]
        rationale = {
            **common,
            "decision": "linked",
            "distance_km": round(dist_km, 4),
            "hours_delta": round(hours, 2),
            "score": round(score, 4),
            "rejected": [
                {"incident_id": str(i.id), "score": round(s, 4)}
                for i, _, _, s in scored[1:3]
            ],
        }
        await _link(session, inc, observation, score, rationale)
        return [str(inc.id)]

    rationale = {
        **common,
        "decision": "created_new",
        "reason": (
            "no candidate above threshold" if scored else "no candidates in gate"
        ),
        "best_candidate": (
            {"incident_id": str(scored[0][0].id), "score": round(scored[0][3], 4)}
            if scored else None
        ),
    }
    inc = await _create(session, observation, rationale)
    return [str(inc.id)]

async def _link(
    session: AsyncSession,
    incident: IncidentCandidate,
    obs: Observation,
    score: float,
    rationale: dict,
) -> None:
    # Idempotent at the DB level: (incident_id, observation_id) is the PK —
    # re-association of the same observation would raise IntegrityError, which
    # the caller's transaction semantics handle.
    session.add(IncidentObservation(
        incident_id=incident.id, observation_id=obs.id,
        association_score=score,
        association_method=settings.assoc_rule_version,
        rationale=rationale,
    ))
    # Running centroid update (weighted by observation count)
    n = incident.observation_count or 0
    incident.centroid_latitude = (
        incident.centroid_latitude * n + obs.latitude
    ) / (n + 1)
    incident.centroid_longitude = (
        incident.centroid_longitude * n + obs.longitude
    ) / (n + 1)
    incident.first_seen_at = min(incident.first_seen_at, obs.observed_at)
    incident.last_seen_at = max(incident.last_seen_at, obs.observed_at)
    incident.observation_count = n + 1
    incident.version += 1
    await emit(
        session, "incident.updated", "incident", incident.id, incident.version,
        {"incident_id": str(incident.id), "version": incident.version,
         "observation_id": str(obs.id)},
    )


async def _create(
    session: AsyncSession, obs: Observation, rationale: dict
) -> IncidentCandidate:
    inc = IncidentCandidate(
        centroid_latitude=obs.latitude,
        centroid_longitude=obs.longitude,
        first_seen_at=obs.observed_at,
        last_seen_at=obs.observed_at,
        association_rule_version=settings.assoc_rule_version,
        association_parameters={"initial_rationale": rationale},
        observation_count=1,
        version=1,
    )
    session.add(inc)
    await session.flush()  # get inc.id
    session.add(IncidentObservation(
        incident_id=inc.id, observation_id=obs.id,
        association_score=1.0,
        association_method=settings.assoc_rule_version,
        rationale=rationale,
    ))
    await emit(
        session, "incident.created", "incident", inc.id, 1,
        {"incident_id": str(inc.id), "version": 1,
         "observation_id": str(obs.id)},
    )
    return inc


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return float(2 * r * math.asin(math.sqrt(a)))
