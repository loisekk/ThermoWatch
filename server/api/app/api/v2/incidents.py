"""Incident endpoints (Phase 4): queue (cursor-paginated), evidence dossier,
observation timeline, analyst reviews (optimistic concurrency + idempotency)
and the markdown report export.

Design notes:
- The queue paginates on the ``(last_seen_at, id)`` keyset — stable under
  inserts, no OFFSET scans. ``activity`` / ``min_confidence`` are post-filters
  on the latest assessment; pages are scanned in bounded batches so filtered
  pages stay correct without an unbounded scan.
- Reviews are append-only audit rows. Transition legality lives in
  ``app.services.review_rules`` (mirrored, never trusted, by the UI).
- Every state change writes an outbox event in the SAME transaction (the WS
  stream broadcasts it after commit).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_write_token
from app.db.base import get_session
from app.db.models import (
    Assessment,
    ContextRecord,
    IncidentCandidate,
    IncidentObservation,
    Observation,
    ReviewEvent,
)
from app.services.cursor import CursorError, decode_cursor, encode_cursor
from app.services.outbox import emit
from app.services.review_rules import (
    MIN_NOTE_CHARS,
    allowed_actions,
    is_transition_valid,
    note_required,
    note_sufficient,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# =====================================================================
# Response schemas
# =====================================================================
class AssessmentSummary(BaseModel):
    """Compact latest-assessment card shown on a queue row."""

    id: UUID
    assessment_version: str
    assessed_at: datetime
    status: str
    top_class: str
    top_confidence: float | None
    activity_state: str
    abstain_reason: str | None


class IncidentSummary(BaseModel):
    """Row in the analyst incident queue — compact, no linked collections."""

    id: UUID
    status: str
    version: int
    centroid_latitude: float
    centroid_longitude: float
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int
    current_assessment: AssessmentSummary | None
    days_active: int


class IncidentListResponse(BaseModel):
    """Cursor-paginated queue page. ``total_approx`` counts THIS page only —
    the keyset scan has no exact total without a full-table count."""

    incidents: list[IncidentSummary]
    next_cursor: str | None
    total_approx: int


class ObservationDetail(BaseModel):
    id: UUID
    observed_at: datetime
    ingested_at: datetime
    latitude: float
    longitude: float
    sensor: str
    platform: str
    frp: float | None
    brightness_ti4: float | None
    confidence: str
    day_night: str
    scan: float
    track: float
    association_score: float
    association_method: str
    association_rationale: dict[str, Any]


class AssessmentDetail(BaseModel):
    id: UUID
    assessment_version: str
    normal_state_version: str | None
    assessed_at: datetime
    source_class_scores: dict[str, float]
    activity_state: str
    residuals: dict[str, Any] | None
    status: str
    confidence: float | None
    abstain_reason: str | None
    evidence_quality: dict[str, Any]
    explanation: dict[str, Any]
    feature_schema_version: str
    model_config_version: str


class ReviewDetail(BaseModel):
    id: UUID
    actor_id: str
    action: str
    note: str | None
    occurred_at: datetime
    expected_incident_version: int
    resulting_incident_version: int


class ContextDetail(BaseModel):
    provider: str
    provider_type: str
    retrieved_at: datetime
    distance_m: float | None
    payload: dict[str, Any]


class IncidentDossier(BaseModel):
    """Full evidence dossier — everything the analyst needs to review."""

    id: UUID
    status: str
    version: int
    created_at: datetime
    centroid_latitude: float
    centroid_longitude: float
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int
    association_rule_version: str
    observations: list[ObservationDetail]
    assessments: list[AssessmentDetail]
    reviews: list[ReviewDetail]
    context: list[ContextDetail]


class ReviewRequest(BaseModel):
    """POST body for an analyst review action."""

    actor_id: str = Field("analyst-demo", min_length=1, max_length=64)
    action: str = Field(..., pattern="^(needs_review|reviewed|escalated|dismissed)$")
    note: str | None = Field(None, max_length=2000)
    expected_incident_version: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=8, max_length=64)


class ReviewResponse(BaseModel):
    review_id: UUID
    incident_id: UUID
    new_status: str
    new_version: int
    occurred_at: datetime


class TimelineEntry(BaseModel):
    id: UUID
    observed_at: datetime
    latitude: float
    longitude: float
    sensor: str
    platform: str
    frp: float | None
    brightness_ti4: float | None
    confidence: str
    day_night: str


class TimelineResponse(BaseModel):
    observations: list[TimelineEntry]
    next_cursor: str | None


# __PART2__


# =====================================================================
# Shared dossier assembly (used by the dossier endpoint AND the report)
# =====================================================================
async def _latest_assessments(
    session: AsyncSession, incident_ids: list[UUID]
) -> dict[UUID, Assessment]:
    """Latest assessment per incident in ONE query (DISTINCT ON)."""
    if not incident_ids:
        return {}
    rows = (await session.execute(
        select(Assessment)
        .where(Assessment.incident_id.in_(incident_ids))
        .distinct(Assessment.incident_id)
        .order_by(Assessment.incident_id, Assessment.assessed_at.desc())
    )).scalars().all()
    return {a.incident_id: a for a in rows}


def _summary_from_assessment(a: Assessment) -> AssessmentSummary:
    scores: dict[str, float] = a.source_class_scores or {}
    top_class = max(scores, key=lambda k: scores[k]) if scores else "unknown"
    return AssessmentSummary(
        id=a.id,
        assessment_version=a.assessment_version,
        assessed_at=a.assessed_at,
        status=a.status,
        top_class=top_class,
        top_confidence=round(scores.get(top_class, 0.0), 4),
        activity_state=a.activity_state,
        abstain_reason=a.abstain_reason,
    )


async def _load_dossier(
    session: AsyncSession, incident_id: UUID, *, for_update: bool = False,
) -> IncidentCandidate:
    """Fetch the incident or raise 404 (shared by dossier/report/review).

    ``for_update=True`` issues SELECT ... FOR UPDATE so concurrent review
    submissions serialize on the row lock: the loser re-reads the committed
    version and fails the optimistic-concurrency check with 409 instead of
    two writers both passing it.
    """
    inc = await session.get(
        IncidentCandidate, incident_id, with_for_update=for_update
    )
    if not inc:
        raise HTTPException(
            status_code=404, detail=f"Incident {incident_id} not found"
        )
    return inc


# __PART2B__


# =====================================================================
# GET /v2/incidents — the analyst queue
# =====================================================================
@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    session: AsyncSession = Depends(get_session),
    status_filter: str | None = Query(
        None, alias="status",
        pattern="^(needs_review|reviewed|escalated|dismissed)$",
        description="Filter by analyst disposition",
    ),
    activity: str | None = Query(
        None,
        pattern="^(acute|recurring|persistent|changing|insufficient_history|unknown)$",
        description="Filter by latest-assessment activity state",
    ),
    min_confidence: float | None = Query(None, ge=0, le=1),
    start_time: datetime | None = Query(
        None, description="Only incidents last seen at/after this time"
    ),
    end_time: datetime | None = Query(
        None, description="Only incidents last seen at/before this time"
    ),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(50, ge=1, le=200),
) -> IncidentListResponse:
    """Cursor-paginated incident queue, newest activity first.

    Keyset order: ``last_seen_at DESC, id DESC``. ``activity`` /
    ``min_confidence`` post-filter on the latest assessment (bounded batch
    scans keep filtered pages correct without an unbounded query).
    """
    try:
        cur_time, cur_id = decode_cursor(cursor) if cursor else (None, None)
    except CursorError:
        raise HTTPException(status_code=400, detail="Invalid cursor") from None

    if cursor:
        # Merge the cursor position into the scan start.
        if cur_time is None or cur_id is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        last_seen: tuple[datetime, UUID] | None = (cur_time, cur_id)
    else:
        last_seen = None

    # Bounded batch scan: with an assessment post-filter a single page may not
    # fill up, so we walk the keyset in fetch-batches until the page is full
    # or the scan budget is exhausted (never an unbounded loop).
    SCAN_BATCH = 200
    MAX_BATCHES = 10

    items: list[IncidentSummary] = []
    next_cursor: str | None = None
    exhausted = False

    for _ in range(MAX_BATCHES):
        stmt = select(IncidentCandidate)
        if status_filter:
            stmt = stmt.where(IncidentCandidate.status == status_filter)
        if start_time:
            stmt = stmt.where(IncidentCandidate.last_seen_at >= start_time)
        if end_time:
            stmt = stmt.where(IncidentCandidate.last_seen_at <= end_time)
        if last_seen is not None:
            t, i = last_seen
            stmt = stmt.where(
                (IncidentCandidate.last_seen_at < t)
                | ((IncidentCandidate.last_seen_at == t)
                   & (IncidentCandidate.id < i))
            )

        stmt = stmt.order_by(
            IncidentCandidate.last_seen_at.desc(), IncidentCandidate.id.desc()
        ).limit(SCAN_BATCH)

        rows = (await session.execute(stmt)).scalars().all()
        if len(rows) < SCAN_BATCH:
            exhausted = True

        asm_map = await _latest_assessments(session, [r.id for r in rows])

        for inc in rows:
            last_seen = (inc.last_seen_at, inc.id)
            asm = asm_map.get(inc.id)
            if activity and (asm is None or asm.activity_state != activity):
                continue
            if min_confidence is not None and (
                asm is None or (asm.confidence or 0.0) < min_confidence
            ):
                continue

            if len(items) >= limit:
                # Page is full — stop consuming rows; the cursor already
                # points at the last EMITTED row, so the next request
                # resumes exactly here (no skipping, no dupes).
                break

            items.append(IncidentSummary(
                id=inc.id,
                status=inc.status,
                version=inc.version,
                centroid_latitude=inc.centroid_latitude,
                centroid_longitude=inc.centroid_longitude,
                first_seen_at=inc.first_seen_at,
                last_seen_at=inc.last_seen_at,
                observation_count=inc.observation_count,
                current_assessment=_summary_from_assessment(asm) if asm else None,
                days_active=(inc.last_seen_at - inc.first_seen_at).days,
            ))

        if len(items) >= limit or exhausted:
            break

    if len(items) >= limit and last_seen is not None:
        next_cursor = encode_cursor(last_seen[0], last_seen[1])

    return IncidentListResponse(
        incidents=items, next_cursor=next_cursor, total_approx=len(items)
    )


# __PART2C__


# =====================================================================
# GET /v2/incidents/{id} — the evidence dossier
# =====================================================================
@router.get("/{incident_id}", response_model=IncidentDossier)
async def get_incident_dossier(
    incident_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> IncidentDossier:
    """Full evidence dossier: observations, assessments, reviews, context.

    Provider outage does not block the dossier — an empty context list is a
    valid response, never an error.
    """
    inc = await _load_dossier(session, incident_id)

    obs_rows = (await session.execute(
        select(Observation, IncidentObservation)
        .join(IncidentObservation,
              IncidentObservation.observation_id == Observation.id)
        .where(IncidentObservation.incident_id == incident_id)
        .order_by(Observation.observed_at)
    )).all()

    observations = [
        ObservationDetail(
            id=obs.id,
            observed_at=obs.observed_at,
            ingested_at=obs.created_at,
            latitude=obs.latitude,
            longitude=obs.longitude,
            sensor=obs.sensor,
            platform=obs.platform,
            frp=obs.frp,
            brightness_ti4=obs.brightness_ti4,
            confidence=obs.confidence,
            day_night=obs.day_night,
            scan=obs.scan,
            track=obs.track,
            association_score=link.association_score,
            association_method=link.association_method,
            association_rationale=link.rationale or {},
        )
        for obs, link in obs_rows
    ]

    asm_rows = (await session.execute(
        select(Assessment)
        .where(Assessment.incident_id == incident_id)
        .order_by(Assessment.assessed_at.desc(), Assessment.created_at.desc())
    )).scalars().all()

    assessments = [
        AssessmentDetail(
            id=a.id,
            assessment_version=a.assessment_version,
            normal_state_version=a.normal_state_version,
            assessed_at=a.assessed_at,
            source_class_scores=a.source_class_scores or {},
            activity_state=a.activity_state,
            residuals=a.residuals,
            status=a.status,
            confidence=a.confidence,
            abstain_reason=a.abstain_reason,
            evidence_quality=a.evidence_quality or {},
            explanation=a.explanation or {},
            feature_schema_version=a.feature_schema_version,
            model_config_version=a.model_config_version,
        )
        for a in asm_rows
    ]

    rev_rows = (await session.execute(
        select(ReviewEvent)
        .where(ReviewEvent.incident_id == incident_id)
        .order_by(ReviewEvent.occurred_at.desc())
    )).scalars().all()

    reviews = [
        ReviewDetail(
            id=r.id,
            actor_id=r.actor_id,
            action=r.action,
            note=r.note,
            occurred_at=r.occurred_at,
            expected_incident_version=r.expected_incident_version,
            resulting_incident_version=r.resulting_incident_version,
        )
        for r in rev_rows
    ]

    ctx_rows = (await session.execute(
        select(ContextRecord)
        .where(ContextRecord.incident_id == incident_id)
        .order_by(ContextRecord.retrieved_at.desc())
        .limit(10)
    )).scalars().all()

    context = [
        ContextDetail(
            provider=c.provider,
            provider_type=c.provider_type,
            retrieved_at=c.retrieved_at,
            distance_m=c.distance_m,
            payload=c.payload or {},
        )
        for c in ctx_rows
    ]

    return IncidentDossier(
        id=inc.id,
        status=inc.status,
        version=inc.version,
        created_at=inc.created_at,
        centroid_latitude=inc.centroid_latitude,
        centroid_longitude=inc.centroid_longitude,
        first_seen_at=inc.first_seen_at,
        last_seen_at=inc.last_seen_at,
        observation_count=inc.observation_count,
        association_rule_version=inc.association_rule_version,
        observations=observations,
        assessments=assessments,
        reviews=reviews,
        context=context,
    )


# __PART3__


# =====================================================================
# GET /v2/incidents/{id}/timeline — chronological observations
# =====================================================================
@router.get("/{incident_id}/timeline", response_model=TimelineResponse)
async def get_incident_timeline(
    incident_id: UUID,
    session: AsyncSession = Depends(get_session),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(100, ge=1, le=500),
) -> TimelineResponse:
    """Cursor-paginated chronological observation timeline (newest first)."""
    await _load_dossier(session, incident_id)

    stmt = (
        select(Observation)
        .join(IncidentObservation,
              IncidentObservation.observation_id == Observation.id)
        .where(IncidentObservation.incident_id == incident_id)
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
    )

    if cursor:
        try:
            cur_time, cur_id = decode_cursor(cursor)
        except CursorError:
            raise HTTPException(status_code=400, detail="Invalid cursor") from None
        stmt = stmt.where(
            (Observation.observed_at < cur_time)
            | ((Observation.observed_at == cur_time) & (Observation.id < cur_id))
        )

    stmt = stmt.limit(limit + 1)
    results = (await session.execute(stmt)).scalars().all()
    has_next = len(results) > limit
    observations = results[:limit]

    next_cursor = (
        encode_cursor(observations[-1].observed_at, observations[-1].id)
        if has_next and observations
        else None
    )

    return TimelineResponse(
        observations=[
            TimelineEntry(
                id=o.id,
                observed_at=o.observed_at,
                latitude=o.latitude,
                longitude=o.longitude,
                sensor=o.sensor,
                platform=o.platform,
                frp=o.frp,
                brightness_ti4=o.brightness_ti4,
                confidence=o.confidence,
                day_night=o.day_night,
            )
            for o in observations
        ],
        next_cursor=next_cursor,
    )


# __PART4__


# =====================================================================
# POST /v2/incidents/{id}/reviews — analyst review action
# =====================================================================
@router.post(
    "/{incident_id}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    incident_id: UUID,
    request: ReviewRequest,
    _auth: None = Depends(require_write_token),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """Record an analyst review action.

    - Idempotency: a repeated ``idempotency_key`` replays the original result.
    - Optimistic concurrency: stale ``expected_incident_version`` -> 409.
    - Transition legality: disallowed changes -> 422 (nothing is recorded).
    - Note policy: ESCALATED / DISMISSED need a substantive note (min 10 chars).
    - Write authorization: requires ``Authorization: Bearer <TW_WRITE_TOKEN>``
      when that setting is configured; open in local mode (see docs/SECURITY.md).
    """
    # Idempotency first: replay the original outcome for a repeated key.
    existing = (await session.execute(
        select(ReviewEvent)
        .where(ReviewEvent.idempotency_key == request.idempotency_key)
    )).scalar_one_or_none()

    if existing:
        if str(existing.incident_id) != str(incident_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "idempotency_key_reused",
                    "message": "Idempotency key already used for a different incident",
                },
            )
        return ReviewResponse(
            review_id=existing.id,
            incident_id=existing.incident_id,
            new_status=existing.action,
            new_version=existing.resulting_incident_version,
            occurred_at=existing.occurred_at,
        )

    inc = await _load_dossier(session, incident_id, for_update=True)

    # Optimistic concurrency: the client read version N; if the row moved on,
    # the write is rejected so the analyst re-reads before retrying.
    if inc.version != request.expected_incident_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "version_conflict",
                "message": (
                    f"Expected version {request.expected_incident_version} "
                    f"but incident is at version {inc.version}. "
                    "Refresh and retry."
                ),
                "current_version": inc.version,
                "current_status": inc.status,
            },
        )

    # Transition legality — an illegal action is never recorded.
    if not is_transition_valid(inc.status, request.action):
        allowed = allowed_actions(inc.status)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_transition",
                "message": (
                    f"Cannot transition from '{inc.status}' to "
                    f"'{request.action}'. Allowed: {allowed}"
                ),
                "current_status": inc.status,
                "allowed": allowed,
            },
        )

    # Note policy (server-side re-check; the schema/UI also enforce it).
    if note_required(request.action) and not note_sufficient(request.note):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "note_required",
                "message": (
                    f"Note (min {MIN_NOTE_CHARS} chars) required for "
                    f"'{request.action}' action"
                ),
            },
        )

    # Commit: review row + status bump + version bump + outbox, atomically.
    now = datetime.now(timezone.utc)
    review = ReviewEvent(
        incident_id=incident_id,
        actor_id=request.actor_id,
        action=request.action,
        note=request.note,
        occurred_at=now,
        expected_incident_version=request.expected_incident_version,
        resulting_incident_version=inc.version + 1,
        idempotency_key=request.idempotency_key,
    )
    session.add(review)

    inc.status = request.action
    inc.version += 1

    await emit(
        session, "incident.reviewed", "incident", incident_id, inc.version,
        {
            "incident_id": str(incident_id),
            "action": request.action,
            "version": inc.version,
        },
    )

    # Flush so the review row gets its server-applied defaults (id) BEFORE the
    # response model reads them — the commit itself happens in get_session's
    # teardown after the response is built.
    await session.flush()

    return ReviewResponse(
        review_id=review.id,
        incident_id=incident_id,
        new_status=request.action,
        new_version=inc.version,
        occurred_at=now,
    )


# __PART5__


# =====================================================================
# GET /v2/incidents/{id}/report — markdown report export
# =====================================================================
@router.get("/{incident_id}/report")
async def get_incident_report(
    incident_id: UUID,
    session: AsyncSession = Depends(get_session),
    assessment_version: str | None = Query(
        None, description="Specific assessment version (default: latest)"
    ),
) -> Response:
    """Reproducible markdown report for the handoff step.

    Includes provenance (assessment/model/feature-schema versions), the review
    history and explicit caveats — per the PRD the report must always carry
    honest framing about model estimates and satellite latency.
    """
    inc = await _load_dossier(session, incident_id)
    dossier = await get_incident_dossier(incident_id, session)

    if assessment_version:
        asm = next(
            (a for a in dossier.assessments
             if a.assessment_version == assessment_version),
            None,
        )
        if not asm:
            raise HTTPException(
                status_code=404,
                detail=f"Assessment version {assessment_version} not found",
            )
    else:
        asm = dossier.assessments[0] if dossier.assessments else None

    days_active = (inc.last_seen_at - inc.first_seen_at).days
    lat = dossier.centroid_latitude
    lon = dossier.centroid_longitude
    lon_hemi = "E" if lon >= 0 else "W"

    lines = [
        f"# Incident Report: {dossier.id}",
        "",
        f"**Generated:** "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Status:** {dossier.status.upper()}",
        f"**Incident Version:** {dossier.version}",
        "",
        "## Summary",
        "",
        f"- **Location:** {lat:.4f}\u00b0N, {abs(lon):.4f}\u00b0{lon_hemi}",
        f"- **First Observed:** "
        f"{dossier.first_seen_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Last Observed:** "
        f"{dossier.last_seen_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Duration:** {days_active} days",
        f"- **Observations:** {dossier.observation_count}",
        "",
    ]

    if asm:
        scores = asm.source_class_scores or {}
        top_class = max(scores, key=lambda k: scores[k]) if scores else "unknown"
        conf = (
            f"{asm.confidence:.2f}" if asm.confidence is not None else "N/A"
        )
        lines += [
            "## Assessment",
            "",
            f"- **Assessment Version:** `{asm.assessment_version}`",
            f"- **Model Version:** `{asm.model_config_version}`",
            f"- **Status:** {asm.status.upper()}",
            f"- **Top Source Class:** {top_class} (confidence: {conf})",
            f"- **Activity State:** {asm.activity_state.upper()}",
            f"- **Feature Schema:** `{asm.feature_schema_version}`",
        ]
        if asm.abstain_reason:
            lines.append(f"- **Abstain Reason:** {asm.abstain_reason}")
        residuals = asm.residuals or {}
        if residuals:
            lines += [
                "",
                "### Residuals (deviation from facility normal state)",
                "",
            ]
            for key, value in residuals.items():
                if value is not None:
                    lines.append(f"- {key}: {value}")
        lines.append("")
    else:
        lines += ["## Assessment", "", "No assessment available.", ""]

    if dossier.reviews:
        lines += ["## Review History", ""]
        for r in dossier.reviews:
            note = f" — {r.note}" if r.note else ""
            lines.append(
                f"- **{r.occurred_at.strftime('%Y-%m-%d %H:%M')}** — "
                f"{r.actor_id}: {r.action.upper()}{note}"
            )
        lines.append("")

    lines += [
        "## Observations (most recent 10)",
        "",
        "| # | Observed At | Sensor | FRP (MW) | Confidence | Day/Night |",
        "|---|---|---|---|---|---|",
    ]
    for i, o in enumerate(dossier.observations[-10:]):
        lines.append(
            f"| {i + 1} "
            f"| {o.observed_at.strftime('%Y-%m-%d %H:%M')} "
            f"| {o.sensor}/{o.platform} "
            f"| {o.frp if o.frp is not None else '\u2014'} "
            f"| {o.confidence} "
            f"| {o.day_night} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Caveats",
        "",
        "- Source classification is a **model estimate**, not verified truth.",
        "- Proximity to a mapped facility does not confirm source identity.",
        "- Satellite thermal observations have 3-6 hour latency "
        "(near-real-time, not real-time).",
        "- This report is reproducible for the stated assessment version and "
        "incident version.",
        "",
        f"*Association rule: {dossier.association_rule_version}*",
        "",
        f"*Observations linked: {dossier.observation_count} "
        f"(rows listed above: {min(10, len(dossier.observations))})*",
    ]

    report_text = "\n".join(lines)

    return Response(
        content=report_text,
        media_type="text/markdown",
        headers={
            "Content-Disposition":
                f"attachment; filename=incident_{str(incident_id)[:8]}_report.md"
        },
    )
