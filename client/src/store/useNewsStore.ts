/** LIVE WIRE store — 5-min poll aligned to the server TTL, single-flight sync,
 *  exponential backoff on errors (15 min max), TV strip state survives panel
 *  switches. Poll is paused while the tab is hidden. */
import { create } from 'zustand';
import { fetchNewsFeed } from '@/features/news/newsWireClient';
import type { NewsFeed } from '@/features/news/types';

interface NewsState {
  feed: NewsFeed | null;
  status: 'idle' | 'loading' | 'live' | 'error';
  error: string | null;
  lastSyncAt: number | null;
  tvOn: boolean;
  tvChannel: string;
  setTv: (channelKey: string | null) => void;
  sync: () => Promise<void>;
}

let inFlight: Promise<void> | null = null;

export const useNewsStore = create<NewsState>()((set, get) => ({
  feed: null,
  status: 'idle',
  error: null,
  lastSyncAt: null,
  tvOn: false,
  tvChannel: 'aje',
  setTv: (key) => set(key === null ? { tvOn: false } : { tvOn: true, tvChannel: key }),
  sync: async () => {
    if (inFlight) return inFlight;
    set({ status: get().feed ? 'live' : 'loading', error: null });
    inFlight = (async () => {
      try {
        const feed = await fetchNewsFeed();
        set({ feed, status: 'live', lastSyncAt: Date.now() });
      } catch (e) {
        set({ status: 'error', error: e instanceof Error ? e.message : String(e) });
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  },
}));

const BASE_MS = 300_000; // 5 min = server TTL

/** 5-min poll, paused when the tab is hidden, backoff to 15 min after errors. */
export function startNewsPolling(): () => void {
  let backoff = 1;
  let timer = 0;
  const tick = async (): Promise<void> => {
    if (!document.hidden) {
      const before = useNewsStore.getState().status;
      await useNewsStore.getState().sync();
      const after = useNewsStore.getState().status;
      backoff = after === 'error' && before !== 'error' ? Math.min(backoff * 2, 3) : 1;
    }
    timer = window.setTimeout(() => void tick(), BASE_MS * backoff);
  };
  timer = window.setTimeout(() => void tick(), 2_000);
  return () => window.clearTimeout(timer);
}
