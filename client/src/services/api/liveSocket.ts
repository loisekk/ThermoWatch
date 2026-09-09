import { API_BASE } from './client';

/** WS live feed with exponential-backoff reconnect. */
export function connectLive(onEvents: (events: unknown[]) => void, onStatus: (online: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let retry = 1500;
  let closed = false;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${API_BASE.replace(/^http/, 'ws')}/api/v1/ws/live`);
    ws.onopen = () => { retry = 1500; onStatus(true); };
    ws.onmessage = (m) => {
      try {
        const msg = JSON.parse(m.data as string);
        if (msg.type === 'fire:new' && Array.isArray(msg.events)) onEvents(msg.events);
      } catch { /* ignore malformed frame */ }
    };
    ws.onclose = () => { onStatus(false); if (!closed) setTimeout(open, retry = Math.min(retry * 2, 15_000)); };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => { closed = true; ws?.close(); };
}
