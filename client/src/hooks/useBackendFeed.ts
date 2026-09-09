import { useEffect } from 'react';
import { connectLive } from '@/services/api/liveSocket';
import { api } from '@/services/api/client';
import { mapServerEvents } from '@/services/api/mappers';
import { useFireStore } from '@/store/useFireStore';

/** When the FastAPI backend is reachable, server events replace the local sim feed. */
export function useBackendFeed(): void {
  useEffect(() => {
    const store = useFireStore.getState();
    let dispose: (() => void) | undefined;
    let alive = true;

    api.health()
      .then(() => {
        if (!alive) return;
        store.setSource('server');
        void api
          .get<unknown[]>('/api/v1/events?window_hours=336')
          .then((evts) => useFireStore.getState().setServerEvents(mapServerEvents(evts)))
          .catch(() => { /* initial fetch failed; WS may still deliver */ });
        dispose = connectLive(
          (events) => useFireStore.getState().adoptServerEvents(mapServerEvents(events)),
          (online) => useFireStore.getState().setSource(online ? 'server' : 'sim'),
        );
      })
      .catch(() => store.setSource('sim'));

    return () => { alive = false; dispose?.(); };
  }, []);
}
