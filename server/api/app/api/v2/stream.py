"""WebSocket stream (Phase 4): broadcasts outbox events to connected clients.

Event envelope:
    {event_id, sequence, entity_type, entity_id, entity_version,
     event_type, committed_at, schema_version}

Clients dedupe by event_id, track the sequence for gap detection, and fall
back to a REST resync after a reconnect (the server never replays history —
``resync_ack`` tells the client to refresh from the REST endpoints).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.models import OutboxEvent
from app.services.outbox import register_broadcaster

router = APIRouter()
logger = structlog.get_logger(__name__)


class ConnectionManager:
    """Tracks connected WS clients and broadcasts outbox events."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("ws.connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("ws.disconnected", total=len(self._connections))

    async def broadcast(self, event: OutboxEvent) -> None:
        """Format an outbox event and send it to every connected client.

        Registered as the outbox broadcaster — invoked by ``publish_pending()``
        on the drain loop. A dead socket never blocks delivery to the rest.
        """
        async with self._lock:
            self._sequence += 1
            committed_at = (
                event.committed_at.isoformat()
                if hasattr(event.committed_at, "isoformat")
                else str(event.committed_at)
            )
            envelope = {
                "event_id": str(event.id),
                "sequence": self._sequence,
                "entity_type": event.entity_type,
                "entity_id": str(event.entity_id),
                "entity_version": event.entity_version,
                "event_type": event.event_type,
                "committed_at": committed_at,
                "schema_version": event.schema_version,
            }
            payload = json.dumps(envelope, default=str)
            dead: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:  # noqa: BLE001 — dead socket, drop it
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws)


manager = ConnectionManager()
register_broadcaster(manager.broadcast)


@router.websocket("/stream")
async def stream_endpoint(websocket: WebSocket) -> None:
    """Live event stream.

    Clients send ``ping`` (keepalive) or ``resync`` (after a reconnect gap);
    the server answers with ``pong`` / ``resync_ack`` frames.
    """
    await manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({
                    "event_type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }))
            elif msg == "resync":
                await websocket.send_text(json.dumps({
                    "event_type": "resync_ack",
                    "message": "Refresh state from REST endpoints",
                }))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:  # noqa: BLE001 — drop the socket, never crash the app
        logger.warning("ws.error", error=str(exc))
        manager.disconnect(websocket)
