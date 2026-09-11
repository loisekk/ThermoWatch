import { API_BASE } from './client';

/** Live WS frame — server /ws/live taxonomy (fire:new, fire:classified,
 *  persistence:detected, alert:triggered, system:status). */
export interface LiveMessage {
  type: string;
  timestamp?: string;
  clients?: number;
  events?: unknown[];
  event?: unknown;
}

export interface LiveHandlers {
  onEvents: (events: unknown[]) => void;
  onMessage: (msg: LiveMessage) => void;
  onStatus: (online: boolean) => void;
}

/** WS live feed with exponential-backoff reconnect. */
export function connectLive(h: LiveHandlers): () => void {
  let ws: WebSocket | null = null;
  let retry = 1500;
  let closed = false;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${API_BASE.replace(/^http/, 'ws')}/api/v1/ws/live`);
    ws.onopen = () => { retry = 1500; h.onStatus(true); };
    ws.onmessage = (m) => {
      try {
        const msg = JSON.parse(m.data as string) as LiveMessage;
        if (msg.type === 'fire:new' && Array.isArray(msg.events)) h.onEvents(msg.events);
        h.onMessage(msg);
      } catch { /* ignore malformed frame */ }
    };
    ws.onclose = () => { h.onStatus(false); if (!closed) setTimeout(open, retry = Math.min(retry * 2, 15_000)); };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => { closed = true; ws?.close(); };
}
