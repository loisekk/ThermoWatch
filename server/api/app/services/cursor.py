"""Opaque keyset-pagination cursors (Phase 4).

A cursor is base64url(JSON ``{t: iso-timestamp, i: uuid}``) — ``(last_seen_at,
id)`` for the incident queue, ``(observed_at, id)`` for the observation
timeline. Timestamps are always normalised to UTC-aware datetimes; decoding a
malformed cursor raises :class:`CursorError` (the API maps it to 400).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import UUID


class CursorError(ValueError):
    """Raised when a pagination cursor cannot be decoded."""


def encode_cursor(last_seen_at: datetime, last_id: UUID) -> str:
    """Encode the (timestamp, id) keyset position into an opaque cursor."""
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    payload = {"t": last_seen_at.astimezone(timezone.utc).isoformat(), "i": str(last_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Decode a cursor back into its (timestamp, id) keyset position."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        ts = datetime.fromisoformat(str(payload["t"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, UUID(str(payload["i"]))
    except Exception as exc:  # noqa: BLE001 — every decode failure is a client error
        raise CursorError("Invalid cursor") from exc
