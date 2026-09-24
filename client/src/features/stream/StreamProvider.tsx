/**
 * WebSocket connection to /v2/stream. On each event, invalidates the relevant
 * TanStack Query cache; after a reconnect with a sequence gap, triggers a full
 * REST resync. Exponential-backoff reconnect; 30 s heartbeat keepalive.
 */
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { V2_STREAM_URL } from '@/services/api/v2Client';
import { routeStreamEvent, shouldProcessSequence } from '@/features/queue/queueUtils';
import type { StreamEvent } from '@/services/api/v2Types';

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000];

export function StreamProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const retryCountRef = useRef(0);
  const lastSequenceRef = useRef(0);

  useEffect(() => {
    let mounted = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let pingInterval: ReturnType<typeof setInterval> | undefined;
    let ws: WebSocket | null = null;

    const handleEvent = (event: StreamEvent) => {
      if (!shouldProcessSequence(event.sequence, lastSequenceRef.current)) return;
      lastSequenceRef.current = event.sequence;
      for (const { queryKey } of routeStreamEvent(event)) {
        void qc.invalidateQueries({ queryKey });
      }
    };

    const connect = () => {
      if (!mounted) return;
      ws = new WebSocket(V2_STREAM_URL);

      ws.onopen = () => {
        retryCountRef.current = 0;
        // Reconnected after a gap — the WS never replays history, so refresh
        // from REST (the server answers with a resync_ack frame).
        if (lastSequenceRef.current > 0) {
          ws?.send('resync');
          void qc.invalidateQueries({ queryKey: ['incidents'] });
        }
        pingInterval = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send('ping');
        }, 30_000);
      };

      ws.onmessage = (e: MessageEvent) => {
        try {
          const event = JSON.parse(String(e.data)) as StreamEvent;
          if (event.event_type === 'pong' || event.event_type === 'resync_ack') return;
          handleEvent(event);
        } catch {
          // Malformed frame — ignore, stay connected.
        }
      };

      ws.onclose = () => {
        if (pingInterval) clearInterval(pingInterval);
        if (!mounted) return;
        const delay = RECONNECT_DELAYS[
          Math.min(retryCountRef.current, RECONNECT_DELAYS.length - 1)
        ];
        retryCountRef.current += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => ws?.close();
    };

    connect();

    return () => {
      mounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingInterval) clearInterval(pingInterval);
      ws?.close();
    };
  }, [qc]);

  return <>{children}</>;
}
