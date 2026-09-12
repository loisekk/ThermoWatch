import { useEffect } from 'react';
import { connectLive, type LiveMessage } from '@/services/api/liveSocket';
import { api, waitUntilHealthy } from '@/services/api/client';
import { mapServerEvents } from '@/services/api/mappers';
import { useFireStore } from '@/store/useFireStore';

/** When the FastAPI backend is reachable, server events replace the local sim feed.
 *  Consumes the full WS taxonomy: fire:new adopts events, the classified /
 *  persistence / alert frames drive the console ticker + alert board.
 *  Cold-start resilient: probes healthz on a retry ladder, then keeps a 30 s
 *  re-probe so the feed flips back to LIVE when a sleeping Render instance wakes. */
function onLiveMessage(msg: LiveMessage): void {
  const st = useFireStore.getState();

  if (msg.type === 'fire:classified' && Array.isArray(msg.events)) {
    const evts = mapServerEvents(msg.events);
    if (evts.length) st.adoptServerEvents(evts);
    for (const e of evts) {
      st.pushServerLog('classify', `CLASSIFIED ${e.id} -> ${e.classification.primary} (conf ${e.classification.confidence}%)`, 'fire:classified');
    }
  } else if (msg.type === 'persistence:detected' && Array.isArray(msg.events)) {
    for (const e of mapServerEvents(msg.events)) {
      st.pushServerLog('classify', `PERSISTENCE DETECTED ${e.id} - cell crossed >=5 detection-days (STA rule)`, 'persistence:detected');
    }
  } else if (msg.type === 'alert:triggered' && Array.isArray(msg.events)) {
    for (const e of mapServerEvents(msg.events)) st.adoptServerAlert(e);
  } else if (msg.type === 'system:status') {
    st.pushServerLog('system', `WS UP - clients ${msg.clients ?? 0} - ${msg.events ?? 0} events buffered`, 'system:status');
  }
}

function attachFeed(): () => void {
  const store = useFireStore.getState();
  store.setSource('server');
  void api
    .get<unknown[]>('/api/v1/events?window_hours=336')
    .then((evts) => useFireStore.getState().setServerEvents(mapServerEvents(evts)))
    .catch(() => { /* initial fetch failed; WS may still deliver */ });
  return connectLive({
    onEvents: (events) => useFireStore.getState().adoptServerEvents(mapServerEvents(events)),
    onMessage: onLiveMessage,
    onStatus: (online) => useFireStore.getState().setSource(online ? 'server' : 'sim'),
  });
}

export function useBackendFeed(): void {
  useEffect(() => {
    const store = useFireStore.getState();
    let dispose: (() => void) | undefined;
    let wakeTimer: number | undefined;
    let alive = true;

    const tryConnect = () => {
      if (!alive || dispose) return;
      dispose = attachFeed();
    };

    waitUntilHealthy()
      .then((ok) => {
        if (!alive) return;
        if (ok) tryConnect();
        else store.setSource('sim');
      });

    // Every 30 s re-probe: if we're offline and Render has woken, connect up.
    const tick = async () => {
      if (!alive || dispose) return;
      const ok = await waitUntilHealthy([0]).catch(() => false);
      if (alive && ok && !dispose) tryConnect();
    };
    wakeTimer = window.setInterval(() => void tick(), 30_000);

    return () => { alive = false; dispose?.(); if (wakeTimer) window.clearInterval(wakeTimer); };
  }, []);
}
