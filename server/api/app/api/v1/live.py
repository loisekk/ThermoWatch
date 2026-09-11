"""WebSocket live-feed manager implementing the KB §21.6 event taxonomy.

Broadcast types:
  - fire:new             raw detections that just entered the store
  - fire:classified      the same detections, post-feature-engineering risk
  - persistence:detected detections whose 400 m cell is in a persistent STA regime
  - alert:triggered      detections with high/critical risk
  - system:status        30 s heartbeat (clients + buffered event count)
"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings

router = APIRouter()


class Manager:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self.heartbeat_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, payload: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 — one bad client must never break the fan-out
                self.disconnect(ws)

    async def announce(self, events: list[dict]):
        """Post-ingest taxonomy fan-out for a batch of enriched events."""
        if not events:
            return
        await self.broadcast({"type": "fire:new", "events": events})
        await self.broadcast({"type": "fire:classified", "events": events})
        crossing = [e for e in events if e["persistence"]["regime"] == "persistent"]
        if crossing:
            await self.broadcast({"type": "persistence:detected", "events": crossing})
        hot = [e for e in events if e["risk"]["level"] in ("high", "critical")]
        if hot:
            await self.broadcast({"type": "alert:triggered", "events": hot})

    async def heartbeat_loop(self):
        from app.services import event_store  # local import avoids any module cycle

        while True:
            await asyncio.sleep(30)
            await self.broadcast({
                "type": "system:status",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "clients": len(self.clients),
                "events": len(event_store.all_events()),
            })


manager = Manager()


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    # Origin allow-list (server-to-server clients send no Origin and are allowed).
    origin = ws.headers.get("origin") or ""
    if origin and not any(origin.rstrip("/") == o.rstrip("/") for o in settings.origins):
        await ws.close(code=4403)
        return
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # client pings; server pushes events
    except WebSocketDisconnect:
        manager.disconnect(ws)
