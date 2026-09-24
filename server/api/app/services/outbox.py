"""Transactional outbox helpers (Phase 2).

Events are written by `emit()` inside the SAME transaction as the state change
they describe, then drained by `publish_pending()` after commit.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent

logger = structlog.get_logger(__name__)

# Broadcast callback registry — the WS module registers here.
# Default is empty so the outbox works without WS wiring.
BroadcastFn = Callable[[OutboxEvent], Awaitable[None]]
_broadcasters: list[BroadcastFn] = []


def register_broadcaster(fn: BroadcastFn) -> None:
    """WS manager registers a callback: fn(event: OutboxEvent) -> Awaitable[None]."""
    _broadcasters.append(fn)


async def emit(
    session: AsyncSession,
    event_type: str,
    entity_type: str,
    entity_id,
    entity_version: int | None,
    payload: dict,
) -> None:
    """Write an outbox row inside the current transaction. Call BEFORE commit."""
    session.add(OutboxEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_version=entity_version,
        payload=payload,
    ))


async def publish_pending(session: AsyncSession, limit: int = 100) -> int:
    """Drain unpublished outbox rows -> broadcast -> mark published.

    Safe to retry: consumers dedupe by event id.
    """
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.committed_at)
        .limit(limit)
    )
    events = result.scalars().all()
    for ev in events:
        for fn in _broadcasters:
            try:
                await fn(ev)
            except Exception as exc:  # never let one consumer block the drain
                logger.warning(
                    "outbox.broadcast_failed", event_id=str(ev.id), error=str(exc)
                )
        ev.published_at = ev.committed_at  # marked processed; clock skew irrelevant
    await session.commit()
    return len(events)
